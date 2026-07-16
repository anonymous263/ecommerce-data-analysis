# 07c — Từ điển dữ liệu: schema `marts_operations` và `marts_recon`

> Phần 3/3 của chương 07 (Từ điển dữ liệu). Tài liệu tra cứu — dùng Ctrl+F.
> Phần trước: [07a — raw & staging](07a-schema-raw-staging.md), [07b — marts_core](07b-schema-marts-core.md).

Xem quy ước ký hiệu (PK/FK/`*_sk`/`*_src`/`*_usd`) ở đầu [07a](07a-schema-raw-staging.md).

---

## Schema `marts_operations`

### `fact_order_cost`
**Mục đích:** Fact chi phí cấp đơn hàng (Phase 3) — quy đổi số liệu từ sheet thủ công sang USD, chuẩn bị cho `mart_order_profit`.
**Grain:** 1 dòng = 1 đơn hàng Woo (nguồn: `stg_manual_order_cost_enrichment`, INNER JOIN với `stg_woo_orders` để đảm bảo mọi dòng khớp 1 đơn hàng thật — dòng sheet không khớp bị loại và có thể xem ở `recon_unmatched_csv_cost`).
**BẤT BIẾN:** không có cột "chi phí ship supplier" riêng — khái niệm này không tồn tại trong dữ liệu; `csv_shipping_charged_usd` là phí ship tính cho KHÁCH, không phải cost.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_cost_sk` | text | **PK** — surrogate key trên (site_code, woo_order_id) | unique + not_null |
| `order_sk` | text | **FK → `fact_order`** | not_null |
| `site_sk` | text | **FK → `dim_site`** | not_null |
| `date_sk` | integer | **FK → `dim_date`** | not_null |
| `cogs_usd` | numeric | Giá vốn hàng bán, đã USD (đã bao gồm phí fulfillment/ship supplier) | |
| `design_fee_usd` | numeric | Phí thiết kế, đã USD | |
| `payment_fee_fallback_usd` | numeric | Phí thanh toán theo sheet (`fee_src`), FX sang USD | Dùng làm fallback khi Woo không có `payment_fee_usd` |
| `csv_shipping_charged_usd` | numeric | Phí ship tính cho KHÁCH theo sheet, đã USD | Chỉ để recon với Woo |
| `csv_revenue_observed_usd` | numeric | Revenue quan sát trên sheet, đã USD | **Chỉ recon** — không bao giờ là metric chính thức |
| `csv_profit_observed_usd` | numeric | Profit quan sát trên sheet, đã USD | **Chỉ recon** |
| `cost_source` | text | Nguồn chi phí | not_null; accepted_values: manual_csv, supplier_api |
| `cost_allocation_method` | text | Phương pháp phân bổ (ở mức đơn hàng: `order_only`) | not_null; accepted_values: line_exact, allocated_by_revenue_share, allocated_by_quantity_share, order_only |
| `cost_confidence` | numeric | Độ tin cậy (0–1) | between 0 and 1; thường 1.00 |

---

## Schema `marts_recon` (reconciliation — đối chiếu & giám sát chất lượng, tất cả là **view**)

Các view này **không phải metric chính thức** — chúng tồn tại để phát hiện lệch (drift) giữa các nguồn và đo độ phủ dữ liệu, phục vụ cơ chế gating của dashboard (xem `docs/METRICS_DEFINITION.md §J`, `docs/DASHBOARD_SPEC.md §K`).

### `recon_cost_coverage`
**Mục đích:** Đo **độ phủ chi phí (cost coverage)** — tỷ lệ đơn hàng có COGS thật, dùng để gate hiển thị lợi nhuận trên dashboard.
**Grain:** 1 dòng mỗi `site_sk`, cộng 1 dòng tổng `'__ALL__'`.

**Nguyên tắc quan trọng:** tỷ lệ gating (`cost_coverage_pct`) tính trên **đơn hàng revenue-generating** (`revenue_orders`), KHÔNG tính trên toàn bộ đơn hàng — đơn failed/cancelled/pending không bao giờ có chi phí và không được kéo tỷ lệ xuống. "Covered" đòi hỏi `cogs_usd > 0` thật sự, không chỉ có dòng `fact_order_cost` tồn tại (dòng sheet với `cogs_usd` = 0/null nghĩa là "chưa biết chi phí", không phải "đã có chi phí").

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_sk` | text | Cửa hàng, hoặc `'__ALL__'` cho tổng hợp | |
| `woo_orders` | numeric | Tổng số đơn hàng Woo | |
| `revenue_orders` | numeric | Số đơn hàng revenue-generating (có ≥1 line `is_revenue_status`) | |
| `covered_orders` | numeric | Số đơn có dòng `fact_order_cost` (bất kể cogs > 0 hay không) | |
| `covered_revenue_orders` | numeric | Số đơn revenue-generating có dòng `fact_order_cost` | |
| `covered_revenue_orders_with_cogs` | numeric | Số đơn revenue-generating có `cogs_usd > 0` thật | Tử số của metric gating |
| `all_order_coverage_pct` | numeric | `covered_orders / woo_orders` | Chỉ mang tính thông tin, KHÔNG dùng để gate |
| `cost_coverage_pct` | numeric | **`covered_revenue_orders_with_cogs / revenue_orders`** | **Metric gating chính thức** |
| `cogs_coverage_pct` | numeric | Giống hệt `cost_coverage_pct` | Giữ tên riêng theo `METRICS_DEFINITION.md §J` |
| `coverage_tier` | text | `'green'` (≥95%), `'yellow'` (80–95%), `'red'` (<80%) | Quyết định dashboard ẩn/hiện lợi nhuận |

### `recon_payment_fee_coverage`
**Mục đích:** Đo độ phủ phí thanh toán chính xác (không phải ước lượng) từ Woo.
**Grain:** 1 dòng mỗi `payment_fee_source`, cộng 1 dòng tổng `'__ALL__'`.

Cùng nguyên tắc với `recon_cost_coverage`: gate trên đơn revenue-generating, không phải toàn bộ đơn — đơn chưa từng thanh toán (failed/cancelled/pending) không bao giờ có phí gateway, tính chúng vào "chưa phủ" sẽ làm sai lệch tỷ lệ (all-orders 79.50% vs revenue-orders 98.03% trong thực tế).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `payment_fee_source` | text | Nguồn phí (`api_exact`/`plugin_parser`/`seed_estimate`/`missing`), hoặc `'__ALL__'` | |
| `order_count` | bigint | Tổng số đơn trong nhóm | |
| `orders_with_fee` | bigint | Số đơn có `payment_fee_usd` không NULL | |
| `revenue_orders` | bigint | Số đơn revenue-generating trong nhóm | |
| `revenue_orders_with_fee` | bigint | Số đơn revenue-generating có phí | Tử số của metric gating |
| `all_order_coverage_pct` | numeric | `orders_with_fee / order_count` | Chỉ thông tin |
| `fee_coverage_pct` | numeric | **`revenue_orders_with_fee / revenue_orders`** | **Metric gating chính thức** — <80% bật chip "estimated payment fee" |

### `recon_csv_vs_dbt_profit`
**Mục đích:** Giám sát lệch giữa Profit quan sát trên sheet (CSV) và Profit chính thức của dbt — CSV Profit **KHÔNG BAO GIỜ** là metric chính thức.
**Grain:** 1 dòng mỗi đơn hàng có cả 2 nguồn.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_sk` | text | **FK → `fact_order`** | |
| `csv_profit_observed_usd` | numeric | Profit theo sheet (đã USD) | Từ `fact_order_cost` |
| `dbt_profit_usd` | numeric | `mart_order_profit.contribution_profit_usd` — NET refund | |
| `delta_usd` | numeric | `csv_profit_observed_usd − dbt_profit_usd` | Lệch có thể lớn với đơn đã refund vì cơ sở tính của sheet chưa chắc refund-aware — đây là dự kiến, không phải bug |
| `delta_pct` | numeric | `delta_usd / dbt_profit_usd` | NULL nếu `dbt_profit_usd = 0` |

### `recon_csv_vs_dbt_revenue`
**Mục đích:** Giám sát lệch giữa Revenue quan sát trên sheet và Revenue chính thức của dbt — CSV Revenue **KHÔNG BAO GIỜ** là metric chính thức.
**Grain:** 1 dòng mỗi đơn hàng có cả 2 nguồn.

**Điểm định nghĩa quan trọng:** Revenue của sheet là giá trị **GROSS** (≈ line revenue + phí ship khách), còn revenue chính thức của dbt là **NET line revenue** (ship sống riêng ở `fact_order.shipping_charged_usd`). Vì vậy `delta_usd` (so với NET) lệch lớn một cách có chủ đích (~bằng tiền ship); phép so sánh có ý nghĩa là `delta_vs_gross_usd` (so với dbt_revenue + shipping), lệch gần 0.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_sk` | text | **FK → `fact_order`** | |
| `csv_revenue_observed_usd` | numeric | Revenue theo sheet (GROSS, đã USD) | |
| `dbt_revenue_usd` | numeric | `SUM(fact_order_item.line_revenue_usd)` filter `is_revenue_status` (NET) | |
| `shipping_charged_usd` | numeric | Phí ship khách (từ `fact_order`) | |
| `dbt_gross_usd` | numeric | `dbt_revenue_usd + shipping_charged_usd` | So sánh tương đương với CSV |
| `delta_usd` | numeric | `csv_revenue_observed_usd − dbt_revenue_usd` | Lệch lớn theo cấu trúc (~bằng shipping) — KHÔNG phải bug |
| `delta_pct` | numeric | `delta_usd / dbt_revenue_usd` | |
| `delta_vs_gross_usd` | numeric | `csv_revenue_observed_usd − dbt_gross_usd` | **Phép so sánh ý nghĩa** — nên gần 0 |

### `recon_woo_vs_csv_shipping_charged`
**Mục đích:** Đối chiếu **phí ship tính cho KHÁCH HÀNG** — Woo (chính thức) vs CSV (sheet). Cả hai bên đều là doanh thu ship, KHÔNG PHẢI chi phí supplier.
**Grain:** 1 dòng mỗi (`site_sk`, `date_sk`).

**Nguyên tắc like-for-like:** phía Woo chỉ tính trên các đơn **cũng có** dòng chi phí CSV (JOIN với `fact_order_cost`) — nếu so toàn bộ Woo với CSV đã-covered sẽ báo "lệch" giả (do khoảng trống cost coverage, không phải lệch thật). Trên tập covered chung, lệch thật ~2% (mục tiêu ≤5%), 97% đơn khớp đến từng cent.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_sk` | text | Cửa hàng | |
| `date_sk` | integer | Ngày | |
| `woo_shipping_charged_usd` | numeric | Tổng phí ship khách theo Woo (chỉ đơn có CSV cost) | |
| `csv_shipping_charged_usd` | numeric | Tổng phí ship khách theo CSV | |
| `delta_usd` | numeric | `woo − csv` | |
| `delta_pct` | numeric | `delta_usd / woo_shipping_charged_usd` | |

### `recon_unmatched_csv_cost`
**Mục đích:** Hiển thị các dòng chi phí trên sheet FOS bị **loại âm thầm** bởi INNER JOIN của `fact_order_cost` (Order Code trên sheet không khớp đơn Woo nào — do gõ sai, đơn bị xóa, hoặc chưa được ingest). Dùng để điều tra/sửa tại nguồn (sheet).
**Grain:** 1 dòng = 1 dòng sheet không khớp, giới hạn `site_code = 'FOS'`.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Luôn `'FOS'` | |
| `order_code` | bigint | `woo_order_id` ghi trên sheet (không khớp Woo) | not_null |
| `order_date` | date | Ngày đơn theo sheet | |
| `currency` | text | Tiền tệ theo sheet | |
| `cogs_usd` | numeric | COGS ghi trên sheet | |
| `design_fee_usd` | numeric | Phí thiết kế ghi trên sheet | |
| `csv_revenue_observed_usd` | numeric | Revenue quan sát trên sheet | |

---

## Khái niệm áp dụng được

Data dictionary (từ điển dữ liệu) là tài liệu **tra cứu chuẩn hóa** — mọi thành viên (kể cả tương lai chính bạn 6 tháng sau) đều tìm được nghĩa chính xác của một cột mà không cần đọc lại toàn bộ code dbt. Vài lý do nó bắt buộc phải có trong bất kỳ dự án BI/DA nào:

1. **Chống hiểu sai metric.** Ví dụ trong dự án này: `csv_revenue_observed_usd` trông giống "revenue" nhưng KHÔNG BAO GIỜ được dùng làm doanh thu chính thức — nếu không có từ điển ghi rõ, một người viết DAX mới dễ dàng dùng nhầm cột này.
2. **Ghi lại các bất biến (invariants) tại đúng chỗ cột sống** — vd. "không có cột `revenue_usd` trên `fact_order`", "`cogs_usd` đã bao gồm phí ship supplier" — những quy tắc mà nếu quên sẽ làm sai mọi con số lợi nhuận.
3. **Tăng tốc onboarding.** Người mới (hoặc AI agent) đọc 1 bảng markdown thay vì phải grep qua hàng chục file `.sql` + `schema.yml` để hiểu 1 cột nghĩa là gì.
4. **Là hợp đồng (contract) giữa dbt và Power BI.** Khi viết DAX, luôn tra từ điển để biết cột nào là NET hay GROSS, cột nào chỉ để recon, cột nào có FK phải join — tránh double-count hoặc join sai grain.
5. **Tài liệu sống, không tĩnh.** Vì được sinh trực tiếp từ `information_schema` + `schema.yml` + comment trong `.sql`, từ điển luôn có thể refresh lại đúng với database thật — khác với tài liệu viết tay dễ lỗi thời khi model thay đổi.

Áp dụng cho dự án khác: bất kỳ kho dữ liệu nào có >10 bảng nên có từ điển dữ liệu ngay từ Phase đầu, cập nhật mỗi khi thêm/đổi model — đừng để nó trở thành việc "làm sau cùng".
