# 07b — Từ điển dữ liệu: schema `marts_core`

> Phần 2/3 của chương 07 (Từ điển dữ liệu). Tài liệu tra cứu — dùng Ctrl+F.
> Phần trước: [07a — raw & staging](07a-schema-raw-staging.md).
> Phần sau: [07c — marts_operations & marts_recon](07c-schema-marts-ops-recon.md).

`marts_core` là lớp mô hình Kimball chính thức: dimension (`dim_*`), fact (`fact_*`), và mart tổng hợp lợi nhuận (`mart_*`). Tất cả materialize dạng **table**. Xem quy ước ký hiệu (PK/FK/`*_sk`/`*_src`/`*_usd`) ở đầu [07a](07a-schema-raw-staging.md).

---

## Dimension (`dim_*`)

### `dim_country`
**Mục đích:** Danh mục quốc gia billing, làm giàu tên/khu vực/tiền tệ từ seed `country_iso_map`.
**Grain:** 1 dòng = 1 mã quốc gia (ISO alpha-2) xuất hiện trong đơn hàng, cộng 1 dòng tổng hợp `'XX'` cho đơn không có quốc gia billing.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `country_sk` | text | **PK** — surrogate key trên `country_code` | unique + not_null |
| `country_code` | text | Mã ISO alpha-2 (hoặc `'XX'` nếu thiếu) | unique + not_null |
| `country_name` | text | Tên quốc gia | `'Unknown'` nếu code không có trong seed và = `'XX'`, ngược lại giữ nguyên code |
| `region` | text | Khu vực địa lý | `'Unknown'` nếu seed không có |
| `currency` | text | Tiền tệ chính của quốc gia (viết hoa) | Từ seed |

### `dim_customer_anonymized`
**Mục đích:** Danh mục khách hàng ẩn danh — KHÔNG chứa PII dạng plaintext, KHÔNG chứa hành vi tổng hợp (hành vi nằm ở `mart_customer_summary`).
**Grain:** 1 dòng = 1 `customer_hash` duy nhất.
**Nguồn:** dựng từ email billing trong `stg_woo_orders` (vì `raw.woo_customers` rỗng — guest checkout).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `customer_sk` | text | **PK** — surrogate key trên `customer_hash` | unique + not_null |
| `customer_hash` | text | `SHA-256(email\|\|salt)`, hoặc `'unknown:<site>:<order_id>'` nếu không có email | unique + not_null |
| `is_unknown_email` | boolean | true nếu KHÔNG có đơn nào của khách này có email | `bool_and` trên tất cả đơn |
| `country_sk` | text | **FK → `dim_country`** — quốc gia billing tại **đơn hàng ĐẦU TIÊN** | |
| `first_order_date` | date | Ngày đơn hàng đầu tiên | |
| `last_order_date` | date | Ngày đơn hàng gần nhất | |

### `dim_date`
**Mục đích:** Bảng lịch chuẩn, 2020-01-01 → 2030-12-31, sinh bằng `dbt_utils.date_spine`.
**Grain:** 1 dòng = 1 ngày.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `date_sk` | integer | **PK** — dạng `YYYYMMDD` (vd. 20260716) | unique + not_null; đây là smart key mọi fact dùng để join |
| `date_day` | date | Ngày dạng date | unique + not_null |
| `year` / `quarter` / `month` | integer | Năm/quý/tháng | |
| `month_name` | text | Tên tháng viết tắt (`Jan`, `Feb`…) | |
| `day_of_month` | integer | Ngày trong tháng | |
| `iso_day_of_week` | integer | Thứ trong tuần theo ISO (1=Thứ Hai…7=Chủ Nhật) | |
| `day_name` | text | Tên thứ viết tắt (`Mon`, `Tue`…) | |
| `is_weekend` | boolean | true nếu Thứ Bảy/Chủ Nhật | |

### `dim_payment_method`
**Mục đích:** Danh mục phương thức thanh toán (Stripe, PayPal…).
**Grain:** 1 dòng = 1 mã phương thức thanh toán duy nhất, cộng 1 dòng `'unknown'` cho đơn thiếu phương thức.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `payment_method_sk` | text | **PK** — surrogate key trên `method_code` | unique + not_null |
| `method_code` | text | Mã phương thức (vd. `stripe`, `paypal`) | unique + not_null; `'unknown'` nếu rỗng |
| `method_name` | text | Tên hiển thị | fallback = `method_code` nếu không có tên |

### `dim_product`
**Mục đích:** Danh mục sản phẩm (catalog master) ở grain `(site_code, woo_product_id)`.
**Grain:** 1 dòng = 1 sản phẩm trong catalog Woo, cộng các dòng tổng hợp cho `product_id` đã bán nhưng không còn trong catalog (bị xóa/placeholder).

> **Quyết định thiết kế quan trọng (khác với `DATA_MODEL.md §5.3`):** toàn bộ sản phẩm là `type=simple`; size/color/style/fit/print **KHÔNG PHẢI** thuộc tính catalog mà được tổng hợp **tại thời điểm bán** (order-item-time) qua plugin WCPA. Do đó các thuộc tính biến thể này **KHÔNG nằm ở `dim_product`** mà nằm ở `fact_order_item`. Đưa chúng vào product master sẽ sai (1 sản phẩm bán ở nhiều size/color) và làm phình bảng master 58k dòng.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `product_sk` | text | **PK** — surrogate key trên (site_code, woo_product_id) | unique + not_null |
| `site_sk` | text | **FK → `dim_site`** | not_null |
| `site_code` | text | Mã cửa hàng | |
| `woo_product_id` | bigint | ID sản phẩm Woo | |
| `product_name` | text | Tên sản phẩm | `'(unknown product)'` nếu chỉ biết qua line item, không có trong catalog |
| `product_url` | text | URL sản phẩm | NULL cho sản phẩm tổng hợp |
| `product_type` | text | Loại sản phẩm | `'unknown'` cho sản phẩm tổng hợp |
| `sku` | text | SKU | |
| `first_seen_date` | date | Ngày sản phẩm xuất hiện lần đầu | NULL cho sản phẩm tổng hợp |
| `last_seen_date` | date | Ngày sửa đổi gần nhất | NULL cho sản phẩm tổng hợp |

### `dim_site`
**Mục đích:** Danh mục cửa hàng (multi-site), mirror `config/sites.yaml` qua seed `dim_site_seed`.
**Grain:** 1 dòng = 1 cửa hàng.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_sk` | text | **PK** — surrogate key trên `site_code` | unique + not_null |
| `site_code` | text | Mã cửa hàng (vd. `FOS`) | unique + not_null |
| `site_name` | text | Tên cửa hàng | |
| `domain` | text | Tên miền | |
| `default_currency` | text | Tiền tệ mặc định (viết hoa) | |
| `timezone` | text | Múi giờ vận hành | |
| `reporting_timezone` | text | Múi giờ dùng khi báo cáo | |
| `is_active` | boolean | Cửa hàng có đang hoạt động | |

---

## Fact (`fact_*`)

### `fact_order`
**Mục đích:** Fact header đơn hàng — thông tin cấp đơn hàng, tiền đã quy đổi USD.
**Grain:** 1 dòng = 1 đơn hàng Woo.
**BẤT BIẾN:** bảng này **KHÔNG có cột `revenue_usd`** — doanh thu chỉ sống ở `fact_order_item.line_revenue_usd` (tránh đếm trùng khi join order × item).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_sk` | text | **PK** — surrogate key trên (site_code, woo_order_id) | unique + not_null |
| `site_sk` | text | **FK → `dim_site`** | not_null |
| `date_sk` | integer | **FK → `dim_date`** (ngày tạo đơn) | not_null |
| `customer_sk` | text | **FK → `dim_customer_anonymized`** | not_null |
| `country_sk` | text | **FK → `dim_country`** | not_null |
| `payment_method_sk` | text | **FK → `dim_payment_method`** | not_null |
| `order_natural_key` | text | `site_code-woo_order_id` | unique + not_null |
| `woo_order_id` | bigint | ID đơn hàng Woo | |
| `status` | text | Trạng thái đơn | accepted_values: completed/processing/cancelled/failed/refunded/pending |
| `status_is_cancelled` | boolean | true nếu cancelled/failed | |
| `currency_source` | text | Tiền tệ gốc | not_null; accepted_values USD/EUR/GBP/CAD |
| `fx_rate_to_usd` | numeric | Tỷ giá áp dụng (ECB, theo ngày đơn hàng) | not_null; fallback 1.0 nếu thiếu tỷ giá |
| `order_total_src` / `order_total_usd` | numeric | Tổng đơn hàng, gốc/USD | `order_total_usd` not_null |
| `shipping_charged_src` / `shipping_charged_usd` | numeric | **Phí ship tính cho KHÁCH HÀNG**, gốc/USD | KHÔNG PHẢI chi phí supplier — chỉ là doanh thu ship |
| `discount_src` / `discount_usd` | numeric | Giảm giá, gốc/USD | |
| `tax_src` / `tax_usd` | numeric | Thuế, gốc/USD | |
| `payment_fee_usd` | numeric | Phí xử lý thanh toán (Stripe/PayPal), đã USD | Ưu tiên `plugin_parser` (order meta) → `seed_estimate` → NULL |
| `payment_fee_source` | text | Nguồn của `payment_fee_usd` | not_null; accepted_values: `api_exact`, `plugin_parser`, `seed_estimate`, `missing` |
| `payment_fee_needs_review` | boolean | true nếu không có plugin fee VÀ không có seed estimate | Đơn hàng "còn thiếu phí thanh toán" |
| `order_count` | integer | Luôn = 1 | Cột tiện dụng để SUM ra tổng số đơn hàng |

### `fact_order_item`
**Mục đích:** Fact line-item — **NƠI DUY NHẤT doanh thu tồn tại**.
**Grain:** 1 dòng = 1 line item của đơn hàng.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_item_sk` | text | **PK** — surrogate key trên (site_code, woo_order_id, woo_order_item_id) | unique + not_null |
| `order_sk` | text | **FK → `fact_order`** | not_null |
| `site_sk` | text | **FK → `dim_site`** | not_null |
| `date_sk` | integer | **FK → `dim_date`** (ngày đơn hàng cha) | not_null |
| `product_sk` | text | **FK → `dim_product`** | not_null |
| `woo_line_item_id` | bigint | ID line item Woo | |
| `woo_product_id` | bigint | ID sản phẩm Woo | |
| `quantity` | integer | Số lượng | not_null; > 0 |
| `unit_price_src` | numeric | Đơn giá (đơn vị gốc) | |
| `line_subtotal_src` | numeric | Tổng phụ dòng (đơn vị gốc) | |
| `line_total_src` | numeric | Tổng dòng thực tế (đơn vị gốc) | |
| `fx_rate_to_usd` | numeric | Tỷ giá áp dụng (theo ngày đơn hàng) | not_null |
| `line_revenue_usd` | numeric | **DOANH THU CHÍNH THỨC — `line_total_src * fx_rate_to_usd`** | not_null; >= 0; **BẤT BIẾN #1 của dự án** |
| `order_status` | text | Trạng thái đơn hàng cha (copy) | not_null; accepted_values |
| `is_revenue_status` | boolean | true nếu `order_status` in (completed, processing, refunded) | not_null; **PHẢI filter cột này khi rollup doanh thu chính thức** — `line_revenue_usd` KHÔNG bị zero-hóa cho đơn failed/cancelled/pending |
| `size` / `color` / `style` / `fit_type` / `print_location` | text | Thuộc tính biến thể tại thời điểm bán | Sống ở đây (không phải `dim_product`) theo quyết định grain nói trên |

### `fact_refund`
**Mục đích:** Fact hoàn tiền, **grain đơn hàng** (`order_item_sk` luôn NULL vì Woo không trả line_items cho refund).
**Grain:** 1 dòng = 1 refund.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `refund_sk` | text | **PK** — surrogate key trên (site_code, woo_refund_id) | unique + not_null |
| `order_sk` | text | **FK → `fact_order`** | not_null |
| `site_sk` | text | **FK → `dim_site`** | |
| `order_item_sk` | text | Luôn NULL | grain đơn hàng, không phải sản phẩm |
| `date_sk` | integer | **FK → `dim_date`** (ngày **REFUND**, không phải ngày đơn hàng) | not_null; "book on refund date" |
| `woo_refund_id` | bigint | ID refund Woo | |
| `refund_amount_usd` | numeric | Số tiền hoàn, đã USD (luôn dương) | not_null; >= 0; FX theo tỷ giá của NGÀY REFUND |
| `refund_reason` | text | Lý do hoàn tiền | |
| `event_type` | text | Loại sự kiện | not_null; accepted_values: `refund`, `cancellation` (= cancellation nếu đơn cha là cancelled/failed) |

---

## Mart tổng hợp lợi nhuận (`mart_*`)

### `mart_order_profit`
**Mục đích:** **Lợi nhuận đóng góp (contribution profit) cấp đơn hàng** — mart trung tâm của Phase 3.
**Grain:** 1 đơn hàng Woo có cost enrichment (INNER JOIN `fact_order_cost`) **và** có gross revenue > 0 (là đơn revenue-bearing).

**Công thức (LOCKED — không được đổi nếu không đồng bộ với `docs/DATA_MODEL.md §4.1/§4.2`):**
```
effective_refund_usd    = LEAST(refunds_usd, gross_revenue_usd)
net_revenue_usd          = gross_revenue_usd − effective_refund_usd
revenue_usd               = net_revenue_usd                              -- alias
contribution_profit_usd  = net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
```
Không có bước trừ shipping riêng — **phí ship supplier đã nằm sẵn trong `cogs_usd`**.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_sk` | text | **PK, FK → `fact_order`** | unique + not_null |
| `site_sk` | text | Cửa hàng | |
| `date_sk` | integer | Ngày đơn hàng | |
| `gross_revenue_usd` | numeric | `SUM(line_revenue_usd)` filter `is_revenue_status`, TRƯỚC refund | not_null |
| `refunds_usd` | numeric | `SUM(fact_refund.refund_amount_usd)` — số tiền THẬT SỰ đã hoàn (bao gồm cả phần ship) | not_null; 0 nếu không có refund |
| `effective_refund_usd` | numeric | `LEAST(refunds_usd, gross_revenue_usd)` — phần refund áp vào doanh thu sản phẩm (chặn trần ở gross để net không âm) | not_null |
| `net_revenue_usd` | numeric | `gross_revenue_usd − effective_refund_usd`, floor tại 0 | not_null |
| `revenue_usd` | numeric | Alias của `net_revenue_usd` | not_null; downstream đọc cột này = NET |
| `cogs_usd` | numeric | Giá vốn hàng bán (từ `fact_order_cost`) | |
| `design_fee_usd` | numeric | Phí thiết kế | |
| `payment_fee_usd` | numeric | Phí thanh toán — Woo ưu tiên, fallback CSV `Fee` nếu Woo NULL | |
| `contribution_profit_usd` | numeric | Công thức LOCKED ở trên | |
| `profit_margin` | numeric | `contribution_profit_usd / net_revenue_usd` | NULL khi đơn refund toàn bộ (net_revenue_usd = 0) |
| `cost_confidence` | numeric | Độ tin cậy chi phí (0–1) | từ `fact_order_cost`, thường 1.00 (order_only) |
| `cost_allocation_method` | text | Phương pháp phân bổ chi phí | accepted_values: line_exact, allocated_by_revenue_share, allocated_by_quantity_share, order_only |
| `payment_fee_source` | text | Nguồn phí thanh toán (theo phân loại của Woo, không phải theo profit) | accepted_values: api_exact, plugin_parser, seed_estimate, missing |

### `mart_product_profit`
**Mục đích:** Lợi nhuận **grain line-item**, với chi phí được phân bổ (allocate) xuống từ order-level theo tỷ lệ doanh thu.
**Grain:** 1 dòng = 1 line item, giới hạn trong các đơn hàng có trong `mart_order_profit`.

Công thức phân bổ mọi thành phần chi phí (cogs/design_fee/payment_fee/effective_refund) theo **cùng một revenue share**:
```
revenue_share       = line_revenue_usd / order_revenue_usd   (tổng tất cả line của đơn hàng)
line_<term>_usd     = order.<term>_usd * revenue_share
```
`SUM(line_profit_usd)` trên toàn bộ line của 1 đơn hàng **cộng dồn khớp chính xác** với `mart_order_profit.contribution_profit_usd`.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `order_item_sk` | text | **PK, FK → `fact_order_item`** | unique + not_null |
| `order_sk` | text | **FK → `fact_order`** | not_null |
| `site_sk` / `date_sk` / `product_sk` | text/integer/text | Copy từ `fact_order_item` | |
| `woo_line_item_id` / `woo_product_id` | bigint | ID Woo | |
| `quantity` | integer | Số lượng | |
| `line_revenue_usd` | numeric | Doanh thu dòng (trước refund) | |
| `line_refund_usd` | numeric | `effective_refund_usd * revenue_share` | phần refund phân bổ cho dòng này |
| `line_net_revenue_usd` | numeric | `line_revenue_usd − line_refund_usd` | |
| `line_cogs_usd` | numeric | COGS phân bổ cho dòng | |
| `line_design_fee_usd` | numeric | Phí thiết kế phân bổ | |
| `line_payment_fee_usd` | numeric | Phí thanh toán phân bổ | |
| `line_profit_usd` | numeric | `line_net_revenue_usd − line_cogs_usd − line_design_fee_usd − line_payment_fee_usd` | |
| `cost_allocation_method` | text | Luôn `'allocated_by_revenue_share'` | |
| `cost_confidence` | numeric | Luôn `0.60` | Thấp hơn order-level (1.00) vì đây là ước lượng phân bổ, không phải số thật |
| `is_revenue_status` | boolean | Copy từ `fact_order_item` | |

### `mart_country_profit`
**Mục đích:** Roll-up lợi nhuận theo **quốc gia × ngày**.
**Grain:** 1 dòng = 1 (`country_sk`, `date_sk`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `country_profit_sk` | text | **PK** — surrogate key trên (country_sk, date_sk) | unique + not_null |
| `country_sk` | text | **FK → `dim_country`** | not_null |
| `date_sk` | integer | **FK → `dim_date`** | |
| `order_count` | bigint | Số đơn hàng | |
| `revenue_usd` | numeric | `SUM(mart_order_profit.revenue_usd)` — đã NET refund | |
| `cogs_usd` / `design_fee_usd` / `payment_fee_usd` | numeric | Tổng chi phí tương ứng | |
| `contribution_profit_usd` | numeric | `SUM(mart_order_profit.contribution_profit_usd)` | |

### `mart_customer_summary`
**Mục đích:** Tóm tắt hành vi mua hàng theo từng khách hàng.
**Grain:** 1 dòng = 1 `customer_hash`.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `customer_sk` | text | **PK** — surrogate key trên `customer_hash` | unique + not_null |
| `customer_hash` | text | Khóa khách hàng | unique + not_null |
| `first_order_date` / `last_order_date` | date | Ngày đơn đầu/cuối | |
| `total_orders` | bigint | Tổng số đơn hàng (distinct order_sk) | not_null |
| `total_revenue_usd` | numeric | Tổng doanh thu, NET refund, floor 0 mỗi đơn | not_null |
| `total_profit_usd` | numeric | Tổng contribution profit trên các đơn có cost enrichment | NULL nếu khách chưa có đơn nào được enrich chi phí (Phase 3) |
| `is_repeat` | boolean | true nếu `total_orders > 1` | |
| `preferred_site_sk` | text | **FK → `dim_site`** — site xuất hiện nhiều nhất (mode) | |
| `preferred_country_sk` | text | **FK → `dim_country`** — quốc gia xuất hiện nhiều nhất (mode) | |

---

*Tiếp theo: [07c — Từ điển dữ liệu: `marts_operations` & `marts_recon`](07c-schema-marts-ops-recon.md)*
