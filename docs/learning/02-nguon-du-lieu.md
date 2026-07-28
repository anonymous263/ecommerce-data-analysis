# 02 — Nguồn dữ liệu (Data Sources)

> Đọc trước: chương 00, 01. Nguồn đối chiếu: `CLAUDE.md` (bảng "Source-of-truth mapping" +
> "Non-negotiable domain rules"), `README.md` §3, `config/sites.yaml`.

Một dự án BI/DA không bắt đầu bằng việc viết SQL — nó bắt đầu bằng câu hỏi: **"dữ liệu này
đến từ đâu, và ai là người nói đúng?"**. Dự án này có **3 nguồn dữ liệu** thật, mỗi nguồn chịu
trách nhiệm cho một mảng khác nhau của bức tranh kinh doanh. Không nguồn nào thay thế được
nguồn kia — đây là nguyên tắc **source of truth (nguồn sự thật)**: mỗi domain dữ liệu (đơn hàng,
chi phí, hành vi web...) chỉ có **một** hệ thống được phép là "đúng", mọi hệ thống khác chỉ
dùng để đối chiếu (reconciliation).

## 1. Ba nguồn dữ liệu

### (1) WooCommerce REST API — nguồn sự thật cho doanh thu & đơn hàng

WooCommerce là plugin bán hàng chạy trên WordPress. Vì mỗi cửa hàng của dự án này (ví dụ site
`FOS` — Fashion Open Studio) là một cửa hàng WooCommerce độc lập, REST API của nó là nơi
**duy nhất** biết chính xác:

- Đơn hàng (`orders`) và các dòng sản phẩm trong đơn (`line_items` → `order_items`)
- Sản phẩm (`products`) — catalog, biến thể (variant)
- Khách hàng (`customers`)
- Hoàn tiền / hủy đơn (`refunds`)
- Trạng thái đơn hàng (`status`)
- **Phí vận chuyển mà khách hàng trả** (`shipping_total` → `shipping_charged_usd`)
- Mã giảm giá (`coupons`)

Đây là **nguồn sự thật (source of truth)** cho toàn bộ domain "bán hàng". Không có nơi nào khác
trong hệ thống được phép ghi đè lên số liệu doanh thu hay trạng thái đơn hàng của Woo.

Ví dụ thực tế: Woo payload audit trên site FOS xác nhận `shipping_total` khác 0 trên
**4.755 / 4.757 đơn hàng**, và toàn bộ catalog (**58.168 / 58.168 sản phẩm**) đều là
`type = simple` — biến thể (size, màu) không đến từ Woo variation nativemà đến từ plugin
WCPA (Woo Custom Product Addons), nằm trong `line_items[].meta_data`. Đây là lý do tại sao
chương 03 nói "Python EL không diễn giải business logic" — việc *hiểu* cấu trúc payload là việc
của audit (`docs/WOO_PAYLOAD_AUDIT.md`), còn việc *transform* nó thành cột sạch là việc của dbt
staging (chương 05), không phải của lớp trích xuất.

### (2) CSV "Order Management" — nguồn sự thật cho chi phí (COGS)

WooCommerce không biết giá vốn sản phẩm — đây là mô hình print-on-demand (POD): mỗi đơn được
một nhà cung cấp bên ngoài (supplier) sản xuất và gửi hàng, và chi phí đó chỉ được người vận
hành ghi tay vào một Google Sheet, xuất ra thành `Order Management.csv`. File này là nguồn sự
thật cho:

- **`cogs_usd`** — giá vốn hàng bán, **đã bao gồm phí fulfillment/vận chuyển của nhà cung cấp**
  (đây là quy tắc bất biến số 6 trong `CLAUDE.md` — xem phần "Quy tắc bất biến" bên dưới)
- `design_fee_usd` — phí thiết kế
- Nhà cung cấp (supplier), mã tracking, URL fulfillment (Phase 5)

CSV này **không phải** nguồn sự thật cho doanh thu, đơn hàng, hoàn tiền, hay lợi nhuận cuối
cùng — dù cột `Revenue`/`Profit`/`ROI`/`Profit Margin` có tồn tại trong sheet, chúng **không bao
giờ** được copy thành số liệu chính thức. Chúng chỉ chảy vào các view
`marts_recon.recon_csv_vs_dbt_*` để theo dõi độ lệch (drift monitoring) — nếu CSV và dbt lệch
nhau quá 5%, đó là tín hiệu cảnh báo dữ liệu, không phải nguồn để tin.

### (3) GA4 BigQuery export — nguồn sự thật cho hành vi web

Google Analytics 4 xuất dữ liệu sự kiện (session, page view, add_to_cart, purchase...) vào
BigQuery mỗi ngày. Đây là nguồn sự thật cho **hành vi truy cập**: phễu chuyển đổi (funnel),
trang đích (landing page), nguồn traffic. GA4 thuộc **Phase 6** — bị khóa lại (gated) bởi một
audit riêng (`docs/GA4_BIGQUERY_AUDIT.md`): chỉ khi ≥85% sự kiện `purchase` khớp được
`transaction_id` với đơn hàng Woo, tính năng "attribution" (gán doanh thu theo kênh marketing)
mới được bật; nếu không, GA4 chỉ dùng để phân tích phễu/hành vi, không gán được về đơn hàng.

## 2. Bảng "hệ thống nào là nguồn sự thật"

| Domain | Nguồn sự thật | Cơ chế | Phase |
|---|---|---|---|
| Đơn hàng, dòng sản phẩm, sản phẩm, khách hàng, coupon, **trạng thái đơn** | **WooCommerce REST API** | Kéo tăng dần (incremental) hằng ngày → `raw.woo_*` | 1 |
| Hoàn tiền / hủy đơn | **WooCommerce** (endpoint `/refunds`) | Như trên | 1–2 |
| **COGS (gồm phí fulfillment/ship của supplier), design fee, supplier, tracking, fulfillment URL** | **CSV Order Management (thủ công)** | Nạp định kỳ → `raw.csv_order_management` | 3 (chi phí) + 5 (fulfillment) |
| Session, event, phễu, trang đích, nguồn traffic | **GA4 BigQuery export** | Trích xuất hằng ngày → `raw.ga4_*` | 6 |
| Chi phí quảng cáo / ROAS / CAC | Nền tảng quảng cáo — **hiện chưa chạy ads** | Hoãn lại | Optional Future |
| `E-commerce data sample/` (Maven Fuzzy Factory) | Chỉ để luyện tập/demo | Namespace riêng, không trộn với dữ liệu thật | Phase 0 / Phase 7 |

Việc lập bảng này **trước khi viết bất kỳ dòng code nào** là một bước quan trọng của quy trình
BI/DA: nó buộc bạn trả lời rõ ràng "ai thắng khi hai nguồn mâu thuẫn nhau" — trước khi bug xảy
ra, không phải sau.

## 3. Đa cửa hàng (multi-site)

Dự án phục vụ nhiều cửa hàng WooCommerce cùng lúc (hiện tại: site `FOS`), nên mọi tầng dữ liệu
— từ `raw` đến `marts` — phải mang theo một **định danh cửa hàng**:

- `site_code` — mã ngắn, con người đọc được (ví dụ `FOS`), dùng ở tầng `raw`/`staging` và làm
  khóa tra cứu.
- `site_sk` — surrogate key (khóa thay thế, xem chương 04) dạng số, dùng làm khóa ngoại trong
  các bảng fact ở tầng `marts` — nhanh hơn join bằng text.

Cấu hình site sống ở `config/sites.yaml` (Python đọc để biết endpoint, khóa API, múi giờ) và
được **phản chiếu (mirror)** sang `dbt/seeds/dim_site_seed.csv` — có một test dbt xác nhận hai
nơi này luôn khớp nhau, để không ai sửa một chỗ mà quên chỗ kia. Ví dụ cấu hình thật của site
FOS:

```yaml
sites:
  - site_code: FOS
    site_name: Fashion Open Studio
    base_url_env: WOO_FOS_BASE_URL   # URL storefront lấy từ .env, không commit
    key_env: WOO_FOS_KEY
    secret_env: WOO_FOS_SECRET
    default_currency: GBP
    supported_currencies: [USD, GBP, CAD, EUR]
    timezone: UTC              # timezone gốc của WordPress/Woo — dùng để watermark
    reporting_timezone: Asia/Bangkok   # timezone hiển thị trên dashboard
    is_active: true
```

Chú ý hai trường `timezone` khác nhau: `timezone` là múi giờ **nguồn** (WordPress/WooCommerce
lưu giờ theo gì), dùng để tính watermark tăng dần một cách chính xác — nhận xét trong cấu hình
nói rõ *không* dùng `Europe/London` cho FOS vì London có giờ tiết kiệm ánh sáng (DST), sẽ làm
lệch giờ UTC+1 vào mùa hè. `reporting_timezone` là múi giờ để **hiển thị** trên dashboard cho
người vận hành (ở Bangkok). Đây là một bài học tổng quát: đừng trộn lẫn "giờ hệ thống lưu" với
"giờ người dùng muốn xem".

**Khóa tự nhiên (natural key) của đơn hàng** trong toàn hệ thống là **`site_code + woo_order_id`**
— không dùng riêng `woo_order_id`, vì hai cửa hàng khác nhau hoàn toàn có thể có đơn hàng cùng
số ID (mỗi Woo instance tự đánh số độc lập). Quên ghép `site_code` vào là lỗi kinh điển khi mở
rộng một dự án single-tenant thành multi-tenant.

## 4. Các quy tắc bất biến quan trọng về nguồn dữ liệu

Đây là những quy tắc **không được vi phạm** — nếu vi phạm, mọi số liệu lợi nhuận phía sau sẽ sai
một cách âm thầm (silent corruption), không có lỗi nào báo ra để bạn biết.

1. **Cột CSV `Shipping` = phí ship mà KHÁCH HÀNG trả** (phía doanh thu — revenue-side), **không
   phải** chi phí trả cho nhà cung cấp. Nó chỉ được nạp vào để đối chiếu
   (`recon_woo_vs_csv_shipping_charged`) với con số chính thức là
   `fact_order.shipping_charged_usd` (lấy từ Woo `shipping_total`).
2. **`cogs_usd` (từ CSV) đã bao gồm phí fulfillment/vận chuyển của nhà cung cấp.** Không có cột
   `actual_shipping_cost_usd` nào tồn tại trong toàn bộ mô hình dữ liệu hay DAX. Nếu một ngày nào
   đó API nhà cung cấp tách riêng được phí ship, cả `cogs_usd` lẫn công thức lợi nhuận phải được
   thiết kế lại cùng lúc (xem `docs/DATA_MODEL.md §4.1`) — không tự ý cộng/trừ riêng lẻ.
3. **CSV `Revenue`/`Profit`/`ROI`/`Profit Margin` không bao giờ là số liệu chính thức** — chúng
   chỉ tồn tại trong `marts_recon.recon_csv_vs_dbt_*` để theo dõi độ lệch.
4. Dữ liệu thật (`Order Management.csv`, mọi bản trích xuất Woo thật) là **private, gitignored**
   — không commit, không export công khai (xem chương 03 để biết cách PII được xử lý ngay khi
   nạp).

## Khái niệm áp dụng được

- Trước khi code, hãy lập **bảng nguồn sự thật (source-of-truth mapping)** cho từng domain dữ
  liệu — nó ngăn xung đột "hai hệ thống, hai con số" xảy ra âm thầm về sau.
- Dữ liệu đối chiếu (reconciliation-only) — như CSV `Revenue`/`Profit` — nên bị cách ly rõ ràng
  (schema/mart riêng, ví dụ `marts_recon`), không bao giờ trộn vào số liệu chính thức.
- Trong hệ thống đa khách hàng/đa cửa hàng (multi-tenant), luôn ghép mã định danh tenant vào
  khóa tự nhiên — không tin ID của hệ thống nguồn là duy nhất toàn cục.
- Tách bạch "múi giờ hệ thống nguồn lưu trữ" (dùng để watermark/incremental) và "múi giờ hiển thị
  cho người dùng" (dùng để dashboard) — đây là hai khái niệm khác nhau, gộp chung sẽ gây lỗi off-by-one-hour.
- Khi một trường dữ liệu gộp nhiều ý nghĩa (như `cogs_usd` gộp cả phí ship supplier), hãy ghi rõ
  quy tắc đó thành bất biến (invariant) trong tài liệu — đừng để người đọc code tự suy luận sai.
