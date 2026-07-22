# FOS Analytics — Capstone Dashboard Build Guide

Hướng dẫn dựng **dashboard vận hành FOS** trong Power BI Desktop, khớp 1-1 với artifact demo (6 trang, theme cyan/sand, tooltip + bookmark + drill-through).

> ⚠️ Đây là guide cho **bản capstone operational** (6 trang, business-question driven, không gating/caveat). Nó **khác** `BUILD_GUIDE.md` (bản MVP gốc của project với 5 trang + tier-gating). Dùng đúng file cho đúng mục tiêu.

> ### Nếu bạn đã dựng measure TRƯỚC Approach A (2026-07-21)
> **Approach A không sửa công thức DAX nào** — commit `b0380a1` chỉ đổi mô tả và text của Profit Caveat Banner. Toàn bộ thay đổi giá trị đến từ mart dbt. Vì vậy:
> - Measure đọc thẳng từ mart (`Contribution Profit`, `Profit Base Net Revenue`, `COGS`, …) → **tự đúng sau khi Refresh**, không phải sửa tay.
> - **Phải kiểm 1 chỗ:** mẫu số của `Profit Margin` / `Cost Ratio` / `COGS Ratio` **bắt buộc** là `[Profit Base Net Revenue]`. Nếu bạn lỡ dùng `[Net Revenue]` (product-only) → margin đang **sai lệch rất lớn** (73.8% thay vì 55.1% — profit có shipping trong cơ sở nhưng mẫu số thì không).
> - File `.pbix` của bạn là local, không nằm trong git → không có commit nào chạm vào nó được.

> ### ⚠️ Nếu bạn đã dựng trang Markets / Products trước bản guide này
> Các measure profit theo **country** và **product** trong bản guide cũ trả về **grand total giống hệt nhau cho mọi dòng** (Power BI không báo lỗi). Xem §2.3b, §3.5b, §3.6 và dựng lại các visual ở Page 2/3/4 theo bộ measure mới.

**Deliverables đi kèm:**
- Theme: `powerbi/themes/fos_dashboard_theme.json`
- Background canvas: `powerbi/backgrounds/background.png` (1920×1080)

**6 trang sẽ dựng:** 1) Overview · 2) Cost & Margin · 3) Products · 4) Markets · 5) Customers · 6) Operations.

---

## 0. Chuẩn bị

- Power BI Desktop (bản tháng gần nhất).
- Postgres 16 chạy trong Docker (`ecommerce_postgres`), các schema `marts_*` đã build (`dbt build` xanh).
- Connector PostgreSQL (Npgsql) — Power BI Desktop có sẵn; nếu hỏi thì cài Npgsql.

---

## 1. Canvas · Theme · Background

### 1.1 Kích thước trang
**View → Page view → Actual size.** Với mỗi trang: **Format page → Canvas settings → Type = Custom → Width 1920, Height 1080.**

### 1.2 Áp theme
**View → Themes → Browse for themes →** chọn `fos_dashboard_theme.json`. Theme này đã set: dataColors (cyan/sand/green/violet/slate…), card bo góc 12px + shadow nhẹ + viền `#E9EEF5`, font Segoe UI, page background `#F5F7FA`.

### 1.3 Background image (mỗi trang)
**Format page → Canvas background → Browse →** chọn `powerbi/backgrounds/background.png` → **Image fit = Fit**, **Transparency = 0%**.
Ảnh chỉ là **lớp nền tĩnh** (header trắng + sidebar cyan + nền content). Mọi thứ tương tác (KPI, chart, nav, slicer, title) đặt **đè lên trên**.

> Copy background sang cả các trang: chuột phải tab trang → **Duplicate page** sau khi set nền để khỏi làm lại; hoặc lặp lại 1.1–1.3 cho từng trang.

### Bảng màu (để format tay khi cần)
| Vai trò | Hex |
|---|---|
| Primary (Revenue, bar chính) | `#0891B2` |
| Secondary (Profit, so sánh) | `#E0A82E` |
| Positive (completed/tốt) | `#2E8B4F` |
| Alert (failed/giảm/cost) | `#E5484D` |
| Neutral / slate | `#64748B` · Violet `#7C6BC4` |
| Text | `#1A2230` (chính) · `#6B7280` (phụ) · `#9AA3AF` (mờ) |
| Card / viền | `#FFFFFF` / `#E9EEF5` (radius 12) · Page `#F5F7FA` |

---

## 2. Kết nối dữ liệu & Data model

### 2.1 Get data (Import)
**Home → Get data → PostgreSQL** · Server `localhost:5432` · Database `ecommerce` · **Import**. Auth Database (user/pass trong `.env`).

Tick các bảng (tên hiển thị có prefix schema — sẽ đổi tên ở 2.2):
`marts_core`: `fact_order`, `fact_order_item`, `fact_refund`, `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `mart_customer_summary`, `dim_date`, `dim_site`, `dim_country`, `dim_product`, `dim_customer_anonymized`, `dim_payment_method`.

**Load** (không Transform — marts đã sạch).

> **Cố ý KHÔNG import `marts_operations.fact_order_cost`** (và cả `marts_recon.*`). Không phải bỏ sót:
> 1. **Thừa** — `cogs_usd` của nó ($61,088.36) khớp chính xác `mart_order_profit`; nó là nguồn upstream đã được `mart_order_profit` tổng hợp sẵn ở order grain. `cost_confidence` / `cost_allocation_method` cũng đã có trong `mart_order_profit`.
> 2. **Rủi ro** — nó chứa `csv_revenue_observed_usd`, `csv_profit_observed_usd`, `csv_shipping_charged_usd`. Theo `CLAUDE.md` rule #5, các số Revenue/Profit từ CSV **chỉ được dùng để theo dõi drift trong `marts_recon`**, tuyệt đối không làm metric chính thức. Đưa bảng này vào model là để sẵn cái bẫy kéo nhầm cột vào visual.
> 3. `marts_recon.*` phục vụ tier-gating của `BUILD_GUIDE.md` (bản MVP) — bản capstone không dùng gating.
>
> Nếu sau này cần trang data-quality, hãy import `marts_recon.recon_cost_coverage` **riêng** và chỉ dùng cột coverage, đừng import `fact_order_cost`.

### 2.2 Đổi tên bảng
Data pane → chuột phải mỗi bảng → **Rename** → bỏ prefix schema, còn `fact_order_item`, `dim_country`… (chữ thường, gạch dưới — DAX phân biệt hoa/thường).

### 2.3 Relationships (Model view) — tất cả **1:* , single direction, active**
| From (dim, one) | To (fact, many) | Key |
|---|---|---|
| dim_date | fact_order · fact_order_item · fact_refund · mart_order_profit · mart_product_profit · mart_country_profit | date_sk |
| dim_country | fact_order · mart_country_profit | country_sk |
| dim_product | fact_order_item · mart_product_profit | product_sk |
| dim_customer_anonymized | fact_order · mart_customer_summary | customer_sk |
| dim_site | fact_order · fact_order_item · mart_order_profit | site_sk |
| dim_payment_method | fact_order | payment_method_sk |

Nếu Power BI tự tạo quan hệ **Both** → sửa về **Single**. `mart_customer_summary[preferred_*_sk]` để **inactive**.

> ### ⚠️ 2.3b — Bảng nào cắt được theo chiều nào (ĐỌC KỸ, đây là nguồn lỗi số 1)
>
> Bảng chỉ cắt được theo dim mà nó **có quan hệ**. Nếu đặt measure lên một dim không có quan hệ, Power BI **không báo lỗi** — nó trả về **grand total giống hệt nhau cho mọi dòng**. Rất dễ tưởng là đúng.
>
> | Bảng | Cắt được theo | **KHÔNG** cắt được theo |
> |---|---|---|
> | `fact_order_item` | date · site · **product** | **country** · customer · payment method |
> | `fact_order` | date · site · **country** · customer · payment method | **product** |
> | `mart_order_profit` | date · site | **product** · **country** · customer |
> | `mart_product_profit` | date · site · **product** | country · customer |
> | `mart_country_profit` | date · **country** | product · site · customer |
> | `mart_customer_summary` | customer | date · product · country |
>
> **Ba hệ quả bắt buộc nhớ:**
> 1. `[Revenue]` (đọc `fact_order_item`) **không** cắt được theo country → mọi visual revenue-theo-nước phải dùng `[Revenue per Country]` (§3.6).
> 2. `[Contribution Profit]` / `[Profit Margin]` (đọc `mart_order_profit`) **không** cắt được theo product hay country → phải dùng bộ đo product (§3.5b) và country (§3.6).
> 3. Ngược lại, `[Revenue]` **cắt tốt** theo product (có quan hệ `fact_order_item → dim_product`), nên trang Products dùng `[Revenue]` bình thường.

### 2.4 Mark as date table
Chọn `dim_date` → **Table tools → Mark as date table** → cột `date_day` → OK. (Bật time-intelligence cho YoY.)

### 2.5 Ẩn cột kỹ thuật
Ẩn mọi cột `*_sk` (chuột phải → **Hide in report view**) cho gọn field list.

---

## 3. Measures & Calculated columns

### 3.0 Bảng nguồn chuẩn — metric nào đọc bảng nào (TRA TRƯỚC KHI DỰNG VISUAL)

Nguyên tắc thống nhất dữ liệu của model: **mỗi metric có đúng MỘT nguồn chuẩn; mọi visual đều đọc từ nguồn đó**. Các bảng fact/mart *cố ý* cho số khác nhau vì trả lời câu hỏi khác nhau (mart đã áp refund capping, payment-fee coalesce, và gồm đơn refunded trong P&L) — đừng "sửa" chênh lệch bằng cách đổi nguồn.

| Câu hỏi kinh doanh | Nguồn chuẩn DUY NHẤT | Measure | KHÔNG lấy từ |
|---|---|---|---|
| P&L: profit, margin, cost, fee | `mart_order_profit` (order) · `mart_product_profit` (product) · `mart_country_profit` (country) | `Contribution Profit` · `Profit Margin` · `Total Cost` · `COGS` · `Payment Fee` · `Product Profit` · `Country Profit`… | `fact_order[payment_fee_usd]` (thiếu fallback CSV, hụt $58.34) · CSV Revenue/Profit (rule #5) |
| Doanh thu gross sản phẩm | `fact_order_item` | `[Revenue]` · `[Revenue per Country]` (TREATAS) · `Quantity Sold` | `fact_order` (không có cột revenue — cố ý) · `mart_country_profit[revenue_usd]` (đó là NET) |
| Shipping khách trả (revenue-side) | `fact_order` | `Shipping Charged` | — (không tồn tại supplier shipping cost riêng) |
| Funnel vận hành: fail/cancel/backlog | `fact_order` (mọi status, 4,757) | `Order Attempts` · `Failed Rate` · `Cancellation Rate` · `Open Backlog` · `Payment Fee Rate` | mart (mart không chứa đơn failed/cancelled) |
| Refund health | `fact_refund` | `Refunded Orders` · `Refund Amount` | mart `effective_refund_usd` (đã cap — dùng cho P&L, không dùng cho KPI refund thô) |
| Khách hàng lifetime | `mart_customer_summary` | `Distinct Customers` · `Repeat Rate` · `Orders per Customer` · `Lapsed Share` | `fact_order` đếm khách theo filter context |

**3 quy tắc thực thi:**
1. **Không trộn 2 cơ sở trong 1 visual** — vd. không đặt `[Revenue]` cạnh `[Product Net Revenue]` trong cùng bảng mà không ghi chú cơ sở.
2. **Tử & mẫu cùng dân số** — mọi ratio chia cho `[Paid Orders]` (3,813, dân số mart) hoặc `[Order Attempts]` (4,757, funnel); margin/cost ratio luôn chia `[Profit Base Net Revenue]`.
3. **Nhãn đúng bản chất** — `mart_country_profit[revenue_usd]` là NET (gồm shipping), cấm dán nhãn "Revenue".

**Chênh lệch hợp lệ đã định lượng** (đừng hoảng khi thấy): `Paid Orders` 3,813 vs `Orders` 3,776 (mart gồm 37 đơn refunded; ecom lấy on-hold thay refunded) · Payment Fee $7,124.47 (mart) vs $6,986.75 (fact) · Refund $1,592.02 (thô) vs $1,582.49 (capped) · Revenue $119,261.71 (item) = $119,261.71 (mart — sau đợt làm sạch dữ liệu 2026-07-22 mart phủ **100%** đơn revenue, hết chênh coverage). Chi tiết: Phụ lục B.

Tạo bảng đo lường: **Home → Enter data →** đặt tên `_Measures` → Load → xóa cột dummy sau khi thêm measure đầu tiên. Mỗi measure: **New measure**, dán DAX, đặt **Format** ở ribbon.

### 3.1 Sales / Revenue
```DAX
Revenue = CALCULATE ( SUM ( fact_order_item[line_revenue_usd] ), fact_order_item[is_revenue_status] = TRUE() )      -- $#,0
Quantity Sold = CALCULATE ( SUM ( fact_order_item[quantity] ), fact_order_item[is_revenue_status] = TRUE() )         -- #,0
Net Revenue = [Revenue] - [Refund Amount]                                                                            -- $#,0  (net BÁO CÁO = gross − refund thực; [Refund Amount] định nghĩa ở §3.8)
Profit Base Net Revenue = SUM ( mart_order_profit[net_revenue_usd] )                                                 -- $#,0  (mẫu số MARGIN/COST = product + SHIPPING − refund, Approach A; khớp mart; KHÔNG dùng cho KPI hiển thị)
Paid Orders = DISTINCTCOUNT ( mart_order_profit[order_sk] )                                                          -- #,0
AOV = DIVIDE ( [Revenue], [Paid Orders] )                                                                            -- $#,0.00
Shipping Charged = SUM ( fact_order[shipping_charged_usd] )                                                          -- $#,0
```

### 3.2 Profit
```DAX
Contribution Profit = SUM ( mart_order_profit[contribution_profit_usd] )     -- $#,0
Profit Margin = DIVIDE ( [Contribution Profit], [Profit Base Net Revenue] )  -- 0.0%  (mẫu số = Profit Base, để khớp mart)
```

### 3.3 YoY (time-intelligence)
```DAX
Revenue PY = CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( dim_date[date_day] ) )
Revenue YoY % = DIVIDE ( [Revenue] - [Revenue PY], [Revenue PY] )                        -- 0.0%
Profit PY = CALCULATE ( [Contribution Profit], SAMEPERIODLASTYEAR ( dim_date[date_day] ) )
Profit YoY % = DIVIDE ( [Contribution Profit] - [Profit PY], [Profit PY] )               -- 0.0%
Orders PY = CALCULATE ( [Paid Orders], SAMEPERIODLASTYEAR ( dim_date[date_day] ) )
Orders YoY % = DIVIDE ( [Paid Orders] - [Orders PY], [Orders PY] )                        -- 0.0%
```

### 3.4 Cost
```DAX
COGS = SUM ( mart_order_profit[cogs_usd] )                          -- $#,0
Design Fee = SUM ( mart_order_profit[design_fee_usd] )              -- $#,0
Payment Fee = SUM ( mart_order_profit[payment_fee_usd] )            -- $#,0
Total Cost = [COGS] + [Design Fee] + [Payment Fee]                 -- $#,0
Cost Ratio = DIVIDE ( [Total Cost], [Profit Base Net Revenue] )    -- 0.0%  (mẫu số = Profit Base)
COGS Ratio = DIVIDE ( [COGS], [Profit Base Net Revenue] )          -- 0.0%  (mẫu số = Profit Base)
Cost per Order = DIVIDE ( [Total Cost], [Paid Orders] )            -- $#,0.00
Cost per Unit = DIVIDE ( [Total Cost], [Quantity Sold] )           -- $#,0.00
```

### 3.5 Products
```DAX
Distinct Products Sold = CALCULATE ( DISTINCTCOUNT ( fact_order_item[product_sk] ), fact_order_item[is_revenue_status] = TRUE() )   -- #,0
Avg Units per Order = DIVIDE ( [Quantity Sold], [Paid Orders] )     -- #,0.00

-- Pareto (đặt trên visual có dim_product[product_name])
Cumulative Revenue =
VAR cur = [Revenue]
RETURN CALCULATE ( [Revenue], FILTER ( ALLSELECTED ( dim_product[product_name] ), [Revenue] >= cur ) )
Cumulative Revenue % = DIVIDE ( [Cumulative Revenue], CALCULATE ( [Revenue], ALLSELECTED ( dim_product[product_name] ) ) )   -- 0.0%
```

### 3.5b Profit theo SẢN PHẨM — BẮT BUỘC dùng bộ này
`[Contribution Profit]` đọc `mart_order_profit`, bảng này **không nối `dim_product`** (§2.3b). Đặt nó lên visual có `dim_product` sẽ ra **grand total cho mọi sản phẩm**. Dùng `mart_product_profit` — mart này có `product_sk` và cộng lại đúng bằng $86,850.01.

```DAX
Product Profit     = SUM ( mart_product_profit[line_profit_usd] )        -- $#,0
Product Net Revenue = SUM ( mart_product_profit[line_net_revenue_usd] )  -- $#,0  (mẫu số margin sản phẩm)
Product Margin     = DIVIDE ( [Product Profit], [Product Net Revenue] )  -- 0.0%
```
> `[Revenue]` **vẫn dùng được** trên trang Products (có quan hệ `fact_order_item → dim_product`). Chỉ *profit* mới phải đổi sang bộ trên.
> Lưu ý cơ sở số: `SUM(mart_product_profit[line_revenue_usd])` = **$119,261.71** = `[Revenue]` **chính xác** — sau đợt làm sạch dữ liệu 2026-07-22, `mart_order_profit` phủ 100% đơn revenue nên hai cơ sở đã trùng nhau. Vẫn đừng trộn hai bộ measure trong cùng một bảng (khác grain, khác nguồn).

### 3.6 Markets — BẮT BUỘC dùng bộ này
Cả `[Revenue]` (đọc `fact_order_item`) lẫn `[Contribution Profit]` (đọc `mart_order_profit`) **đều không cắt được theo country** (§2.3b). Có 2 cách, dùng đúng cách cho đúng mục đích:

```DAX
-- (a) Gross product revenue theo nước — chuyển filter nước từ fact_order sang fact_order_item qua order_sk
Revenue per Country =
CALCULATE ( [Revenue], TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] ) )   -- $#,0

-- (b) Profit / margin theo nước — đọc thẳng mart_country_profit (có quan hệ dim_country)
Country Profit      = SUM ( mart_country_profit[contribution_profit_usd] )   -- $#,0
Country Net Revenue = SUM ( mart_country_profit[revenue_usd] )               -- $#,0
Country Margin      = DIVIDE ( [Country Profit], [Country Net Revenue] )     -- 0.0%
Country Orders      = SUM ( mart_country_profit[order_count] )               -- #,0

Revenue Share = DIVIDE ( [Revenue per Country], CALCULATE ( [Revenue per Country], ALLSELECTED ( dim_country[country_name] ) ) )   -- 0.0%
```
> ⚠️ **Bẫy đặt tên:** `mart_country_profit[revenue_usd]` **KHÔNG phải gross revenue** — nó là **net revenue đã gồm shipping** (tổng = $157,614.83, đúng bằng `[Profit Base Net Revenue]`). Đừng bao giờ gắn nhãn "Revenue" cho nó trên visual; muốn hiện doanh thu gross theo nước thì dùng `[Revenue per Country]`.

### 3.7 Customers
```DAX
Distinct Customers = DISTINCTCOUNT ( mart_customer_summary[customer_sk] )     -- #,0
Repeat Customers = CALCULATE ( COUNTROWS ( mart_customer_summary ), mart_customer_summary[is_repeat] = TRUE() )
Repeat Rate = DIVIDE ( [Repeat Customers], [Distinct Customers] )             -- 0.0%
One-time Share = 1 - [Repeat Rate]                                           -- 0.0%
Orders per Customer = DIVIDE ( SUM ( mart_customer_summary[total_orders] ), [Distinct Customers] )   -- #,0.00
New Customers = DISTINCTCOUNT ( mart_customer_summary[customer_sk] )          -- #,0  (dùng với first_order_date trên trục)
Lapsed Share = DIVIDE ( CALCULATE ( COUNTROWS ( mart_customer_summary ), mart_customer_summary[Recency Segment] = "Lapsed 12+mo" ), [Distinct Customers] )   -- 0.0%
```
**Calculated columns** trên `mart_customer_summary` (Table tools → New column):
```DAX
Days Since Last Order =
DATEDIFF (
    mart_customer_summary[last_order_date],
    CALCULATE ( MAX ( mart_customer_summary[last_order_date] ), ALL ( mart_customer_summary ) ),
    DAY )
-- Neo động = ngày đơn mới nhất trong bảng (hiện là 2026-07-14), tự đúng sau mỗi refresh.
-- KHÔNG hardcode DATE(2026,7,14): sẽ âm thầm stale khi có đơn mới → Recency Segment / Lapsed Share sai dần.
Recency Segment =
SWITCH ( TRUE(),
    mart_customer_summary[Days Since Last Order] < 90,  "Active 0-3mo",
    mart_customer_summary[Days Since Last Order] < 180, "3-6 mo",
    mart_customer_summary[Days Since Last Order] < 365, "6-12 mo",
    "Lapsed 12+mo" )
CLV Bucket =
SWITCH ( TRUE(),
    mart_customer_summary[total_revenue_usd] < 20,  "1. <$20",
    mart_customer_summary[total_revenue_usd] < 40,  "2. $20-40",
    mart_customer_summary[total_revenue_usd] < 75,  "3. $40-75",
    mart_customer_summary[total_revenue_usd] < 150, "4. $75-150",
    "5. $150+" )
```

### 3.8 Operations
```DAX
Order Attempts = COUNTROWS ( fact_order )                                                       -- #,0
Completed Orders = CALCULATE ( COUNTROWS ( fact_order ), fact_order[status] = "completed" )
Failed Orders    = CALCULATE ( COUNTROWS ( fact_order ), fact_order[status] = "failed" )
Cancelled Orders = CALCULATE ( COUNTROWS ( fact_order ), fact_order[status] = "cancelled" )
Open Backlog     = CALCULATE ( COUNTROWS ( fact_order ), fact_order[status] = "processing" )     -- #,0
Paid Success Rate  = DIVIDE ( [Paid Orders], [Order Attempts] )                                  -- 0.0%
Failed Rate        = DIVIDE ( [Failed Orders], [Order Attempts] )                                -- 0.0%
Cancellation Rate  = DIVIDE ( [Cancelled Orders], [Order Attempts] )                             -- 0.0%
Refunded Orders = DISTINCTCOUNT ( fact_refund[order_sk] )                                        -- #,0
Refund Amount   = SUM ( fact_refund[refund_amount_usd] )                                         -- $#,0
Refund Rate     = DIVIDE ( [Refunded Orders], [Paid Orders] )                                    -- 0.0%
Payment Fee Rate = DIVIDE ( SUM ( fact_order[payment_fee_usd] ), SUM ( fact_order[order_total_usd] ) )   -- 0.0%
```

> Kiểm chứng nhanh (all-time, **Approach A** — shipping là revenue; verify lại trên DB + model 2026-07-22 sau đợt làm sạch dữ liệu): Revenue (gross, product) = **$119,261.71** · Refund Amount = **$1,592.02** · Net Revenue §A2 (product) = **$117,669.69** · Shipping Charged (mọi đơn) = **$50,648.98** · Profit Base Net Revenue (mart, product+shipping−refund) = **$157,614.83** · Contribution Profit = **$86,850.01** · Margin **55.1%** · Paid Orders **3,813** · AOV **$31.28** · Total Cost **$70,764.82** · Cost Ratio **44.9%** · COGS Ratio **38.8%** · Cost per Order **$18.56** · Cost per Unit **$16.42** · Paid Success Rate **80.2%** · Distinct Customers **4,266** · Repeat Rate **9.0%** · Orders per Customer **1.12**.
>
> Chênh giữa Profit Base (**$157,614.83**) và Net Revenue §A2 (**$117,669.69**) = **$39,945.14**, gồm: **phần shipping khách trả** trên các đơn revenue (**+$39,935.60**) và **+$9.53** refund cap (mart trừ `effective_refund_usd` = $1,582.49, thấp hơn refund thô `[Refund Amount]` = $1,592.02 vì cap tại gross của từng đơn). Chênh coverage đã về **$0** — mart phủ 100% đơn revenue từ 2026-07-22. Approach A đưa shipping vào doanh thu — xem `docs/METRIC_CHANGES.md` 2026-07-21. Trước Approach A profit chỉ ≈ $47,536 (thiếu shipping).
>
> **Vì sao `Paid Orders` = 3,813 chứ không phải 3,776?** `mart_order_profit` gồm **completed 3,697 + processing 79 + refunded 37**. Nó **không** trùng với "đơn revenue-status theo `fact_order`" (processing/completed/on-hold = **3,776**) — đó là measure `[Orders]` của project ecom. Hai con số đều đúng, chỉ khác dân số; capstone dùng `[Paid Orders]` để mọi tỉ lệ chi phí/lợi nhuận ăn khớp với `mart_order_profit`.
>
> **Quy tắc:** `[Net Revenue]` (= Revenue product − Refund thô) chỉ dùng cho **thẻ KPI hiển thị sales**; mọi **margin & cost ratio** dùng `[Profit Base Net Revenue]` (mart = product + shipping − refund) để khớp `Contribution Profit`. Page 1 KPI "Net Revenue" và "Revenue by year" → `[Net Revenue]`; Page 2 các ratio → `[Profit Base Net Revenue]`.

---

## 4. Khung chung mọi trang (đặt lên background)

### 4.1 Sidebar navigation (6 nút)
Đặt **Buttons** (Insert → Buttons → Blank) chồng lên vùng nav pill của background:
- Mỗi nút: **Action = Page navigation → Destination = trang tương ứng.** Fill trong suốt, Text = tên trang (Overview…Operations), hoặc dùng **Insert → Buttons → Navigator → Page navigator** để tự sinh + tự highlight trang hiện tại.

### 4.2 Header
- **Text box** tiêu đề trang (ví dụ "Executive Overview") đặt ở header trái. Font Segoe UI Semibold ~22.
- **Slicer Date**: field `dim_date[date_day]`, kiểu **Between**, đặt ở header phải (đè lên 2 ô date-picker của background). **View → Sync slicers →** tick tất cả trang.

### 4.3 Filters (global)
- **Slicer** `dim_country[country_name]` (hoặc `dim_country[region]`) — style Dropdown — đặt ở vùng "Market" trong sidebar.
- **Slicer** `fact_order_item[fit_type]` — style Tile/Horizontal — vùng "Fit type".
- Cả hai: **Sync slicers** bật cho mọi trang.

---

## 5. Build từng trang

Ký hiệu: **Card** = card visual (New card) · **Axis/Values/Legend** = field wells. KPI dùng card, mỗi card 1 measure; delta YoY để ở supporting/label hoặc card phụ.

### PAGE 1 — Overview
**KPI (6 card, hàng trên):** Revenue (+ Revenue YoY %) · Contribution Profit (+ Profit YoY %) · Profit Margin · Paid Orders (+ Orders YoY %) · AOV · Repeat Rate.

| Visual | Loại | Field |
|---|---|---|
| Revenue & Profit theo tháng | **Line chart** | Axis `dim_date[Month]` (hierarchy, cấp Month) · Values `[Revenue]`, `[Contribution Profit]` |
| Revenue theo năm | **Clustered column** | Axis `dim_date[Year]` · Values `[Net Revenue]`, `[Contribution Profit]` |
| Top markets | **Clustered bar** | Axis `dim_country[country_name]` · Values **`[Revenue per Country]`** (§3.6 — `[Revenue]` sẽ ra grand total cho mọi nước) · Filter Top N = 10 by `[Revenue per Country]` |
| Revenue → Profit bridge | **Waterfall** | Category = 1 field trục "breakdown"; đơn giản nhất: dùng **Waterfall** với Category `dim_date` **hoặc** tạo bảng phụ. *Cách dễ:* dùng 1 **Stacked/Clustered** thể hiện Net Rev, −COGS, −Design, −Pmt fee, Profit qua bảng disconnected (xem ghi chú dưới). |

> **Waterfall gọn:** tạo bảng disconnected `Bridge` (Enter data) với cột `Step` = {Net rev, COGS, Design, Pmt fee, Profit} và `Order` 1..5; measure `Bridge Value = SWITCH(SELECTEDVALUE(Bridge[Step]), "Net rev",[Profit Base Net Revenue], "COGS",-[COGS], "Design",-[Design Fee], "Pmt fee",-[Payment Fee], "Profit",[Contribution Profit])`. Waterfall: Category `Bridge[Step]` (sort theo `Order`), Y `[Bridge Value]`.
>
> ⚠️ Bước khởi đầu **bắt buộc** là `[Profit Base Net Revenue]` (product + shipping − refund, $157,614.83) — đúng cơ sở mà `[Contribution Profit]` trừ chi phí. Dùng `[Net Revenue]` (product-only, $117,669.69) sẽ làm waterfall **không cân**: 117,670 − 70,765 = $46,905 ≠ $86,850 (lệch ~$39,945 = phần shipping, tàn dư pre-Approach-A). Kiểm chứng: 157,614.83 − 61,088.36 − 2,551.99 − 7,124.47 = **86,850.01** ✓.

### PAGE 2 — Cost & Margin
**KPI (5 card):** Total Cost · Cost Ratio · COGS Ratio · Cost per Order (+ Cost per Unit ở label) · Profit Margin.

| Visual | Loại | Field |
|---|---|---|
| Cost structure | **Clustered bar** | Axis = bảng phụ `CostType` (Enter data: COGS/Payment fee/Design) hoặc 3 card; Values measure tương ứng. Đơn giản: bar ngang với 3 measure `[COGS]`,`[Payment Fee]`,`[Design Fee]` qua "values" của multi-row/bar. |
| Margin & COGS ratio theo tháng | **Line chart** | Axis `dim_date[Month]` · Values `[Profit Margin]`, `[COGS Ratio]` |
| Lowest-margin products | **Table** | Rows `dim_product[product_name]` · Values `[Revenue]`, **`[Product Profit]`**, **`[Product Margin]`** (§3.5b — `[Contribution Profit]`/`[Profit Margin]` sẽ ra grand total cho mọi sản phẩm) · Sort tăng theo `[Product Margin]`, filter `[Revenue] > 300`, Top 8 |

### PAGE 3 — Products
**KPI (4 card):** Distinct Products Sold · (top-11%→50% là insight, ghi text) · Front-print share · Men's fit share.

| Visual | Loại | Field |
|---|---|---|
| Pareto concentration | **Line + column** hoặc Line | Axis `dim_product[product_name]` sort desc theo `[Revenue]` · Line `[Cumulative Revenue %]` (Top ~100 hoặc all). Thêm 2 constant line ở 50% & 80%. |
| Top products by profit | **Table** | Rows `dim_product[product_name]` · Values `[Revenue]`, **`[Product Profit]`**, **`[Product Margin]`** (§3.5b) · Top 8 by `[Product Profit]` |
| Revenue by print location | **Bar** | Axis `fact_order_item[print_location]` · Values `[Revenue]` |
| Revenue by size | **Column** | Axis `fact_order_item[size]` · Values `[Revenue]` (sort S→5XL bằng sort column) |
| Revenue by fit type | **Donut** | Legend `fact_order_item[fit_type]` · Values `[Revenue]` |

### PAGE 4 — Markets
**KPI (4 card):** Top market (text/card lớn) · Best-margin market · International share · Markets served (`DISTINCTCOUNT(dim_country[country_name])`).

| Visual | Loại | Field |
|---|---|---|
| Revenue map | **Filled/Bubble map** | Location `dim_country[country_name]` · Bubble size **`[Revenue per Country]`** · Color saturation **`[Country Margin]`** |
| Revenue vs margin | **Line and clustered column** | Shared axis `dim_country[country_name]` (Top 8) · Column **`[Revenue per Country]`** · Line **`[Country Margin]`** |
| Market detail (drill source) | **Table** | Rows `dim_country[country_name]` · Values **`[Country Orders]`**, **`[Revenue per Country]`**, **`[AOV per Country]`**, **`[Country Margin]`**, `[Revenue Share]` |

> ⚠️ **Cả trang này KHÔNG được dùng `[Revenue]`, `[Contribution Profit]`, `[Profit Margin]`, `[Paid Orders]` trực tiếp** — không bảng nào trong số đó cắt được theo country (§2.3b), Power BI sẽ im lặng trả grand total giống nhau cho mọi nước. Dùng bộ `*per Country* / Country *` ở §3.6.
>
> AOV theo nước cần mẫu số cùng dân số với tử số:
> ```DAX
> AOV per Country = DIVIDE ( [Revenue per Country], [Country Orders] )   -- $#,0.00
> ```

### PAGE 5 — Customers
**KPI (4 card):** Distinct Customers · One-time Share · Orders per Customer · Lapsed Share.

| Visual | Loại | Field |
|---|---|---|
| New customers / tháng | **Column** | Axis `mart_customer_summary[first_order_date]` (cấp Month) · Values `[New Customers]` |
| Customer recency | **Bar** | Axis `mart_customer_summary[Recency Segment]` · Values `[Distinct Customers]` (màu semantic: Active green → Lapsed red) |
| Orders per customer | **Column** | Axis `mart_customer_summary[total_orders]` · Values `Count of customer_sk` |
| Customer value distribution | **Column** | Axis `mart_customer_summary[CLV Bucket]` · Values `Count of customer_sk` |

### PAGE 6 — Operations
**KPI (5 card):** Paid Success Rate · Failed Rate · Cancellation Rate · Open Backlog · Refund Rate.

| Visual | Loại | Field |
|---|---|---|
| Order status breakdown | **Bar** | Axis `fact_order[status]` · Values `[Order Attempts]` (Count) · màu theo status (completed green, failed red, cancelled sand…) qua "colors" từng data point |
| Status theo tháng | **Stacked column** | Axis `dim_date[Month]` · Values Completed/Failed/Cancelled — dùng `fact_order[status]` làm Legend + `[Order Attempts]` |
| Payment method & fee | **Table/Bar** | Rows `dim_payment_method[method_name]` · Values Count orders, `[Payment Fee Rate]`, `[Payment Fee]` |
| Refund health | **Card + table** | Cards `[Refund Rate]`,`[Refunded Orders]`,`[Refund Amount]`; table `fact_refund[refund_reason]` × count |

---

## 6. Custom Tooltip (hover ra chi tiết)

**Trang tooltip "Month":**
1. Trang mới → **Format → Page information → Allow use as tooltip = On** → **Page size → Type = Tooltip**.
2. Đặt vài card nhỏ: `[Revenue]`, `[Contribution Profit]`, `[Profit Margin]`, `[Paid Orders]` (bối cảnh sẽ tự lọc theo tháng đang hover).
3. Ở **Line chart Page 1** → **Format → Tooltips → Type = Report page → Page = Month.**

**Trang tooltip "Market"** (tương tự): cards **`[Country Orders]`**, **`[AOV per Country]`**, **`[Country Margin]`** (bộ country §3.6 — tooltip cũng chịu chung ràng buộc quan hệ) và `[Revenue per Country]`; gán cho map/bar/table ở Page 4. Bỏ `[Refund Rate]` khỏi tooltip này: `fact_refund` không nối `dim_country` nên nó sẽ ra tỉ lệ toàn hệ thống cho mọi nước.

---

## 7. Drill-through — Market detail

1. Tạo trang **Market Detail** (1920×1080, cùng background).
2. Kéo `dim_country[country_name]` vào **Visualizations → Add drill-through fields here** (mục *Drill through*).
3. Trên trang này đặt: header tên nước (card/text `SELECTEDVALUE(dim_country[country_name])`), KPI (**`[Revenue per Country]`**, **`[Country Orders]`**, **`[AOV per Country]`**, **`[Country Margin]`**, `[Revenue Share]` — bộ country ở §3.6, KHÔNG dùng `[Revenue]`/`[Profit Margin]`), line **revenue theo tháng** (dùng `[Revenue per Country]`), donut **payment mix** (`dim_payment_method[method_name]` × count).
4. Power BI tự thêm nút **Back** (chuột phải nút → giữ). Trên Page 4, **chuột phải** 1 nước (table/map/bar) → **Drill through → Market Detail**.

---

## 8. Bookmarks

**View → Bookmarks + Selection.**

- **Measure toggle (Rev+Profit ↔ Orders)** trên line Page 1:
  1. Tạo 2 line chart chồng lên nhau cùng vị trí: chart A (`[Revenue]`,`[Contribution Profit]`), chart B (`[Paid Orders]`).
  2. Selection pane: bookmark **"Rev+Profit"** = hiện A / ẩn B; bookmark **"Orders"** = ẩn A / hiện B (mỗi bookmark chỉ tick *Data* + *Display*, bỏ *Current page*).
  3. Insert 2 **Buttons** "Rev+Profit" / "Orders" → **Action = Bookmark**.
- **Reset filters:** clear mọi slicer về mặc định → **Add bookmark "Reset"** → nút Action = Bookmark đó.
- (Tùy chọn) **Insight panel** trượt ra: 1 shape/panel + Selection pane show/hide qua 2 bookmark.

---

## 9. Hoàn thiện & lưu

- Duyệt lại: mọi visual để **title** rõ, format số đúng (§3), màu khớp bảng màu §1.
- Ẩn các trang phụ trợ (Month/Market tooltip, Market Detail) khỏi tab nếu cần: chuột phải tab → **Hide page** (drill-through vẫn hoạt động khi ẩn).
- **File → Save as →** `powerbi/ecommerce_analytics.pbix` (hoặc bản .pbip).
- Chụp screenshot mỗi trang → `powerbi/screenshots/`.

---

## Phụ lục A — Index measure nhanh
Sales: Revenue · Quantity Sold · Net Revenue · Profit Base Net Revenue · Paid Orders · AOV · Shipping Charged
Profit: Contribution Profit · Profit Margin · (YoY: Revenue/Profit/Orders YoY %)
Cost: COGS · Design Fee · Payment Fee · Total Cost · Cost Ratio · COGS Ratio · Cost per Order · Cost per Unit
Products: Distinct Products Sold · Avg Units per Order · Cumulative Revenue % · **Product Profit · Product Net Revenue · Product Margin**
Markets: **Revenue per Country · Country Profit · Country Net Revenue · Country Margin · Country Orders · AOV per Country** · Revenue Share
Customers: Distinct Customers · Repeat Rate · One-time Share · Orders per Customer · New Customers · Lapsed Share (+ cột Recency Segment, CLV Bucket, Days Since Last Order)
Operations: Order Attempts · Completed/Failed/Cancelled Orders · Open Backlog · Paid Success Rate · Failed Rate · Cancellation Rate · Refunded Orders · Refund Amount · Refund Rate · Payment Fee Rate

---

## Phụ lục B — Đối chiếu với project ecom (`powerbi/measures/dax_measures.txt`)

Capstone **cố ý giữ tên riêng**. Bảng này để khi bạn đọc doc ecom (`docs/METRICS_DEFINITION.md`) không bị lẫn. Hai bộ đo **không thay thế được cho nhau** ở những dòng đánh dấu ⚠️.

| Capstone | ecom | Quan hệ |
|---|---|---|
| `Paid Orders` = 3,813 | `Orders` = 3,776 | ⚠️ **Khác dân số.** Capstone đếm đơn có trong `mart_order_profit` (completed + processing + **refunded**); ecom đếm `fact_order` status ∈ {processing, completed, on-hold}. |
| `Shipping Charged` | `Shipping Charged to Customer` | Chỉ khác tên, cùng công thức. |
| `Open Backlog` (COUNTROWS) | `Open Order Backlog` (DISTINCTCOUNT) | Cùng giá trị (79). |
| `Refunded Orders` = DISTINCTCOUNT | `Refunded Order Count` = COUNTROWS | Hiện cùng = 37 (khớp 37 đơn status refunded sau đợt làm sạch 2026-07-22). Bản capstone **bền hơn** nếu 1 đơn có nhiều dòng refund — chính là cải tiến mà ecom đã ghi chú `// REVIEW (LOW)`. |
| `Refund Rate` = Refunded / Paid Orders | `Refund Rate` = (Refunded ∪ Cancelled) / Eligible Orders | ⚠️ **Khác hẳn ngữ nghĩa.** Capstone đo *sức khoẻ hoàn tiền* (1.0%); ecom đo *tỉ lệ đơn hỏng* gồm cả huỷ. Cancellation tách riêng ở capstone. |
| `Cancellation Rate` (÷ Order Attempts) | `Cancellation Rate` (÷ Eligible Orders) | ⚠️ Khác mẫu số. Capstone lấy mọi lần thử đặt hàng để 3 tỉ lệ ops (paid/failed/cancel) cộng lại có nghĩa. |
| `Distinct Customers` = 4,266 | `Distinct Customers` ≈ 4,263 (số lịch sử) | ⚠️ ecom lọc `is_unknown_email = FALSE()`. Capstone lấy toàn bộ `mart_customer_summary`. |
| `Repeat Rate` | `Repeat Customer Share` | Cùng công thức, khác tên. |
| `Orders per Customer` = 1.12 | `Orders per Customer` = 0.89 | ⚠️ Capstone = `SUM(total_orders)/customers` (lifetime, đúng cho trang Customers). ecom = `[Orders]/[Distinct Customers]` (theo filter context). |
| `Payment Fee` (mart_order_profit) = $7,124.47 | `Payment Fee` (fact_order) = $6,986.75 | ⚠️ **Capstone đúng hơn cho P&L:** `[Contribution Profit]` trừ đúng cột của `mart_order_profit` (đã COALESCE CSV fallback cho fee Woo thiếu), nên bản ecom không reconcile được (lệch $137.72 trên cùng tập đơn). |
| `Product Profit` / `Product Margin` | — | Capstone-only, bắt buộc vì `mart_order_profit` không nối `dim_product`. |
| `Revenue per Country` | `Revenue per Country` | **Giống nhau** — cùng dùng `TREATAS`, cùng lý do (§2.3b). |
| `Country Margin` | — | Capstone-only; ecom chưa có measure margin theo nước. |
| `Total Cost` / `Cost Ratio` / `Cost per Order` / `Cost per Unit` | — | Capstone-only (trang Cost & Margin). |
| — | Coverage Tier · Profit Visible Flag · các chip gating | ecom-only: capstone **không dùng tier-gating** (đã nêu ở đầu file). |

**Bất biến dùng chung cho cả hai** (`CLAUDE.md` rule #1–#6): revenue sản phẩm sống ở `fact_order_item[line_revenue_usd]`, shipping khách trả sống ở `fact_order[shipping_charged_usd]` và **được tính là doanh thu**; `cogs_usd` là chi phí fulfil all-in (đã gồm phí ship của nhà cung cấp) nên **không bao giờ trừ shipping như một khoản chi phí**; **không tồn tại** `actual_shipping_cost_usd`; mẫu số margin luôn là `[Profit Base Net Revenue]`.
