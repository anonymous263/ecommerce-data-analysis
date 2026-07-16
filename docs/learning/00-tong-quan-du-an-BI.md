# 00 — Tổng quan dự án BI/DA

> Nguồn đối chiếu: `README.md`, `CLAUDE.md` (gốc tiếng Anh của repo).

## 1. BI/DA là gì? Phân biệt các khái niệm

Trước khi đi vào chi tiết dự án, cần tách bạch ba khái niệm hay bị dùng lẫn lộn:

| Khái niệm | Trả lời câu hỏi | Ví dụ trong dự án này |
|---|---|---|
| **Data Analytics (DA — phân tích dữ liệu)** | "Chuyện gì đã xảy ra, tại sao, và tiếp theo nên làm gì?" — thường là phân tích ad-hoc, một lần, đào sâu một câu hỏi cụ thể | Ví dụ: "Vì sao tháng 6 tỷ lệ hoàn tiền (refund) ở site FOS tăng đột biến?" |
| **Business Intelligence (BI — trí tuệ kinh doanh)** | "Số liệu hôm nay là bao nhiêu, và xu hướng thế nào?" — báo cáo/dashboard được **lặp lại định kỳ**, phục vụ nhiều người, tự động cập nhật | Các trang Power BI: Executive Overview, Product Performance, Country Performance... |
| **Data Warehouse (kho dữ liệu)** | "Dữ liệu sạch, đáng tin, có mô hình rõ ràng nằm ở đâu để BI và DA cùng dùng chung?" | Toàn bộ schema Postgres `raw` → `staging` → `marts_*` do dbt xây |

Nói ngắn gọn: **kho dữ liệu là nền móng**, **BI là ngôi nhà** dựng trên nền móng đó (dashboard cố định, lặp lại), còn **DA là hoạt động sống trong ngôi nhà** — dùng cả nền móng lẫn ngôi nhà để trả lời câu hỏi phát sinh. Một dự án BI/DA nghiêm túc không bắt đầu từ việc "vẽ dashboard" — nó bắt đầu từ việc xây kho dữ liệu đúng, vì dashboard đẹp mà số liệu sai thì vô giá trị (garbage in, garbage out).

Dự án này thuộc dạng "warehouse-first": xây kho dữ liệu chuẩn Kimball (xem chương 04) trước, sau đó mới dựng Power BI lên trên. Đây là điểm khác biệt với cách làm BI "dashboard-first" (kéo trực tiếp từ nguồn vào Power BI, không qua kho) — cách làm dashboard-first nhanh lúc đầu nhưng dễ vỡ khi nhiều nguồn dữ liệu, nhiều site, cần lịch sử, hoặc cần tái sử dụng logic nghiệp vụ ở nhiều nơi.

## 2. Bối cảnh & mục tiêu dự án

Dự án là **một kho phân tích riêng tư (private analytics warehouse), portfolio là mục tiêu phụ**, phục vụ nhiều cửa hàng **WooCommerce bán hàng POD (print-on-demand — in theo yêu cầu)**, chủ yếu là áo thun/áo ba lỗ/hoodie, được **fulfillment (đóng gói + giao hàng) bởi các nhà cung cấp bên ngoài** (một số có API, một số không).

Vấn đề thực tế trước khi có dự án: mọi vận hành (COGS, phí thiết kế, nhà cung cấp, mã vận đơn...) đang nằm trong một **Google Sheet thủ công** — hữu ích cho vận hành hằng ngày nhưng **không phải nguồn sự thật** cho doanh thu hay lợi nhuận, và không thể trả lời các câu hỏi tổng hợp như:

- Sản phẩm/chủ đề (topic) nào thực sự có lãi sau phí, COGS, vận chuyển?
- Quốc gia/thị trường nào mua nhiều nhất với biên lợi nhuận tốt nhất?
- Khách rơi rớt ở đâu trong phễu: session → view_item → add_to_cart → begin_checkout → purchase?
- Nhà cung cấp nào fulfill nhanh nhất? Hãng vận chuyển nào gây trễ/lỗi giao hàng nhiều nhất?
- So sánh hiệu quả các site với nhau ra sao?

**Mục tiêu cụ thể** (theo `README.md` §2):

1. Xây kho **PostgreSQL** theo mô hình star schema Kimball (xem chương 04), nguồn chính là WooCommerce, làm giàu bằng sheet chi phí thủ công, mở rộng bằng GA4 BigQuery.
2. Xây script **Python extract/load** nạp dữ liệu thô từ API vào schema `raw`, và các model **dbt** biến đổi `raw → staging → marts`.
3. Xây **dashboard Power BI** hỗ trợ quyết định về mix sản phẩm, giá, nhà cung cấp, vận hành.
4. Phát hành bản **portfolio công khai** dùng dữ liệu **hoàn toàn tổng hợp (synthetic)** — không bao giờ dùng dữ liệu khách hàng thật đã "làm sạch".

## 3. Kiến trúc tổng thể

Bốn pipeline extract/load nạp dữ liệu vào **một** đồ thị biến đổi (transformation graph) của dbt, rồi đổ ra Power BI:

```
┌────────────────────────┐
│  Sources               │
│  - WooCommerce REST API│ (nguồn sự thật: doanh thu, đơn hàng, hoàn tiền)
│  - GA4 BigQuery export │ (nguồn sự thật: hành vi truy cập)
│  - Order Management    │ (nguồn sự thật: COGS + làm giàu fulfillment)
│    sheet / CSV         │
│  - Ads platforms       │ (tùy chọn tương lai — hiện chưa chạy quảng cáo)
└──────────┬─────────────┘
           │
   ┌───────▼────────┐
   │ Python EL      │  chỉ extract/load, KHÔNG business logic
   │ (idempotent)   │
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ schema raw     │  append-only, mỗi dòng có site_code + extracted_at + _payload JSONB
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ dbt staging    │  làm sạch, ép kiểu, băm PII
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ dbt marts      │  dim_*/fact_* + các mart lợi nhuận
   └───────┬────────┘
           │
   ┌───────▼────────┐
   │ Power BI       │  các trang dashboard kích hoạt theo từng phase
   └────────────────┘
```

Chi tiết luồng dữ liệu và lý do tách Python (EL) khỏi dbt (T) được trình bày sâu ở **chương 01**.

## 4. Tech stack

| Lớp | Lựa chọn | Vai trò |
|---|---|---|
| Ngôn ngữ extract/load | Python 3.11 | Kéo dữ liệu từ API/CSV, nạp vào Postgres — không xử lý nghiệp vụ |
| Lưu trữ | PostgreSQL 16 chạy trong Docker | Kho dữ liệu trung tâm — chứa cả `raw`, `staging`, `marts_*` |
| Biến đổi dữ liệu | dbt-core + dbt-postgres | SQL có version control, test, docs — biến `raw` thành `marts` |
| Nguồn hành vi web | BigQuery (GA4 export) | Sessions, events, funnel, landing page |
| Trực quan hóa | Power BI Desktop | Dashboard cuối cùng người dùng nghiệp vụ nhìn thấy |
| Quản lý mã nguồn | Git + GitHub | Version control cho cả code Python và model dbt |

Vì sao chọn tổ hợp này thay vì ví dụ Airflow + Snowflake + Looker? Đây là dự án **một người vận hành (solo)**, quy mô dữ liệu vừa phải (hàng nghìn đơn hàng), nên ưu tiên **công cụ nhẹ, chạy local, chi phí gần bằng 0, nhưng vẫn theo đúng kỷ luật kỹ thuật của một kho dữ liệu thật** (schema phân lớp, test tự động, version control). dbt + Postgres là tổ hợp phổ biến nhất cho quy mô này trong ngành.

## 5. Các giai đoạn (Phase) của dự án

Dự án chia thành 8 phase (0–7), mỗi phase có một "outcome" rõ ràng để biết khi nào xong:

| Phase | Kết quả (outcome) |
|---|---|
| 0 | Postgres + dbt chạy được; các guard bảo vệ PII; cấu hình site; audit nguồn dữ liệu ban đầu |
| 1 | Nạp thô `raw.woo_*` từ WooCommerce + audit payload (`docs/WOO_PAYLOAD_AUDIT.md`) |
| 2 | dbt staging + các mart lõi (core): sales/orders/products/customers/refunds |
| 3 | Làm giàu chi phí thủ công (manual cost enrichment) → `fact_order_cost`, các mart lợi nhuận |
| 4 | Power BI MVP (bản dùng được đầu tiên) |
| 5 | Làm giàu dữ liệu fulfillment → `fact_fulfillment` |
| 6 | Mô hình hóa GA4 BigQuery (có audit gate riêng) |
| 7 | Bộ dữ liệu mẫu tổng hợp (synthetic) công khai + hoàn thiện portfolio |

Điểm đáng chú ý trong thứ tự này: **Phase 3 (làm giàu chi phí) đứng TRƯỚC Phase 4 (Power BI MVP)**. Lý do: COGS (giá vốn hàng bán) chỉ tồn tại trong sheet thủ công — nếu dựng dashboard trước khi có COGS, mọi "lợi nhuận" hiển thị sẽ sai hoặc thiếu. Đây là một bài học áp dụng được cho dự án khác: **đừng dựng dashboard trước khi các input tài chính quan trọng đã sẵn sàng trong kho** — thứ tự phase phải phản ánh sự phụ thuộc dữ liệu thật, không phải thứ tự "dễ làm trước".

Tại thời điểm viết tài liệu này, dự án đang ở cuối Phase 3 (xem `TASKS.md` để biết trạng thái mới nhất) — nghĩa là kho dữ liệu, staging, marts lõi, và làm giàu chi phí đã hoàn tất; Phase 4 (Power BI) là bước tiếp theo.

## Khái niệm áp dụng được

- Trước khi vẽ bất kỳ dashboard nào, hãy tự hỏi: "kho dữ liệu bên dưới có đáng tin không?" — BI đẹp không cứu được dữ liệu sai.
- Chia dự án thành các **phase có outcome đo được**, và sắp thứ tự phase theo **phụ thuộc dữ liệu** (dữ liệu nào cần có trước để phase sau không sai), không phải theo độ dễ.
- Khi nhiều nguồn dữ liệu có mức độ tin cậy khác nhau (API chính thức vs. sheet thủ công), hãy xác định rõ ngay từ đầu ai là "nguồn sự thật" cho từng lĩnh vực dữ liệu (xem chương 02).
- Bản mẫu công khai (portfolio) và dữ liệu thật phải tách biệt triệt để về mặt kiến trúc, không chỉ là "xóa vài cột" trước khi public.
