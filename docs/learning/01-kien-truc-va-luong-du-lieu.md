# 01 — Kiến trúc và luồng dữ liệu

> Nguồn đối chiếu: `CLAUDE.md` (phần Architecture), `docs/PIPELINE_DESIGN.md`, `docs/DATA_MODEL.md`.
> Xem lại bức tranh lớn ở chương 00 trước khi đọc chương này.

## 1. Luồng dữ liệu chi tiết

Toàn bộ hệ thống chỉ có **một hướng chảy dữ liệu**, không có nhánh ngược:

```
Sources → Python EL (extract/load) → Postgres schema `raw`
        → dbt (raw → staging → marts) → Power BI
```

Cụ thể hơn, với 4 pipeline nạp dữ liệu (theo `docs/PIPELINE_DESIGN.md §1`):

```
┌─────────────┐      ┌─────────────┐      ┌──────────────┐
│  Sources    │ ───► │ Python EL   │ ───► │ Postgres raw │
└─────────────┘      └─────────────┘      └──────┬───────┘
                                                 │
                                          ┌──────▼───────┐
                                          │   dbt        │
                                          │  raw → stg → │
                                          │  marts       │
                                          └──────┬───────┘
                                                 ▼
                                            Power BI
```

4 nguồn (mỗi nguồn có pipeline Python riêng, xem chương 02 để biết chi tiết từng nguồn):

1. **WooCommerce REST API** — đơn hàng, sản phẩm, khách hàng, hoàn tiền (Phase 1).
2. **Order Management CSV** (sheet thủ công) — COGS, phí thiết kế, nhà cung cấp, vận đơn (Phase 3 + 5).
3. **GA4 BigQuery export** — session, event, funnel (Phase 6, có audit gate riêng).
4. **Ads platforms** — chi tiêu quảng cáo (Optional Future — hiện chưa triển khai).

Dù nguồn khác nhau, cả 4 pipeline đều đổ vào **cùng một schema `raw`** trong Postgres, và từ đó dbt xử lý **tất cả trong một đồ thị biến đổi duy nhất** — đây là điểm mấu chốt giúp hệ thống nhất quán: logic nghiệp vụ (FX, hash PII, tính lợi nhuận...) chỉ được viết **một lần** trong dbt, áp dụng đồng nhất cho mọi nguồn, mọi site.

## 2. ELT vs ETL — và vì sao dự án chọn ELT

Hai mô hình kinh điển khi xây pipeline dữ liệu:

| | **ETL** (Extract → Transform → Load) | **ELT** (Extract → Load → Transform) |
|---|---|---|
| Thứ tự | Biến đổi dữ liệu **trước khi** nạp vào kho | Nạp dữ liệu thô vào kho **trước**, biến đổi **sau**, bên trong kho |
| Nơi chạy transform | Một tầng xử lý riêng (thường là code ứng dụng) | Ngay trong data warehouse, bằng SQL (ở đây là dbt) |
| Ưu điểm | Kho chỉ chứa dữ liệu "sạch" | Giữ được bản gốc để audit lại; tận dụng sức mạnh SQL của warehouse; dễ sửa logic mà không cần kéo lại dữ liệu |
| Nhược điểm | Mất bản gốc; sửa logic phải kéo lại từ nguồn | Kho phình to hơn (chứa cả raw) |

Dự án này chọn **ELT**, thể hiện rõ trong quy tắc bất biến ở `CLAUDE.md`:

> **Python does EL only** — pull, land, log. It never applies business logic.
> **dbt owns every transform** — typing, FX conversion, PII hashing, joins, cost allocation, profit, tests, docs.

Lý do chọn ELT cho dự án này:

1. **Payload API thay đổi liên tục và khó đoán trước.** WooCommerce trả về `line_items`, `meta_data` với cấu trúc có thể thay đổi theo plugin cài thêm. Nếu transform ngay lúc extract (ETL), mỗi lần payload đổi phải sửa code Python và **kéo lại dữ liệu** để áp dụng logic mới. Với ELT, `_payload` JSONB gốc vẫn còn nguyên trong `raw` — chỉ cần sửa SQL trong `stg_woo_orders.sql` và chạy lại `dbt build`, không cần gọi lại API.
2. **dbt cho version control, test, và docs tự động cho toàn bộ logic biến đổi** — thứ Python thuần không có sẵn. Đưa toàn bộ business logic vào dbt nghĩa là các quy tắc bất biến (ví dụ công thức lợi nhuận ở chương 06) được kiểm chứng bằng dbt test mỗi lần build, không phải nhớ áp dụng thủ công trong nhiều script Python rải rác.
3. **Audit & khả năng truy vết (traceability).** Vì `raw` giữ nguyên `_payload` gốc, bất kỳ lúc nào cũng có thể so sánh số liệu ở mart với payload gốc để tìm lỗi — quan trọng với dữ liệu tài chính (COGS, doanh thu).
4. **Tách trách nhiệm rõ ràng (separation of concerns).** Một lỗi trong logic tính lợi nhuận không bao giờ là lỗi của script Python — nó luôn nằm trong dbt. Điều này giúp debug nhanh hơn: biết ngay phải mở file nào.

## 3. Mô hình phân lớp: raw / staging / marts

Đây là mô hình tương tự khái niệm phổ biến trong ngành **"medallion architecture"** (bronze/silver/gold), chỉ khác tên gọi:

| Lớp (schema) | Tương đương medallion | Ai sở hữu | Vai trò |
|---|---|---|---|
| `raw` | Bronze | Python ELT | Bản sao chính xác từ nguồn, **append-only**, kèm `extracted_at` và `_payload` JSON gốc |
| `staging` | Silver | dbt | Đã làm sạch, ép kiểu, khử trùng lặp, băm PII |
| `marts_core` | Gold | dbt | `dim_*` + fact đơn hàng/sản phẩm/khách hàng + các mart lợi nhuận |
| `marts_marketing` | Gold | dbt | Fact GA4 và (tùy chọn) fact quảng cáo |
| `marts_operations` | Gold | dbt | `fact_order_cost`, `fact_fulfillment`, nhà cung cấp |
| `marts_recon` | Gold (đặc thù) | dbt | Đối chiếu chéo giữa các nguồn (reconciliation) |

Giải thích vai trò từng lớp:

### `raw` — lớp thô, không đụng vào logic

Quy tắc đặt tên: `raw.<nguồn>_<thực thể>` — ví dụ `raw.woo_orders`, `raw.ga4_events`, `raw.csv_order_management`. Đặc điểm:

- **Append-only**: không sửa/xóa dữ liệu cũ, chỉ thêm dòng mới hoặc upsert theo khóa tự nhiên.
- Mỗi dòng đều có `site_code`, `extracted_at`, và cột `_payload` kiểu JSONB chứa **toàn bộ response gốc** — đây là "lưới an toàn" (safety net): dù staging hôm nay chỉ lấy 5 trường, sau này cần trường thứ 6 thì trường đó **đã nằm sẵn** trong `_payload`, chỉ cần sửa SQL staging, không cần gọi lại API.
- PII (thông tin định danh cá nhân) đã được cắt bỏ **ngay tại bước nạp** nếu không cần thiết (ví dụ cột `Name`, `Email`, `Phone` trong CSV bị loại trước khi vào `raw.csv_order_management` — xem chương 03), nhưng những gì còn lại trong raw (như email Woo) vẫn ở dạng **chưa băm (unhashed)** — việc băm là việc của staging.

### `staging` — lớp làm sạch và chuẩn hóa

Quy tắc đặt tên: `staging.stg_<nguồn>_<thực thể>` — ví dụ `stg_woo_orders`, `stg_manual_order_cost_enrichment`. Công việc của lớp này (chi tiết ở chương 05):

- Ép kiểu dữ liệu (typing) — ví dụ chuỗi số từ JSON thành `NUMERIC` thật.
- Giữ tiền ở **đơn vị gốc** (`*_src`) cùng cột `currency` để lớp `fact` quy đổi FX sang USD sau — staging **không** tự quy đổi (xem chương 05).
- **Băm PII** — email được băm bằng `SHA-256(lower(trim(email)) || PII_SALT)` qua macro `hash_pii.sql`; đây là ranh giới bắt buộc: PII **không bao giờ** được phép đi qua biên `raw → staging` ở dạng chưa băm.
- Khử trùng lặp (dedupe).
- Áp dụng các quyết định đã "khóa" từ audit payload (Phase 1) — ví dụ cách parse biến thể sản phẩm (variant), cách parse phí thanh toán.

### `marts_*` — lớp tổng hợp phục vụ phân tích

Đây là nơi **logic nghiệp vụ thật sự** sống: join nhiều bảng staging lại, tính lợi nhuận, phân bổ chi phí, tạo các bảng `dim_*`/`fact_*` theo mô hình star schema (xem chương 04). Việc tách thành 4 schema con (`marts_core`, `marts_marketing`, `marts_operations`, `marts_recon`) thay vì gộp chung một `marts`, giúp:

- Người đọc biết ngay một bảng phục vụ mục đích gì (bán hàng lõi? marketing? vận hành? đối chiếu?) chỉ từ tên schema.
- Phân quyền truy cập dễ hơn nếu sau này có nhiều người dùng khác nhau truy cập kho (ví dụ team vận hành chỉ cần `marts_operations`).
- `marts_recon` tách riêng vì bản chất khác hẳn — nó không phục vụ dashboard chính, mà để **giám sát độ lệch** giữa các nguồn (ví dụ CSV vs dbt, GA4 vs Woo) — xem chương 08.

## 4. Vai trò từng công cụ trong stack (tổng hợp lại)

| Công cụ | Vai trò trong luồng dữ liệu |
|---|---|
| **Python 3.11** | Extract (gọi API/đọc CSV) + Load (ghi vào `raw`, upsert theo khóa tự nhiên, quản lý watermark tăng dần). Không viết công thức lợi nhuận, không join bảng nghiệp vụ. |
| **PostgreSQL 16 (Docker)** | Nơi chứa toàn bộ 6 schema (`raw`, `staging`, `marts_core`, `marts_marketing`, `marts_operations`, `marts_recon`). Vừa là "nhà kho", vừa là "công trường" nơi dbt chạy transform bằng SQL. |
| **dbt-core + dbt-postgres** | Biến `raw` thành `staging` thành `marts`: viết SQL dạng model, quản lý dependency giữa các model (DAG), chạy test tự động, sinh docs/lineage graph. |
| **BigQuery (GA4 export)** | Nguồn dữ liệu hành vi web, được Python đọc bằng đầu vào riêng (`ga4_bigquery.py`, Phase 6) rồi nạp vào `raw.ga4_*`. |
| **Power BI Desktop** | Lớp trên cùng — kết nối vào các bảng `marts_*` (không kết nối trực tiếp vào `raw` hay `staging`), dựng model quan hệ và DAX (xem chương 09). |

Một nguyên tắc xuyên suốt cần nhớ: **mỗi công cụ chỉ làm đúng một việc, và ranh giới giữa các việc là cứng** — Python không bao gigiờ tính toán nghiệp vụ; dbt không bao giờ tự đi gọi API; Power BI không bao giờ chứa logic tính lợi nhuận (logic đó nằm trong marts, Power BI chỉ hiển thị). Ranh giới rõ ràng này là điều giúp một dự án BI/DA solo vẫn giữ được kỷ luật kỹ thuật như một team lớn.

## Khái niệm áp dụng được

- **Tách "kéo dữ liệu" (EL) khỏi "biến đổi dữ liệu" (T)** là nguyên tắc có thể áp dụng cho bất kỳ dự án dữ liệu nào — nó cho phép sửa logic nghiệp vụ mà không cần gọi lại API nguồn.
- Chọn **ELT thay vì ETL** khi: nguồn dữ liệu có cấu trúc hay đổi, cần khả năng audit/truy vết bản gốc, và công cụ transform (như dbt) mạnh hơn code thuần.
- Luôn giữ lại **payload gốc** (JSON/JSONB) ở lớp raw như một "lưới an toàn" — tránh phải kéo lại dữ liệu khi cần thêm trường mới.
- Đặt **ranh giới bắt buộc cho PII** ngay tại điểm chuyển giao giữa các lớp (raw → staging), không để tùy nghi từng model.
- Chia lớp `marts` theo **miền nghiệp vụ** (core/marketing/operations/recon) thay vì gộp chung, để tên schema tự nói lên mục đích sử dụng.
