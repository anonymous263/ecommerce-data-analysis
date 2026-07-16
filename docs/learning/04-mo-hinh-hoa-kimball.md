# 04 — Mô hình hóa Kimball & Star Schema

> Đọc trước: chương 00–03. Nguồn đối chiếu: `docs/DATA_MODEL.md` (toàn bộ), và code thật trong
> `dbt/models/marts/core/` (`fact_order.sql`, `fact_order_item.sql`, `fact_refund.sql`,
> `dim_date.sql`, `dim_site.sql`, `dim_product.sql`, `dim_customer_anonymized.sql`,
> `dim_country.sql`, `dim_payment_method.sql`).

Sau khi dữ liệu thô đã nằm an toàn trong schema `raw` (chương 03), câu hỏi tiếp theo là: **tổ
chức lại nó thành hình dạng gì để một người phân tích (analyst) hoặc một báo cáo Power BI có thể
truy vấn nhanh, đúng, và dễ hiểu?** Câu trả lời kinh điển trong ngành BI/DA là **mô hình hóa
Kimball (Kimball dimensional modeling)** — đặt tên theo Ralph Kimball, người đưa ra phương pháp
này từ thập niên 1990 — và hình dạng kết quả gọi là **star schema (mô hình hình sao)**.

Đây không phải là kiến thức "để biết cho vui" — đây là **nền tảng thiết kế của toàn bộ lớp
`marts_*`** trong dự án này. Bỏ qua chương này, chương 06 (marts) sẽ đọc như một mớ SQL rời rạc;
hiểu chương này, chương 06 chỉ là "áp dụng khái niệm × dữ liệu POD cụ thể".

## 1. Fact vs Dimension — động từ và danh từ

Cách nhớ đơn giản nhất: **fact = động từ, dimension = danh từ.**

- **Fact (bảng sự kiện)** ghi lại **điều gì đã xảy ra** — một hành động, một giao dịch, một phép
  đo. Nó luôn có ít nhất một **con số đo lường được (measure)**: số tiền, số lượng, thời lượng...
  Ví dụ trong dự án: "khách hàng mua 1 áo giá 25 USD" là một sự kiện → dòng trong
  `fact_order_item`.
- **Dimension (bảng chiều/ngữ cảnh)** mô tả **bối cảnh** của sự kiện đó — ai, cái gì, ở đâu, khi
  nào. Nó phần lớn là các cột mô tả (text), ít khi có con số cộng dồn được. Ví dụ: "sản phẩm đó
  tên gì, thuộc loại gì" → `dim_product`; "ngày đó là thứ mấy, quý nào" → `dim_date`.

Nhìn vào chính schema của dự án:

| Bảng | Loại | Vì sao |
|---|---|---|
| `fact_order` | Fact | Ghi lại sự kiện "một đơn hàng được tạo" — có `order_total_usd`, `shipping_charged_usd`... |
| `fact_order_item` | Fact | Ghi lại sự kiện "một dòng sản phẩm được bán" — có `line_revenue_usd`, `quantity` |
| `fact_refund` | Fact | Ghi lại sự kiện "một khoản tiền được hoàn" — có `refund_amount_usd` |
| `dim_date` | Dimension | Mô tả một ngày lịch — `year`, `quarter`, `is_weekend`, không có con số để SUM |
| `dim_product` | Dimension | Mô tả một sản phẩm — `product_name`, `product_type`, không đo lường gì |
| `dim_site` | Dimension | Mô tả một cửa hàng — `site_name`, `default_currency`, `timezone` |

Một cách kiểm tra nhanh khi phân vân "cái này là fact hay dimension?": **hỏi "tôi có muốn SUM
hoặc COUNT cột này không?"**. Nếu có → nhiều khả năng đó là measure trong fact. Nếu bạn chỉ muốn
`GROUP BY` hoặc `WHERE` theo nó → đó là thuộc tính dimension.

## 2. Grain — độ mịn của một dòng dữ liệu

**Grain (độ mịn / hạt)** là câu trả lời cho câu hỏi: **"một dòng trong bảng này đại diện cho
điều gì, chính xác?"** Đây là quyết định **quan trọng nhất** khi thiết kế một fact table — sai
grain là nguồn gốc của hầu hết lỗi double-count (đếm trùng) trong BI.

`docs/DATA_MODEL.md §2` viết grain của từng fact **trước khi** viết bất kỳ cột nào — đây là thực
hành bắt buộc, không phải tùy chọn:

| Fact | Grain (một dòng = ...) |
|---|---|
| `fact_order` | một đơn hàng (`site_code + woo_order_id`) |
| `fact_order_item` | một dòng sản phẩm trong một đơn hàng |
| `fact_refund` | một lần hoàn tiền/hủy đơn (grain theo đơn hàng, không theo dòng sản phẩm) |
| `fact_order_cost` | một đơn hàng (chi phí chỉ có ở mức đơn, không có ở mức dòng) |

Vì sao dự án cần **cả hai** `fact_order` lẫn `fact_order_item`, thay vì gộp làm một bảng? Vì
chúng có **grain khác nhau**: một đơn hàng có thể có nhiều dòng sản phẩm (1 đơn : N dòng). Nếu
gộp doanh thu (`line_revenue_usd`, grain dòng) và tổng đơn (`order_total_usd`, grain đơn) vào
cùng một bảng ở grain dòng, thì mỗi lần bạn `SUM(order_total_usd)` trên một đơn có 3 dòng sản
phẩm, bạn sẽ cộng `order_total_usd` **ba lần** — sai gấp 3. Đây chính xác là lý do quy tắc bất
biến số 1 của dự án tồn tại:

> **"Doanh thu chỉ sống ở một nơi duy nhất: `fact_order_item.line_revenue_usd`. `fact_order`
> không có cột `revenue_usd`."**

Nhìn vào comment thật trong `fact_order.sql`:

```sql
-- Order header fact. INVARIANT: NO revenue_usd column here (revenue lives once
-- on fact_order_item) — this prevents the order x item double-count.
```

Và trong `fact_order_item.sql`, đây là nơi **duy nhất** revenue được tính:

```sql
round(i.line_total_src * coalesce(fx.usd_rate, 1.0), 6) as line_revenue_usd,
```

Bài học tổng quát: **khi hai thực thể có quan hệ một-nhiều (1:N), chúng gần như luôn cần hai
fact table ở hai grain khác nhau** (hoặc một fact ở grain mịn nhất, và bảng còn lại chỉ giữ
thuộc tính header không lặp lại theo dòng) — không được trộn số liệu grain-thô (đơn) vào bảng
grain-mịn (dòng) mà không chia đều, và ngược lại không đặt số liệu grain-mịn lên bảng grain-thô.

`fact_refund` là một ví dụ khác về grain phải được **xác nhận bằng dữ liệu thật**, không đoán:
comment trong `fact_refund.sql` cho biết audit `WOO_PAYLOAD_AUDIT §7` phát hiện `line_items`
rỗng trên **toàn bộ** refund payload của Woo, nên `fact_refund` buộc phải ở grain đơn hàng
(`order_item_sk` luôn NULL), dù `DATA_MODEL.md` có để ngỏ khả năng grain dòng sản phẩm nếu audit
xác nhận dữ liệu hỗ trợ. Đây là bài học: **đừng thiết kế grain theo lý thuyết — kiểm tra payload
thật trước, rồi mới khóa grain.**

## 3. Surrogate Key vs Natural Key

Một **natural key (khóa tự nhiên)** là định danh có sẵn từ hệ thống nguồn — ví dụ `woo_order_id`
do WooCommerce tự sinh. Vấn đề: trong hệ thống **đa cửa hàng (multi-site)**, `woo_order_id` chỉ
duy nhất **trong phạm vi một cửa hàng**, không duy nhất toàn hệ thống (hai site khác nhau hoàn
toàn có thể cùng có đơn `#1042`). Vì vậy natural key thật của đơn hàng trong dự án là **cặp**
`site_code + woo_order_id` (đã nói ở chương 02).

Một **surrogate key (khóa thay thế)** là khóa **do warehouse tự sinh ra**, không mang ý nghĩa
nghiệp vụ, chỉ dùng để join nhanh giữa các bảng trong star schema. Quy ước đặt tên của dự án:
hậu tố `_sk` (ví dụ `order_sk`, `site_sk`, `product_sk`, `customer_sk`, `country_sk`,
`payment_method_sk`, `date_sk`).

Cách sinh surrogate key trong dự án dùng macro `dbt_utils.generate_surrogate_key` — một hash
ổn định (deterministic) trên một hoặc nhiều cột input. Ví dụ thật từ `fact_order.sql`:

```sql
{{ dbt_utils.generate_surrogate_key(['site_code', 'woo_order_id']) }}   as order_sk,
{{ dbt_utils.generate_surrogate_key(['site_code']) }}                   as site_sk,
```

Vì sao không chỉ dùng `woo_order_id` làm khóa join luôn cho gọn? Ba lý do:

1. **Tránh đụng độ đa site** — như đã giải thích, `woo_order_id` không duy nhất toàn cục;
   `generate_surrogate_key(['site_code', 'woo_order_id'])` băm cả hai cột lại, đảm bảo duy nhất.
2. **Cách ly khỏi thay đổi ở hệ thống nguồn** — nếu một ngày Woo đổi kiểu dữ liệu ID hay dự án
   thêm nguồn dữ liệu mới ngoài Woo, các bảng fact/dimension khác không cần sửa lại kiểu khóa.
3. **Nhất quán kiểu dữ liệu để join nhanh** — mọi `_sk` đều cùng một dạng (text hash trong dự án
   này), nên logic join giữa fact và dimension luôn đồng nhất, không phải xử lý case-by-case.

Một ngoại lệ đáng chú ý: **`date_sk` không dùng hash**, mà dùng **số nguyên thông minh (smart
key)** dạng `YYYYMMDD`:

```sql
to_char(order_date, 'YYYYMMDD')::int as date_sk,
```

Đây là quy ước phổ biến trong Kimball modeling cho chiều ngày: `date_sk` vừa là khóa join, vừa
**tự đọc được** (20260716 = 16/07/2026) và join cực nhanh (so sánh số nguyên) — không cần tra
bảng để biết dòng đó là ngày nào.

## 4. Conformed Dimension — chiều dùng chung nhiều fact

**Conformed dimension** là một dimension được xây **một lần duy nhất** rồi **dùng chung** cho
nhiều fact table khác nhau, đảm bảo khi hai báo cáo khác nhau cùng "cắt theo ngày" hoặc "cắt theo
cửa hàng", chúng luôn dùng **cùng một định nghĩa** — không có chuyện dashboard A tính "tuần" khác
dashboard B.

Trong dự án, `dim_date` và `dim_site` là hai conformed dimension rõ nét nhất:

- `dim_date` (sinh từ `dbt_utils.date_spine`, phủ 2020-01-01 → 2030-12-31) được join vào
  **mọi** fact có mốc thời gian: `fact_order`, `fact_order_item`, `fact_refund`, và sau này
  `fact_order_cost`, `fact_fulfillment`, `fact_ga4_*`. Chỉ cần định nghĩa "quý 3 bắt đầu từ
  tháng 7" một lần ở đây, mọi fact tự động đồng nhất.
- `dim_site` (sinh từ seed `dim_site_seed.csv`, phản chiếu `config/sites.yaml`) được join vào
  mọi fact vì dự án là **multi-site** — mọi số liệu đều có thể cắt theo cửa hàng.

Nếu không có conformed dimension, mỗi fact sẽ tự định nghĩa lại "ngày" hoặc "cửa hàng" theo cách
riêng — hai báo cáo dùng hai fact khác nhau có thể cho ra hai con số "doanh thu tháng 7" khác
nhau chỉ vì định nghĩa "tháng 7" bị lệch.

## 5. Xử lý dimension "khuyết" — dòng đại diện cho unknown

Một chi tiết thực dụng đáng học: dimension trong dự án luôn có một **dòng đại diện cho giá trị
thiếu**, để **foreign key trong fact luôn resolve được**, không bao giờ NULL join thất bại.

Ví dụ `dim_country.sql`:

```sql
-- A synthetic 'XX' row absorbs orders with no billing country so every fact FK resolves.
```

Và `dim_payment_method.sql`:

```sql
-- A synthetic 'unknown' row absorbs orders missing a payment_method so the FK resolves.
```

Đây là kỹ thuật Kimball gọi là **"the missing member"** hoặc **default row pattern**: thay vì để
`country_sk` là NULL khi đơn hàng không có `billing_country`, dimension chủ động tạo sẵn dòng
`country_code = 'XX'`, và fact luôn join thành công. Lợi ích: các công cụ BI (kể cả Power BI) xử
lý `INNER JOIN` an toàn hơn `LEFT JOIN` có NULL, và người xem dashboard thấy "Unknown" như một
danh mục tường minh thay vì một dòng biến mất khỏi báo cáo.

## 6. Star Schema vs Snowflake Schema

**Star schema (mô hình hình sao)**: một fact table ở giữa, các dimension nối trực tiếp vào fact
bằng **một** join, không có dimension nối vào dimension khác. Vẽ ra trông như ngôi sao — fact ở
tâm, dimension là các tia xung quanh. Đây chính xác là hình dạng `docs/DATA_MODEL.md §8` mô tả:

```
                       ┌──────────────┐
                       │  dim_date    │
                       └──────┬───────┘
                              │
   ┌──────────┐               │            ┌──────────────┐
   │ dim_site ├───┐           │        ┌───┤ dim_product  │
   └──────────┘   │           │        │   └──────────────┘
                  ▼           ▼        ▼
   ┌──────────────────────────────────────────┐
   │ fact_order_item  (REVENUE)               │
   └────────────────────────────────────────────┘
```

**Snowflake schema**: các dimension được **chuẩn hóa (normalize)** thêm một bước — ví dụ
`dim_product` lại tách ra `dim_product_category` riêng, `dim_country` tách ra `dim_region`
riêng — dimension nối vào dimension, tạo thành nhiều nhánh nhỏ như bông tuyết.

Dự án này **chọn star, không chọn snowflake**, và lý do được nêu ngay ở đầu `DATA_MODEL.md §1`:

> "All relationships are single-direction (dim → fact) on surrogate keys."

Ba lý do thực dụng cho lựa chọn này:

1. **Dễ hiểu với người không rành SQL** — một nhà phân tích BI mở Power BI, thấy fact ở giữa,
   kéo `dim_product.product_type` vào slicer là xong, không cần biết phải nối qua mấy tầng bảng
   trung gian.
2. **Nhanh hơn khi truy vấn** — mỗi thêm một tầng chuẩn hóa là thêm một phép join; star schema
   tối thiểu hóa số lượng join cần thiết để trả lời một câu hỏi.
3. **Hợp với mô hình quan hệ (relationship) của Power BI** — Power BI dùng engine cột (VertiPaq)
   được tối ưu cho quan hệ 1-nhiều dạng star; càng gần dạng star, DAX càng đơn giản và nhanh
   (xem chương 09).

Cái giá phải trả của star schema là một chút **dư thừa dữ liệu (denormalization)** — ví dụ
`dim_country.country_name` có thể lặp lại cho nhiều dòng cùng `country_code` nếu không tách
riêng — nhưng trong ngữ cảnh phân tích (đọc nhiều, ghi ít), đánh đổi này gần như luôn đáng giá.

## 7. Áp dụng vào chính dự án: đọc lại một fact hoàn chỉnh

Ghép lại toàn bộ khái niệm bằng ví dụ `fact_order_item` — fact quan trọng nhất dự án vì nó giữ
doanh thu chính thức:

```sql
{{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_order_id', 'i.woo_order_item_id']) }}
    as order_item_sk,                                          -- surrogate key của chính fact
{{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_order_id']) }}
    as order_sk,                                                -- FK về fact_order (cùng grain đơn)
{{ dbt_utils.generate_surrogate_key(['i.site_code']) }}
    as site_sk,                                                 -- FK về conformed dim_site
to_char(o.order_date, 'YYYYMMDD')::int as date_sk,               -- FK về conformed dim_date
{{ dbt_utils.generate_surrogate_key(['i.site_code', 'i.woo_product_id']) }}
    as product_sk,                                               -- FK về dim_product
...
round(i.line_total_src * coalesce(fx.usd_rate, 1.0), 6) as line_revenue_usd  -- measure duy nhất giữ doanh thu
```

Grain của dòng này là **một dòng sản phẩm trong một đơn** — khớp chính xác với
`order_item_sk = surrogate_key(site_code, woo_order_id, woo_order_item_id)`: ba cột này cùng
nhau xác định duy nhất một dòng, đúng bằng định nghĩa grain đã khai báo. Đây là cách kiểm tra
"grain và surrogate key có khớp nhau không" trong thực tế: **các cột đưa vào
`generate_surrogate_key` của khóa chính phải chính là các cột định nghĩa grain.**

## Khái niệm áp dụng được

- **Fact = động từ (đo lường được), Dimension = danh từ (mô tả ngữ cảnh).** Dùng phép thử "tôi
  có muốn SUM/COUNT cột này không?" để phân loại nhanh.
- **Viết grain statement trước khi viết một cột SQL nào** — grain sai là nguồn gốc phổ biến nhất
  của lỗi double-count trong BI. Xác nhận grain bằng dữ liệu thật (audit payload), không đoán.
- **Surrogate key (`_sk`) cách ly warehouse khỏi thay đổi ở hệ thống nguồn** và giải quyết vấn đề
  ID không duy nhất toàn cục trong hệ thống multi-tenant. Các cột tạo surrogate key của khóa
  chính phải khớp đúng grain đã khai báo.
- **Conformed dimension** (như `dim_date`, `dim_site`) phải được xây một lần, dùng chung cho mọi
  fact — đảm bảo mọi báo cáo cắt theo cùng một định nghĩa "ngày"/"cửa hàng" (xem chương 07 để
  tra từng cột).
- **Dùng dòng "unknown/XX" đại diện cho giá trị thiếu trong dimension**, để foreign key trong
  fact không bao giờ join thất bại — tường minh hơn để NULL trôi tự do.
- **Chọn star schema thay vì snowflake** khi mục tiêu là tốc độ truy vấn và dễ hiểu cho BI tool
  (Power BI) — chấp nhận một chút dư thừa dữ liệu để đổi lấy ít join hơn (xem chương 09 về quan
  hệ trong Power BI).
