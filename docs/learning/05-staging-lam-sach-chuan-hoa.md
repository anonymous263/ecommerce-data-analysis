# 05 — Staging: Làm sạch & Chuẩn hóa

> Đọc trước: chương 03 (`03-trich-xuat-va-nap-EL.md`, layout schema `raw`) và chương 04
> (`04-mo-hinh-hoa-kimball.md`, fact/dim/grain). Nguồn đối chiếu: toàn bộ
> `dbt/models/staging/woocommerce/*.sql`, `dbt/models/staging/manual/stg_manual_order_cost_enrichment.sql`,
> `dbt/macros/hash_pii.sql`, `dbt/models/staging/**/_sources.yml`, `docs/PIPELINE_DESIGN.md §4/§9.5`,
> `docs/DATA_AUDIT.md`.

Dữ liệu vừa nạp vào schema `raw` (chương 03) vẫn còn "nguyên bản" — mọi thứ nằm trong cột
`_payload` JSONB, kiểu dữ liệu là text, PII còn nguyên (với Woo), tên trường theo quy ước của hệ
thống nguồn (`camelCase` hoặc snake_case tùy API). **`staging` là lớp đầu tiên trong dbt**, và vai
trò của nó rất hẹp và có kỷ luật: **làm sạch và chuẩn hóa**, KHÔNG áp bất kỳ logic kinh doanh nào
(không cộng dồn, không tính lợi nhuận, không phân bổ chi phí — đó là việc của `marts`, xem chương
06). `docs/PIPELINE_DESIGN.md §4` tóm tắt đúng bốn việc của lớp này: **"Cleaned, typed, deduped,
PII hashed."**

Mọi model staging trong dự án đều là **view** (`{{ config(materialized='view') }}`) — không phải
table vật chất hoá. Lý do: staging chỉ là một "ống kính" đọc lại `raw` với kiểu dữ liệu đúng, chi
phí lưu trữ gần như bằng 0, và luôn phản ánh dữ liệu `raw` mới nhất mà không cần chạy lại
transform tốn kém.

## 1. Ép kiểu (typing) — trích từ JSONB text sang kiểu đúng

Payload Woo nằm trong `_payload` JSONB; mọi giá trị đọc ra bằng `->>'key'` đều có kiểu `text`, kể
cả số và ngày. Việc đầu tiên của staging là ép chúng về đúng kiểu, đồng thời xử lý các giá trị
rỗng/thiếu một cách tường minh. Ví dụ thật trong `stg_woo_orders.sql`:

```sql
nullif(s.p->>'total',  '')::numeric                              as order_total_src,
nullif(s.p->>'shipping_total', '')::numeric                      as shipping_charged_src,
nullif(trim(upper(s.p->'billing'->>'country')), '')             as billing_country_code,
(s.status in ('cancelled', 'failed'))                            as status_is_cancelled,
```

Vì sao dùng `nullif(x, '')` trước khi `::numeric`? Vì JSON trả về chuỗi rỗng `''` cho một trường
thiếu, và `''::numeric` sẽ **ném lỗi runtime** thay vì cho ra `NULL` — `nullif` biến chuỗi rỗng
thành `NULL` trước, để phép ép kiểu không bao giờ crash trên dữ liệu thiếu. Đây là một mẫu hình
lặp lại xuyên suốt mọi file staging trong dự án.

`stg_woo_order_items.sql` còn cho thấy kiểu "làm sạch số" khác — chặn giá trị âm/vô lý ngay tại
staging:

```sql
greatest(coalesce((s.p->>'quantity')::int, 0), 0)          as quantity,
```

Và làm sạch chuỗi bị "đóng gói" bởi plugin biến thể (WCPA) — giá trị thô dạng `'L | L | #ffffff'`
chỉ giữ lại đoạn sạch đầu tiên:

```sql
nullif(trim(split_part(a.size_raw, '|', 1)), '') as size,
```

`print_location` còn có thêm một bước regex để bóc các hậu tố phụ phí lặp lại
(`'Back ($0.00)'`, `'Both side (£5.95) (£5.95)'`) — một ví dụ cho thấy typing không chỉ là ép
kiểu số/ngày, mà còn là **chuẩn hóa chuỗi** khi nguồn dữ liệu không sạch sẵn.

## 2. Quy đổi tiền tệ (FX) — staging CHUẨN BỊ, không tự quy đổi

Đây là một điểm dễ hiểu nhầm nếu chỉ đọc lý thuyết chung, nên cần nói chính xác theo code thật của
dự án: **staging KHÔNG tự quy đổi tiền tệ về USD.** Comment đầu `stg_woo_orders.sql` nói rõ:

```
Money stays in source currency (*_src); FX to USD happens in the fact layer.
```

Vai trò của staging ở khâu này là **chuẩn bị đúng nguyên liệu** cho việc quy đổi diễn ra chính xác
ở lớp `marts` (chương 06): mọi cột tiền được đặt tên với hậu tố `_src` (giữ nguyên đơn vị tiền tệ
gốc, ví dụ `order_total_src`, `shipping_charged_src`, `line_total_src`, `refund_amount_src`), và
cột `currency_source`/`currency` được giữ lại song song để lớp fact biết phải tra tỷ giá nào.
`stg_manual_order_cost_enrichment.sql` cũng theo đúng khuôn mẫu này — trừ hai cột `cogs_usd` và
`design_fee_usd` đã là USD sẵn trong sheet (không cần FX), mọi cột tiền khác vẫn giữ hậu tố `_src`.

Việc quy đổi thật sự diễn ra ở `fact_order.sql`, join với seed `fx_rates` (nguồn ECB — European
Central Bank) theo **đúng ngày phát sinh giao dịch** (không phải "tỷ giá mới nhất"):

```sql
-- one usd_rate per (date, currency); the seed is forward-filled daily so
...
coalesce(fo.usd_rate, 1.0)   as fx_rate_to_usd,
```

Vì sao phải tách hai bước (staging giữ `_src`, fact mới quy đổi) thay vì quy đổi ngay ở staging?
Vì quy đổi tiền tệ **cần join với một bảng khác** (seed `fx_rates`) theo **ngày** — mà ngày dùng để
tra tỷ giá lại khác nhau tùy loại giao dịch (đơn hàng dùng `order_date`, hoàn tiền dùng
`refund_date` — xem chương 06, "book on refund date"). Gộp việc quy đổi vào staging sẽ buộc mỗi
model staging phải tự lặp lại logic join tỷ giá, thay vì để một nơi duy nhất (lớp fact) chịu trách
nhiệm. Đồng thời, giữ `*_src` song song với `*_usd` (ở lớp fact) cho phép audit ngược: nếu một con
số USD trông sai, ta luôn có thể quay lại `*_src` + `currency` để kiểm tra xem lỗi nằm ở dữ liệu
gốc hay ở phép quy đổi.

## 3. Băm PII (hashing) — dữ liệu cá nhân không bao giờ đi qua ranh giới ở dạng thô

Đây là quy tắc **cứng** của dự án (`CLAUDE.md`, "Privacy"): **PII không bao giờ được phép đi qua
ranh giới `raw → staging` ở dạng plaintext (chữ rõ)**. Macro `hash_pii` (định nghĩa tại
`dbt/macros/hash_pii.sql`) là công cụ duy nhất thực hiện việc này:

```sql
case
    when nullif(trim({{ column_expr }}), '') is null then null
    else encode(
        sha256(convert_to(lower(trim({{ column_expr }})) || '{{ env_var("PII_SALT") }}', 'UTF8')),
        'hex'
    )
end
```

Công thức đúng như tài liệu định nghĩa: **`SHA-256(lower(trim(email)) || PII_SALT)`** — hạ chữ
thường, cắt khoảng trắng thừa, nối thêm một chuỗi bí mật (`PII_SALT`, đọc từ biến môi trường)
trước khi băm. `PII_SALT` là lý do vì sao cùng một email luôn cho ra cùng một hash (để join khách
hàng lặp lại được), nhưng không ai có thể "đảo ngược" hash để suy ra email gốc nếu không biết salt.

Macro được gọi trực tiếp trong hai model: `stg_woo_orders.sql` (`billing_email_hash`) và
`stg_woo_customers.sql` (`customer_email_hash`). Tên, số điện thoại, địa chỉ, IP, user-agent
**không bao giờ được `SELECT`** ra khỏi payload — không phải "ẩn đi", mà đơn giản là các cột đó
không tồn tại trong bất kỳ model staging nào.

Vì cửa hàng này chủ yếu là **guest checkout** (khách mua không đăng ký tài khoản —
`raw.woo_customers` hiện rỗng), việc "khách hàng là ai" hoàn toàn dựa vào email đã băm trên đơn
hàng. `stg_woo_orders.sql` xử lý cả trường hợp thiếu email:

```sql
coalesce(
    billing_email_hash,
    'unknown:' || site_code || ':' || woo_order_id::text
) as customer_hash
```

Nếu đơn không có email, `customer_hash` trở thành một khóa duy nhất cho riêng đơn đó (tiền tố
`unknown:`) — **không gộp chung** các đơn ẩn danh khác nhau vào một "khách hàng ma" duy nhất, và
cũng không thể liên kết các đơn ẩn danh với nhau (đúng bản chất: không biết đó có phải cùng một
người hay không). Đây là điểm quan trọng: **mất `PII_SALT` là mất toàn bộ khả năng liên kết khách
hàng** — mọi `customer_hash` sẽ đổi giá trị nếu salt đổi, phá vỡ liên kết lịch sử mua hàng của mọi
khách. Vì vậy `PII_SALT` phải được sao lưu offline, tách biệt khỏi repo (nó sống trong `.env`,
gitignored — xem chương 03).

## 4. Khử trùng lặp (dedupe) và chuẩn hóa tên cột

Khái niệm **dedupe (khử trùng lặp)** trong staging thường giải quyết vấn đề: một hệ thống nguồn có
thể trả về nhiều bản ghi cho cùng một khóa tự nhiên (do re-extract, do lỗi phân trang, do API trả
trùng), và staging phải đảm bảo mỗi khóa tự nhiên chỉ còn **đúng một dòng** trước khi tới lớp fact
(kỹ thuật phổ biến: `DISTINCT ON (...)` hoặc `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY
extracted_at DESC)` rồi lọc `= 1`).

Trong dự án này, bước đó được giải quyết **sớm hơn** — ngay tại lớp EL (chương 03): Python nạp dữ
liệu Woo bằng **idempotent upsert theo `(site_code, woo_<entity>_id)`** (`docs/PIPELINE_DESIGN.md
§4`), nên bảng `raw` đã đảm bảo duy nhất theo khóa tự nhiên trước khi dbt chạm vào — các test
`dbt_utils.unique_combination_of_columns` trong `_sources.yml` (ví dụ trên `woo_orders`,
`woo_order_items`, `woo_refunds`, `woo_coupons`) xác nhận đúng bất biến này. Vì vậy các model
staging trong dự án không cần thêm `DISTINCT ON`/`ROW_NUMBER` — chúng thừa hưởng tính duy nhất đã
được đảm bảo ở tầng dưới. Bài học tổng quát vẫn còn nguyên: **luôn xác nhận uniqueness bằng test,
đừng giả định** — nếu một dự án khác không có upsert idempotent ở EL, staging bắt buộc phải tự
dedupe.

Chuẩn hóa tên cột cũng là việc của staging: mọi tên trường JSON (`date_created_gmt`, camelCase nếu
có) được đổi thành **snake_case** nhất quán, và các hậu tố quy ước được áp dụng xuyên suốt: `_src`
(tiền tệ gốc), `_usd` (chỉ xuất hiện ở marts), `_hash` (PII đã băm), `_at_utc` (timestamp), `_code`
(mã chuẩn hóa, ví dụ `billing_country_code` luôn viết hoa qua `upper(...)`).

## 5. Điểm qua từng model staging chính

| Model | Nguồn | Việc chính |
|---|---|---|
| `stg_woo_orders` | `raw.woo_orders` | Ép kiểu header đơn, băm email, dựng `customer_hash`, bóc phí thanh toán plugin (Stripe/PayPal) từ `meta_data` |
| `stg_woo_order_items` | `raw.woo_order_items` | Ép kiểu dòng sản phẩm (nơi doanh thu sẽ sống ở fact), làm sạch biến thể (Size/Color/Style/Fit Type/Print location) từ `meta_data` của plugin WCPA |
| `stg_woo_products` | `raw.woo_products` | Ép kiểu catalog sản phẩm, grain `(site_code, woo_product_id)` |
| `stg_woo_customers` | `raw.woo_customers` | Băm email khách đăng ký; hiện ít dùng vì bảng nguồn rỗng (guest checkout áp đảo) |
| `stg_woo_refunds` | `raw.woo_refunds` | Ép kiểu hoàn tiền, lấy trị tuyệt đối `refund_amount_src` (Woo lưu số âm ở một số site) |
| `stg_woo_coupons` | `raw.woo_coupons` | Ép kiểu mã giảm giá |
| `stg_manual_order_cost_enrichment` | `raw.csv_order_management` | Ép kiểu chi phí COGS/design fee (đã USD sẵn) + phí/ship khách (còn `_src`), không PII (đã drop lúc nạp — chương 03) |

Mỗi model chỉ đọc **đúng một** bảng `raw` tương ứng (1 nguồn : 1 staging model) — chưa có join
giữa các thực thể khác nhau (đơn với sản phẩm, đơn với chi phí) ở tầng này; việc join liên-thực-thể
là công việc của `marts` (chương 06).

## Khái niệm áp dụng được

- **Staging chỉ làm sạch & chuẩn hóa, không áp logic kinh doanh** — ranh giới rõ ràng giữa "dữ
  liệu đúng kiểu" (staging) và "số liệu kinh doanh đúng" (marts) giúp debug dễ hơn: sai ở staging
  là sai kiểu/parse, sai ở marts là sai công thức.
- **Luôn `nullif(x, '')` trước khi ép kiểu số/ngày** trên dữ liệu JSON — chuỗi rỗng gây lỗi runtime
  khi cast, còn `NULL` thì không.
- **Giữ tiền ở đơn vị gốc (`*_src`) tại staging; chỉ quy đổi FX ở lớp cần join theo ngày đúng ngữ
  cảnh** (ngày đặt hàng khác ngày hoàn tiền) — tách trách nhiệm này giúp mỗi loại giao dịch tra
  đúng tỷ giá của chính nó, và giữ khả năng audit ngược về số gốc.
- **PII phải bị băm một chiều (`SHA-256 + salt`) ngay khi rời khỏi `raw`, không có ngoại lệ** — và
  `PII_SALT` phải được backup an toàn, tách biệt khỏi mã nguồn: mất salt nghĩa là mất toàn bộ liên
  kết khách hàng vĩnh viễn.
- **Đảm bảo uniqueness bằng test tường minh (`unique_combination_of_columns`), đừng giả định** —
  dedupe có thể xảy ra ở EL (upsert) hoặc ở staging (`DISTINCT ON`/`ROW_NUMBER`), miễn là có một
  nơi chịu trách nhiệm và có test xác nhận.
- **Chuẩn hóa tên cột & hậu tố nhất quán** (`_src`, `_hash`, `_code`, `_at_utc`) giúp người đọc
  SQL đoán được ý nghĩa cột ngay cả khi chưa mở tài liệu (xem chương 07 để tra từng cột chi tiết).
