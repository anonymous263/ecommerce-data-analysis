# Tài liệu học — Dự án BI/DA (WooCommerce POD Analytics)

> Bộ tài liệu này giải thích **toàn bộ** cách xây dựng một data warehouse + hệ thống BI
> cho dữ liệu thương mại điện tử: từ nguồn dữ liệu, cách kéo (extract), làm sạch, chuẩn hóa,
> mô hình hóa, biến đổi (transform), tới trực quan hóa bằng Power BI.
>
> **Mục tiêu:** viết theo *lộ trình học*, không phải tài liệu tra cứu khô khan. Đọc xong
> bạn hiểu được cả **cái gì**, **tại sao**, và **cách làm** — để áp dụng cho dự án khác.

---

## Lộ trình học (đọc theo thứ tự)

| # | File | Nội dung | Bạn học được gì |
|---|------|----------|-----------------|
| 00 | `00-tong-quan-du-an-BI.md` | BI/DA là gì; mục tiêu, kiến trúc tổng thể, tech stack, các giai đoạn (phase) của dự án | Bức tranh lớn: một dự án BI gồm những mảnh nào |
| 01 | `01-kien-truc-va-luong-du-lieu.md` | Luồng dữ liệu Sources → Python EL → Postgres (raw) → dbt → Power BI; **ELT vs ETL** và vì sao chọn ELT; mô hình phân lớp `raw`/`staging`/`marts` | Nguyên tắc tách "kéo dữ liệu" khỏi "biến đổi dữ liệu" |
| 02 | `02-nguon-du-lieu.md` | 3 nguồn: WooCommerce API, CSV thủ công (chi phí), GA4; bảng "hệ thống nào là nguồn sự thật" (source of truth); đa cửa hàng (multi-site) | Cách xác định nguồn dữ liệu và trách nhiệm từng nguồn |
| 03 | `03-trich-xuat-va-nap-EL.md` | Extract & Load bằng Python: phân trang & watermark khi gọi Woo API; nạp CSV; thiết kế schema `raw` (append-only, `_payload` JSONB, `site_code`, `extracted_at`); xử lý PII ngay khi nạp | Cách kéo dữ liệu an toàn, có thể lặp lại, và bảo vệ dữ liệu cá nhân |
| 04 | `04-mo-hinh-hoa-kimball.md` | Mô hình hóa Kimball: **fact vs dimension**, **grain** (độ mịn), **surrogate key** (khóa thay thế), **conformed dimension**, **star schema** — khái niệm + vì sao | Nền tảng thiết kế kho dữ liệu phân tích |
| 05 | `05-staging-lam-sach-chuan-hoa.md` | Lớp `staging` trong dbt: ép kiểu (typing), chuẩn bị FX (giữ `*_src`, quy đổi ở lớp fact), **băm PII (hashing)**, khử trùng lặp (dedupe); giải thích từng model staging | Làm sạch & chuẩn hóa dữ liệu thô một cách có kỷ luật |
| 06 | `06-marts-bien-doi-tong-hop.md` | Lớp `marts`: core (đơn hàng, sản phẩm, khách hàng, hoàn tiền), profit (lợi nhuận), recon (đối chiếu); **logic nghiệp vụ**: quy tắc doanh thu, lợi nhuận đóng góp, refund netting, phân bổ chi phí; các **bất biến (invariants)** | Biến dữ liệu sạch thành số liệu kinh doanh đúng |
| 07 | `07a-schema-raw-staging.md`, `07b-schema-marts-core.md`, `07c-schema-marts-ops-recon.md` | **Từ điển dữ liệu** (tách 3 phần theo schema): mọi bảng, mọi cột — kiểu, ý nghĩa, nguồn, khóa (`raw`+`staging`, `marts_core`, `marts_operations`+`marts_recon`) | Tra cứu chính xác từng cột khi làm dashboard/DAX |
| 08 | `08-chat-luong-va-kiem-dinh.md` | Chất lượng dữ liệu: **coverage** (độ phủ chi phí, phí thanh toán), **gating theo tầng** (ẩn/hiện lợi nhuận), dbt tests, các view đối chiếu (recon) | Cách "đo" và "gác cổng" chất lượng số liệu |
| 09 | `09-truc-quan-hoa-powerbi.md` | Power BI: semantic model, quan hệ (relationship), bảng `_Measures`, **DAX**, gating lợi nhuận, các trang dashboard | Chuyển marts thành dashboard có thể tin cậy |
| 10 | `10-bai-hoc-va-ap-dung.md` | Tổng kết: các khái niệm/quy tắc **có thể tái sử dụng** cho dự án BI/DA khác | Đúc kết để áp dụng lần sau |
| 11 | `11-dax-measures-giai-thich.md` | **Từ điển measure & DAX**: giải thích từng công thức trong `dax_measures.txt` — đọc hiểu, vì sao viết vậy, viết sai hỏng ra sao; phụ lục tra cứu hàm DAX + các REVIEW còn tồn | Đọc và viết được DAX; hiểu filter context, `TREATAS`, `KEEPFILTERS`, gating |
| 12 | `12-dax-formatting-chuan-sqlbi.md` | **Format DAX chuẩn SQLBI**: 8 rules kèm lý do (space, `table[column]` vs `[measure]`, xuống dòng/thụt 4, VAR/RETURN, toán tử...), before/after từ measure thật của project, format UDF, công cụ (daxformatter, `Shift+Alt+F`) | Viết DAX đọc được như văn xuôi; review format người khác có căn cứ |

> **Từ điển dữ liệu (07)** đã được tách thành 3 file theo schema:
> `07a-schema-raw-staging.md`, `07b-schema-marts-core.md`, `07c-schema-marts-ops-recon.md`.
>
> **Hai chương tra cứu:** 07 (từng **cột**) và 11 (từng **measure**) dùng để tra khi cần,
> không cần đọc một mạch. Chương 09 dạy *khái niệm* DAX; chương 11 đi *từng công thức*.

---

## Cách dùng bộ tài liệu này để học

1. **Đọc tuần tự 00 → 10.** Mỗi chương xây trên chương trước.
2. **Vừa đọc vừa mở code/tài liệu gốc** tương ứng để đối chiếu (xem cột "Nguồn" bên dưới).
3. Ở mỗi chương có phần **"Khái niệm áp dụng được"** — ghi lại để dùng cho dự án khác.
4. Chương 07 (từ điển cột, 3 file `07a`/`07b`/`07c`) và chương 11 (từ điển measure/DAX)
   dùng để **tra cứu**, không cần đọc một mạch. Khi build Power BI, mở chương 11 cạnh
   `powerbi/measures/dax_measures.txt` và tra theo từng measure đang tạo.

## Tài liệu gốc (tiếng Anh) để đối chiếu

Bộ tài liệu học này *diễn giải lại* các tài liệu kỹ thuật gốc trong `docs/` — khi cần chi
tiết "chuẩn", xem:

- `README.md`, `CLAUDE.md` — tổng quan & quy tắc bất biến
- `docs/DATA_MODEL.md` — schema, grain, công thức lợi nhuận
- `docs/PIPELINE_DESIGN.md` — bố cục EL + dbt
- `docs/METRICS_DEFINITION.md` — định nghĩa từng chỉ số/DAX
- `docs/DASHBOARD_SPEC.md` — các trang dashboard & gating
- `docs/DATA_AUDIT.md`, `docs/WOO_PAYLOAD_AUDIT.md` — kiểm kê PII & payload

---

*Trạng thái: hoàn tất — 15 chương (00–12, với 07 tách thành 07a/07b/07c) đã viết xong,
bám sát code và schema thật của repo. Bộ tài liệu sẽ cần cập nhật khi pipeline thay đổi
(ví dụ khi triển khai Phase 5 fulfillment hoặc Phase 6 GA4).*
