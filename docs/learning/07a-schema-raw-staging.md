# 07a — Từ điển dữ liệu: schema `raw` và `staging`

> Phần 1/3 của chương 07 (Từ điển dữ liệu). Đây là tài liệu **tra cứu** — không cần đọc
> tuần tự, dùng Ctrl+F để tìm bảng/cột cần biết. Hai phần còn lại:
> [07b — marts_core](07b-schema-marts-core.md), [07c — marts_operations & marts_recon](07c-schema-marts-ops-recon.md).

**Nguồn dữ liệu lấy trực tiếp từ database thật** (không bịa):

```powershell
docker exec ecommerce_postgres psql -U ecommerce -d ecommerce -P pager=off -c "
select table_schema, table_name, column_name, data_type
from information_schema.columns
where table_schema in ('raw','staging')
order by table_schema, table_name, ordinal_position;"
```

Ý nghĩa từng cột đối chiếu từ `dbt/models/**/schema.yml`, `dbt/models/**/_sources.yml` và comment đầu mỗi file `.sql` model.

## Quy ước đọc bảng

| Ký hiệu | Ý nghĩa |
|---|---|
| **PK** | Khóa chính — giá trị (hoặc tổ hợp) là duy nhất, xác định 1 dòng |
| **FK → bảng X** | Khóa ngoại — tham chiếu đến khóa chính của bảng X |
| **`*_sk`** | Surrogate key — khóa thay thế do dbt sinh ra (`dbt_utils.generate_surrogate_key`, hash MD5 của các cột tự nhiên), dùng để join ổn định giữa fact/dimension thay vì dùng khóa nghiệp vụ |
| **`*_src`** | Số tiền còn ở **đơn vị tiền tệ gốc** (chưa quy đổi USD) |
| **`*_usd`** | Số tiền đã quy đổi sang USD |

---

## Schema `raw` (do Python EL nạp — append-only, không có business logic)

Mỗi bảng `woo_*` mang theo `site_code`, khóa tự nhiên Woo, `extracted_at`, và toàn bộ object gốc trong `_payload` (JSONB). Nguồn: `dbt/models/staging/woocommerce/_sources.yml`.

### `raw.woo_orders`
**Mục đích:** bản sao thô của mỗi đơn hàng Woo (header), lấy từ WooCommerce REST API `/orders`.
**Grain:** 1 dòng = 1 đơn hàng Woo (`site_code + woo_order_id`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng (vd. `FOS`) | not_null; PK theo tổ hợp |
| `woo_order_id` | bigint | ID đơn hàng trong Woo | not_null; PK theo tổ hợp (site_code, woo_order_id) |
| `number` | text | Số đơn hàng hiển thị cho khách | |
| `status` | text | Trạng thái đơn (completed/processing/…) | Woo API field `status`, cũng có trong `_payload` |
| `currency` | text | Mã tiền tệ đơn hàng | |
| `date_created_gmt` | timestamptz | Ngày giờ tạo đơn (GMT) | |
| `date_modified_gmt` | timestamptz | Ngày giờ sửa đổi gần nhất | dùng làm watermark khi extract lại |
| `extracted_at` | timestamptz | Thời điểm Python kéo dòng này về | |
| `_payload` | jsonb | Toàn bộ JSON object gốc từ Woo API | Chứa cả các field không có cột riêng (billing, meta_data, line_items…) — staging đọc trực tiếp từ đây |

### `raw.woo_order_items`
**Mục đích:** dòng chi tiết sản phẩm trong đơn hàng (explode từ `orders[].line_items`).
**Grain:** 1 dòng = 1 line item của 1 đơn hàng.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_order_id` | bigint | FK → `raw.woo_orders` | not_null |
| `woo_order_item_id` | bigint | ID line item trong Woo | not_null; PK theo tổ hợp (site_code, woo_order_id, woo_order_item_id) |
| `extracted_at` | timestamptz | Thời điểm kéo về | |
| `_payload` | jsonb | JSON gốc của line item (product_id, name, sku, quantity, price, subtotal, total, meta_data…) | meta_data chứa thuộc tính biến thể (size/color/style/fit/print) do plugin WCPA đóng gói |

### `raw.woo_products`
**Mục đích:** bản sao master sản phẩm Woo.
**Grain:** 1 dòng = 1 sản phẩm (`site_code + woo_product_id`). Toàn bộ 58.168 sản phẩm là `type=simple`.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_product_id` | bigint | ID sản phẩm Woo | not_null; PK theo tổ hợp |
| `date_modified_gmt` | timestamptz | Ngày sửa đổi gần nhất | |
| `extracted_at` | timestamptz | Thời điểm kéo về | |
| `_payload` | jsonb | JSON gốc (name, permalink, type, sku, status, date_created_gmt…) | |

### `raw.woo_customers`
**Mục đích:** khách hàng đăng ký tài khoản Woo. **Hiện đang RỖNG** vì cửa hàng chủ yếu bán guest-checkout (không tài khoản).
**Grain:** 1 dòng = 1 khách hàng đăng ký.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_customer_id` | bigint | ID khách hàng Woo | not_null |
| `date_modified_gmt` | timestamptz | Ngày sửa đổi | |
| `extracted_at` | timestamptz | Thời điểm kéo về | |
| `_payload` | jsonb | JSON gốc (email, billing…) | PII — bị drop/hash ngay ở staging |

### `raw.woo_refunds`
**Mục đích:** hoàn tiền Woo. **Grain đơn hàng** (không phải grain sản phẩm) — trường `line_items` luôn rỗng trong nguồn.
**Grain:** 1 dòng = 1 refund (`site_code + woo_refund_id`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_refund_id` | bigint | ID refund Woo | not_null; PK theo tổ hợp (site_code, woo_refund_id) |
| `woo_order_id` | bigint | FK → `raw.woo_orders` | not_null |
| `date_created_gmt` | timestamptz | Ngày tạo refund | |
| `extracted_at` | timestamptz | Thời điểm kéo về | |
| `_payload` | jsonb | JSON gốc (amount, reason…) | `amount` có thể là số âm tùy site — staging lấy trị tuyệt đối |

### `raw.woo_coupons`
**Mục đích:** mã giảm giá Woo.
**Grain:** 1 dòng = 1 coupon (`site_code + woo_coupon_id`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_coupon_id` | bigint | ID coupon Woo | not_null; unique + not_null |
| `date_modified_gmt` | timestamptz | Ngày sửa đổi | |
| `extracted_at` | timestamptz | Thời điểm kéo về | |
| `_payload` | jsonb | JSON gốc (code, discount_type, amount…) | |

### `raw.csv_order_management`
**Mục đích:** bản sao đã-xử-lý-PII của Google Sheet chi phí thủ công (`Order Management.csv`) — nguồn duy nhất của COGS.
**Grain:** 1 dòng = 1 đơn hàng Woo (`site_code + woo_order_id`).
**Lưu ý riêng tư:** `Name`, `Email`, `Phone`, `Ship to` bị **drop trước khi ghi vào bảng này** — đây KHÔNG phải bản copy 1:1 của sheet gốc.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_order_id` | bigint | FK → `raw.woo_orders` (khớp theo Order Code) | not_null; PK theo tổ hợp |
| `order_status` | text | Trạng thái đơn theo sheet | |
| `order_date` | date | Ngày đơn hàng | |
| `currency` | text | Tiền tệ ghi trên sheet | cột "Currency" được tin tưởng trực tiếp |
| `items_subtotal_src` | numeric | Tổng tiền sản phẩm (đơn vị gốc) | |
| `csv_shipping_charged_src` | numeric | **Phí ship tính cho KHÁCH HÀNG** (không phải chi phí supplier) | Cột `Shipping` trên sheet — chỉ dùng để đối chiếu (recon), KHÔNG PHẢI cost |
| `tips_coupon_src` | numeric | Tip/coupon (đơn vị gốc) | |
| `order_total_src` | numeric | Tổng đơn hàng theo sheet (đơn vị gốc) | |
| `fee_src` | numeric | Phí thanh toán ghi trên sheet (đơn vị gốc) | dùng làm fallback cho `payment_fee_usd` khi Woo không có |
| `payout_src` | numeric | Số tiền payout (đơn vị gốc) | |
| `cogs_usd` | numeric | **COGS — giá vốn hàng bán, đã là USD** | Nguồn sự thật duy nhất của COGS; **đã bao gồm phí ship/fulfillment của supplier** |
| `design_fee_usd` | numeric | Phí thiết kế, đã là USD | |
| `csv_revenue_observed_usd` | numeric | Revenue quan sát trên sheet (đã USD) | **KHÔNG BAO GIỜ** dùng làm metric chính thức — chỉ để đối chiếu (recon) |
| `csv_profit_observed_usd` | numeric | Profit quan sát trên sheet (đã USD) | Chỉ để đối chiếu (recon) |
| `csv_roi` | numeric | ROI theo sheet | Chỉ để đối chiếu |
| `csv_profit_margin` | numeric | Profit margin theo sheet | Chỉ để đối chiếu |
| `country` | text | Quốc gia ghi trên sheet | |
| `extracted_at` | timestamptz | Thời điểm Python nạp dòng này | |
| `_payload` | jsonb | JSON gốc còn lại sau khi đã drop PII | |

### `raw.pipeline_runs` / `raw.pipeline_state`
**Mục đích:** bảng vận hành nội bộ của pipeline (không phải dữ liệu nghiệp vụ).

| Bảng | Cột chính | Ý nghĩa |
|---|---|---|
| `pipeline_runs` | `run_id` (PK, uuid), `pipeline_name`, `site_code`, `start_ts`, `end_ts`, `status`, `rows_in`, `rows_out`, `error_text` | Log mỗi lần chạy extract/load: chạy pipeline nào, cho site nào, kết quả ra sao |
| `pipeline_state` | `site_code` + `entity` (PK tổ hợp), `watermark`, `updated_at` | Lưu watermark (mốc thời gian) để lần extract sau chỉ lấy dữ liệu mới/thay đổi |

---

## Schema `staging` (dbt — làm sạch, ép kiểu, băm PII; tất cả đều là **view**)

Nguyên tắc chung: tiền vẫn ở **đơn vị gốc** (`*_src`), PII đã bị hash hoặc drop, FX sang USD để dành cho lớp `marts`.

### `stg_woo_orders`
**Mục đích:** Header đơn hàng đã ép kiểu, PII đã hash.
**Grain:** 1 dòng = 1 đơn hàng (giống `raw.woo_orders`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_order_id` | bigint | ID đơn hàng Woo | not_null |
| `order_natural_key` | text | `site_code || '-' || woo_order_id` | **PK** — unique + not_null |
| `order_number` | text | Số đơn hàng hiển thị | |
| `status` | text | Trạng thái đơn | accepted_values: completed/processing/cancelled/failed/refunded/pending |
| `status_is_cancelled` | boolean | `status in (cancelled, failed)` | |
| `currency_source` | text | Tiền tệ gốc, viết hoa | not_null; accepted_values: USD/EUR/GBP/CAD |
| `order_created_at_utc` | timestamptz | Ngày giờ tạo đơn | = `date_created_gmt` |
| `order_date` | date | Ngày tạo đơn (date only) | dùng làm khóa ngày cho FX join |
| `payment_method` | text | Mã phương thức thanh toán | |
| `payment_method_title` | text | Tên hiển thị phương thức thanh toán | |
| `billing_country_code` | text | Mã quốc gia billing (ISO alpha-2, viết hoa) | |
| `order_total_src` | numeric | Tổng đơn hàng (đơn vị gốc) | |
| `shipping_charged_src` | numeric | **Phí ship tính cho khách** (đơn vị gốc) | Woo field `shipping_total` |
| `discount_src` | numeric | Giảm giá (đơn vị gốc) | |
| `tax_src` | numeric | Thuế (đơn vị gốc) | |
| `billing_email_hash` | text | `SHA-256(lower(trim(email)) \|\| PII_SALT)` | Macro `hash_pii.sql`; not_null |
| `is_unknown_email` | boolean | true nếu đơn không có email billing | |
| `stripe_fee_src` | numeric | Phí Stripe (đơn vị processor) | Lấy từ order meta `_cs_stripe_fee` |
| `paypal_fee_src` | numeric | Phí PayPal (đơn vị processor) | Lấy từ order meta `_cs_paypal_fee` |
| `stripe_currency` | text | Tiền tệ Stripe báo cáo | |
| `paypal_currency` | text | Tiền tệ PayPal báo cáo | |
| `plugin_payment_fee_src` | numeric | `coalesce(stripe_fee_src, paypal_fee_src)` | |
| `plugin_payment_fee_currency` | text | Tiền tệ tương ứng plugin fee | |
| `has_plugin_payment_fee` | boolean | true nếu có phí xử lý từ Stripe/PayPal | |
| `customer_hash` | text | `billing_email_hash`, hoặc `'unknown:<site>:<order_id>'` nếu không có email | Khóa liên kết khách hàng (guest checkout) |

### `stg_woo_order_items`
**Mục đích:** Line item đã ép kiểu + thuộc tính biến thể đã làm sạch (size/color/style/fit/print).
**Grain:** 1 dòng = 1 line item.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_order_id` | bigint | FK → `stg_woo_orders` | |
| `woo_order_item_id` | bigint | ID line item | not_null; unique theo tổ hợp (site_code, woo_order_id, woo_order_item_id) |
| `woo_product_id` | bigint | FK → `stg_woo_products` | |
| `product_name_at_sale` | text | Tên sản phẩm tại thời điểm bán | có thể khác tên hiện tại trong catalog |
| `sku` | text | SKU tại thời điểm bán | |
| `quantity` | integer | Số lượng | not_null; > 0 |
| `unit_price_src` | numeric | Đơn giá (đơn vị gốc) | |
| `line_subtotal_src` | numeric | Tổng phụ dòng (trước giảm giá, đơn vị gốc) | |
| `line_total_src` | numeric | **Tổng dòng thực tế (đơn vị gốc)** | Đây là gốc của `line_revenue_usd` — nơi DUY NHẤT doanh thu tồn tại |
| `size` / `color` / `style` / `fit_type` | text | Thuộc tính biến thể đã làm sạch | Từ meta_data plugin WCPA (`display_key`), lấy đoạn đầu trước dấu `\|` |
| `print_location` | text | Vị trí in đã làm sạch | Đã strip hậu tố phụ phí dạng `(£5.95)` |

### `stg_woo_products`
**Mục đích:** Master sản phẩm đã ép kiểu.
**Grain:** 1 dòng = 1 sản phẩm (`site_code + woo_product_id`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_product_id` | bigint | ID sản phẩm | not_null |
| `product_name` | text | Tên sản phẩm | |
| `product_url` | text | URL sản phẩm (permalink) | |
| `product_type` | text | Loại sản phẩm | Toàn bộ là `simple` |
| `sku` | text | SKU | |
| `product_status` | text | Trạng thái publish | |
| `first_seen_at_utc` | timestamptz | Ngày tạo sản phẩm | |
| `last_seen_at_utc` | timestamptz | Ngày sửa đổi gần nhất | |

### `stg_woo_customers`
**Mục đích:** Khách hàng đăng ký tài khoản, PII đã hash. **Hiện không dùng** để xây `dim_customer_anonymized` (vì rỗng — guest checkout thống trị); giữ lại cho tương lai.
**Grain:** 1 dòng = 1 khách hàng đăng ký.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_customer_id` | bigint | ID khách hàng | not_null |
| `customer_email_hash` | text | Email đã hash | |
| `billing_country_code` | text | Quốc gia billing | |
| `created_at_utc` | timestamptz | Ngày tạo tài khoản | |

### `stg_woo_refunds`
**Mục đích:** Refund đã ép kiểu, grain đơn hàng.
**Grain:** 1 dòng = 1 refund.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_refund_id` | bigint | ID refund | not_null; unique theo tổ hợp (site_code, woo_refund_id) |
| `woo_order_id` | bigint | FK → `stg_woo_orders` | not_null |
| `refund_amount_src` | numeric | Số tiền hoàn (đơn vị gốc, luôn dương — đã lấy trị tuyệt đối) | |
| `refund_reason` | text | Lý do hoàn tiền | |
| `refund_created_at_utc` | timestamptz | Ngày giờ tạo refund | |
| `refund_date` | date | Ngày refund (date only) | Dùng để book refund theo ngày refund, KHÔNG phải ngày đơn hàng |

### `stg_woo_coupons`
**Mục đích:** Coupon đã ép kiểu.
**Grain:** 1 dòng = 1 coupon.

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | |
| `woo_coupon_id` | bigint | ID coupon | unique + not_null |
| `coupon_code` | text | Mã coupon | |
| `discount_type` | text | Loại giảm giá | |
| `amount` | numeric | Giá trị giảm giá | |
| `created_at_utc` / `modified_at_utc` | timestamptz | Ngày tạo/sửa | |

### `stg_manual_order_cost_enrichment`
**Mục đích:** Bảng chi phí thủ công đã ép kiểu (chưa FX) — nguồn đầu vào của `fact_order_cost` (Phase 3).
**Grain:** 1 dòng = 1 đơn hàng Woo (`site_code + woo_order_id`).

| Cột | Kiểu | Ý nghĩa | Ghi chú/Nguồn |
|---|---|---|---|
| `site_code` | text | Mã cửa hàng | not_null |
| `woo_order_id` | bigint | FK → `stg_woo_orders` | not_null; unique theo tổ hợp |
| `currency` | text | Tiền tệ (theo sheet) | |
| `order_date` | date | Ngày đơn hàng | |
| `cogs_usd` | numeric | COGS, đã là USD | Bao gồm phí fulfillment/ship của supplier |
| `design_fee_usd` | numeric | Phí thiết kế, đã USD | |
| `fee_src` | numeric | Phí thanh toán theo sheet (đơn vị gốc) | → FX thành `payment_fee_fallback_usd` ở `fact_order_cost` |
| `csv_shipping_charged_src` | numeric | Phí ship tính khách theo sheet (đơn vị gốc) | Chỉ để recon |
| `csv_revenue_observed_usd` | numeric | Revenue quan sát (đã USD) | Chỉ recon |
| `csv_profit_observed_usd` | numeric | Profit quan sát (đã USD) | Chỉ recon |
| `cost_source` | text | `'manual_csv'` | accepted_values: manual_csv, supplier_api |
| `cost_allocation_method` | text | `'order_only'` (chi phí chính xác ở mức đơn hàng) | accepted_values: line_exact, allocated_by_revenue_share, allocated_by_quantity_share, order_only |
| `cost_confidence` | numeric | `1.00` (chi phí đơn hàng chính xác 100%) | Độ tin cậy allocation xuống line-level thấp hơn (xem `mart_product_profit`, 0.60) |

### Seeds (nạp qua `dbt seed`, sống trong schema `staging`)

| Bảng | Mục đích | Cột chính |
|---|---|---|
| `country_iso_map` | Ánh xạ mã quốc gia nguồn → ISO code/tên/khu vực/tiền tệ chuẩn | `source_country`, `country_code`, `country_name`, `region`, `currency` |
| `dim_site_seed` | Cấu hình site (mirror `config/sites.yaml`) | `site_code` (PK), `site_name`, `domain`, `default_currency`, `timezone`, `reporting_timezone`, `is_active` |
| `dim_supplier_seed` | Danh sách nhà cung cấp POD | `supplier_code` (PK), `supplier_name`, `supplier_store_id`, `sla_days`, `is_active` |
| `fx_rates` | Tỷ giá USD theo ngày, nguồn ECB (Frankfurter), forward-fill mỗi ngày | `date`, `currency` (PK tổ hợp), `usd_rate`, `source` |
| `payment_fees` | Bảng phí thanh toán ước tính dự phòng (fallback) theo phương thức + quốc gia | `payment_method`, `country_code`, `fee_percent`, `fixed_fee_usd`, `source`, `is_active` (hiện tất cả `is_active=false` → không match, đơn hàng rơi về `missing`) |
| `product_cogs` | (Dự phòng — không dùng, COGS thật đến từ manual CSV) | `product_sku`, `cogs_usd`, `source`, `is_active` |
| `utm_campaign_map` | (Dự phòng, Phase 6/GA4) | `site_code`, `utm_campaign`, `channel_grouping`, `is_paid` |

---

*Tiếp theo: [07b — Từ điển dữ liệu: `marts_core`](07b-schema-marts-core.md)*
