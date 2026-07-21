# FOS Analytics — Capstone Dashboard Build Guide

Hướng dẫn dựng **dashboard vận hành FOS** trong Power BI Desktop, khớp 1-1 với artifact demo (6 trang, theme cyan/sand, tooltip + bookmark + drill-through).

> ⚠️ Đây là guide cho **bản capstone operational** (6 trang, business-question driven, không gating/caveat). Nó **khác** `BUILD_GUIDE.md` (bản MVP gốc của project với 5 trang + tier-gating). Dùng đúng file cho đúng mục tiêu.

**Deliverables đi kèm:**
- Theme: `powerbi/themes/fos_dashboard_theme.json`
- Background canvas: `powerbi/backgrounds/fos_canvas_1920x1080.png`

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
**Format page → Canvas background → Browse →** chọn `fos_canvas_1920x1080.png` → **Image fit = Fit**, **Transparency = 0%**.
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

### 2.4 Mark as date table
Chọn `dim_date` → **Table tools → Mark as date table** → cột `date_day` → OK. (Bật time-intelligence cho YoY.)

### 2.5 Ẩn cột kỹ thuật
Ẩn mọi cột `*_sk` (chuột phải → **Hide in report view**) cho gọn field list.

---

## 3. Measures & Calculated columns

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

### 3.6 Markets
```DAX
Revenue Share = DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALLSELECTED ( dim_country[country_name] ) ) )   -- 0.0%
```

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
Days Since Last Order = DATEDIFF ( mart_customer_summary[last_order_date], DATE ( 2026, 7, 14 ), DAY )   -- 2026-07-14 = ngày cuối dữ liệu; cập nhật khi refresh
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

> Kiểm chứng nhanh (all-time, **Approach A** — shipping là revenue): Revenue (gross, product) ≈ **$119,377** · Refund Amount ≈ **$1,466** · Net Revenue §A2 (product) ≈ **$117,911** · Shipping Charged ≈ **$50,649** · Profit Base Net Revenue (mart, product+shipping−refund) ≈ **$157,883** · Contribution Profit ≈ **$87,138** · Margin **55.2%** · Paid Orders **3,815** · Cost Ratio **44.8%** · COGS Ratio **38.7%** · Paid Success Rate **80.2%** · Distinct Customers **4,266**.
>
> Chênh giữa Profit Base (**$157,883**) và Net Revenue §A2 (**$117,911**) ≈ **$39,972** chính là **phần shipping khách trả** (Approach A đưa vào doanh thu, xem `docs/METRIC_CHANGES.md` 2026-07-21). Trước Approach A profit chỉ ≈ $47,536 (thiếu shipping).
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
| Top markets | **Clustered bar** | Axis `dim_country[country_name]` · Values `[Revenue]` · Filter Top N = 10 by `[Revenue]` |
| Revenue → Profit bridge | **Waterfall** | Category = 1 field trục "breakdown"; đơn giản nhất: dùng **Waterfall** với Category `dim_date` **hoặc** tạo bảng phụ. *Cách dễ:* dùng 1 **Stacked/Clustered** thể hiện Net Rev, −COGS, −Design, −Pmt fee, Profit qua bảng disconnected (xem ghi chú dưới). |

> **Waterfall gọn:** tạo bảng disconnected `Bridge` (Enter data) với cột `Step` = {Net rev, COGS, Design, Pmt fee, Profit} và `Order` 1..5; measure `Bridge Value = SWITCH(SELECTEDVALUE(Bridge[Step]), "Net rev",[Net Revenue], "COGS",-[COGS], "Design",-[Design Fee], "Pmt fee",-[Payment Fee], "Profit",[Contribution Profit])`. Waterfall: Category `Bridge[Step]` (sort theo `Order`), Y `[Bridge Value]`.

### PAGE 2 — Cost & Margin
**KPI (5 card):** Total Cost · Cost Ratio · COGS Ratio · Cost per Order (+ Cost per Unit ở label) · Profit Margin.

| Visual | Loại | Field |
|---|---|---|
| Cost structure | **Clustered bar** | Axis = bảng phụ `CostType` (Enter data: COGS/Payment fee/Design) hoặc 3 card; Values measure tương ứng. Đơn giản: bar ngang với 3 measure `[COGS]`,`[Payment Fee]`,`[Design Fee]` qua "values" của multi-row/bar. |
| Margin & COGS ratio theo tháng | **Line chart** | Axis `dim_date[Month]` · Values `[Profit Margin]`, `[COGS Ratio]` |
| Lowest-margin products | **Table** | Rows `dim_product[product_name]` · Values `[Revenue]`, `[Contribution Profit]`, `[Profit Margin]` · Sort tăng theo `[Profit Margin]`, filter `[Revenue] > 300`, Top 8 |

### PAGE 3 — Products
**KPI (4 card):** Distinct Products Sold · (top-11%→50% là insight, ghi text) · Front-print share · Men's fit share.

| Visual | Loại | Field |
|---|---|---|
| Pareto concentration | **Line + column** hoặc Line | Axis `dim_product[product_name]` sort desc theo `[Revenue]` · Line `[Cumulative Revenue %]` (Top ~100 hoặc all). Thêm 2 constant line ở 50% & 80%. |
| Top products by profit | **Table** | Rows `dim_product[product_name]` · Values `[Revenue]`,`[Contribution Profit]`,`[Profit Margin]` · Top 8 by `[Contribution Profit]` |
| Revenue by print location | **Bar** | Axis `fact_order_item[print_location]` · Values `[Revenue]` |
| Revenue by size | **Column** | Axis `fact_order_item[size]` · Values `[Revenue]` (sort S→5XL bằng sort column) |
| Revenue by fit type | **Donut** | Legend `fact_order_item[fit_type]` · Values `[Revenue]` |

### PAGE 4 — Markets
**KPI (4 card):** Top market (text/card lớn) · Best-margin market · International share · Markets served (`DISTINCTCOUNT(dim_country[country_name])`).

| Visual | Loại | Field |
|---|---|---|
| Revenue map | **Filled/Bubble map** | Location `dim_country[country_name]` · Bubble size `[Revenue]` · Color saturation `[Profit Margin]` |
| Revenue vs margin | **Line and clustered column** | Shared axis `dim_country[country_name]` (Top 8) · Column `[Revenue]` · Line `[Profit Margin]` |
| Market detail (drill source) | **Table** | Rows `dim_country[country_name]` · Values `[Paid Orders]`,`[Revenue]`,`[AOV]`,`[Profit Margin]`,`[Revenue Share]` |

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

**Trang tooltip "Market"** (tương tự): cards `[Paid Orders]`,`[AOV]`,`[Profit Margin]`,`[Refund Rate]`; gán cho map/bar/table ở Page 4.

---

## 7. Drill-through — Market detail

1. Tạo trang **Market Detail** (1920×1080, cùng background).
2. Kéo `dim_country[country_name]` vào **Visualizations → Add drill-through fields here** (mục *Drill through*).
3. Trên trang này đặt: header tên nước (card/text `SELECTEDVALUE(dim_country[country_name])`), KPI (`[Revenue]`,`[Paid Orders]`,`[AOV]`,`[Profit Margin]`,`[Revenue Share]`), line **revenue theo tháng**, donut **payment mix** (`dim_payment_method[method_name]` × count).
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

## Phụ lục — Index measure nhanh
Sales: Revenue · Quantity Sold · Net Revenue · Paid Orders · AOV · Shipping Charged
Profit: Contribution Profit · Profit Margin · (YoY: Revenue/Profit/Orders YoY %)
Cost: COGS · Design Fee · Payment Fee · Total Cost · Cost Ratio · COGS Ratio · Cost per Order · Cost per Unit
Products: Distinct Products Sold · Avg Units per Order · Cumulative Revenue % 
Markets: Revenue Share
Customers: Distinct Customers · Repeat Rate · One-time Share · Orders per Customer · New Customers · Lapsed Share (+ cột Recency Segment, CLV Bucket, Days Since Last Order)
Operations: Order Attempts · Completed/Failed/Cancelled Orders · Open Backlog · Paid Success Rate · Failed Rate · Cancellation Rate · Refunded Orders · Refund Amount · Refund Rate · Payment Fee Rate
