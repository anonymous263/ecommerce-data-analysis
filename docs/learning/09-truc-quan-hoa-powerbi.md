# 09 — Trực quan hóa Power BI

## Vì sao chương này tồn tại

Đến Phase 4, `marts_core`/`marts_operations`/`marts_recon` đã là dữ liệu sạch,
đã được kiểm định (chương 08). Nhưng dữ liệu sạch trong Postgres không tự động
thành dashboard đáng tin — cần một lớp **semantic model** (mô hình ngữ nghĩa)
biến các bảng phẳng thành quan hệ có ý nghĩa, và một lớp **DAX measure** biến cột
dữ liệu thành phép tính kinh doanh. Chương này giải thích cách `powerbi/BUILD_GUIDE.md`
và `powerbi/measures/dax_measures.txt` làm hai việc đó, và cách gating (chương 08)
được **thực thi thật** trên dashboard bằng measure — không phải bằng tay.

## 1. Semantic model: import, quan hệ, bảng đo lường

### Import từ Postgres

Power BI kết nối trực tiếp vào Postgres (`localhost:5432`, database `ecommerce`)
bằng connector PostgreSQL (Npgsql), ở chế độ **Import** (không phải DirectQuery —
dữ liệu được nạp vào bộ nhớ Power BI, không query trực tiếp mỗi lần tương tác).
18 bảng được nạp, chia theo schema:

| Schema | Bảng |
|---|---|
| `marts_core` | `fact_order`, `fact_order_item`, `fact_refund`, `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `mart_customer_summary`, `dim_date`, `dim_site`, `dim_country`, `dim_product`, `dim_customer_anonymized` |
| `marts_operations` | `fact_order_cost` |
| `marts_recon` | `recon_cost_coverage`, `recon_payment_fee_coverage`, `recon_csv_vs_dbt_revenue`, `recon_csv_vs_dbt_profit`, `recon_woo_vs_csv_shipping_charged` |

Lý do dùng **Load** thay vì **Transform Data**: các mart dbt **đã** được làm
sạch, ép kiểu, tính toán sẵn — Power BI Desktop không nên biến thành một lớp
transform thứ hai (điều này sẽ phá vỡ nguyên tắc "dbt sở hữu mọi phép biến đổi"
ở chương 01/05/06).

### Quan hệ dim → fact, một chiều (single direction)

Tổng cộng **19 quan hệ**, mỗi quan hệ đều theo cùng một khuôn: kéo khóa từ bảng
**dim** ("một") sang bảng **fact** ("nhiều"), với:
- **Cardinality = One to many (1:\*)**
- **Cross-filter direction = Single** (một chiều)
- **Active = có**

Ví dụ (nhóm Core Sales, 9 quan hệ):

| Từ (dim) | Đến (fact) | Khóa |
|---|---|---|
| `dim_date` | `fact_order` | `date_sk` |
| `dim_site` | `fact_order_item` | `site_sk` |
| `dim_customer_anonymized` | `fact_order` | `customer_sk` |

**Tại sao một chiều, không phải hai chiều (Both)?** Cross-filter hai chiều cho
phép filter lan ngược từ fact sang dim rồi lan tiếp sang fact khác dùng chung
dim đó — dễ tạo vòng lặp filter không kiểm soát được và làm sai kết quả khi mô
hình có nhiều fact (`fact_order`, `fact_order_item`, `mart_order_profit`...) cùng
share một dim. Giữ một chiều buộc bạn phải xử lý tường minh (bằng DAX, ví dụ
`TREATAS`) khi cần lan filter — thấy rõ trong lỗi đã sửa ở `[Revenue per
Country]` (§2 bên dưới).

**Bảng recon bị cô lập có chủ đích.** 5 bảng `recon_*` **không có quan hệ nào**
với phần còn lại của star schema — chúng chỉ có 1 dòng/site + 1 dòng `__ALL__`
tổng, và các measure đọc trực tiếp dòng `__ALL__` bằng `CALCULATE` (xem §3). Nối
chúng vào star sẽ vô nghĩa (chúng không cùng grain với fact_order) và dễ gây
nhầm lẫn khi debug — nên `BUILD_GUIDE.md` cố ý dồn 5 bảng này vào một góc riêng
của Model View, tách khỏi khu vực dim/fact.

### Đánh dấu bảng ngày (mark as date table)

`dim_date` được đánh dấu **Mark as date table** trên cột `date_day` — bước bắt
buộc để các hàm time-intelligence của DAX (`DATEADD`, dùng trong mọi measure
MoM %) hoạt động đúng. Power BI cần biết đây là bảng lịch liên tục, duy nhất
theo ngày, để tính "cùng kỳ tháng trước" chính xác.

### Bảng `_Measures`

Một bảng rỗng (Enter Data → xóa cột dummy sau khi có measure đầu tiên), đặt tên
với dấu gạch dưới `_Measures` để nó **luôn nổi lên đầu** danh sách bảng trong
Fields pane (dấu `_` đứng trước chữ cái trong thứ tự sắp xếp ASCII). Đây là nơi
duy nhất chứa mọi công thức DAX — tách biệt hoàn toàn khỏi các bảng dữ liệu, để
khi tìm một measure không phải lục qua 18 bảng.

## 2. DAX và cách đặt tên measure

**Measure khác cột (column).** Một cột là dữ liệu đã lưu sẵn trong bảng (ví dụ
`fact_order[shipping_charged_usd]`); một **measure** là công thức được **tính
lại theo ngữ cảnh lọc (filter context)** hiện tại — mỗi khi bạn đổi slicer ngày/
site/country, mọi measure tự tính lại cho đúng lát cắt đó. Đây là lý do
`[Revenue]` không thể là một cột: nó phải cộng dồn theo đúng bộ lọc đang áp
dụng.

**Quy ước đặt tên: theo nghiệp vụ, không prefix kỹ thuật.** Measure đặt tên như
người dùng cuối sẽ đọc: `[Revenue]`, `[Contribution Profit]`, `[Cost Coverage
%]` — không phải `[m_revenue]` hay `[calc_ContributionProfit]`. Tên measure
xuất hiện trực tiếp trên card/trục biểu đồ, nên phải tự giải thích được.

Vài ví dụ từ `powerbi/measures/dax_measures.txt`, minh họa cách công thức DAX
bám sát định nghĩa chỉ số ở `METRICS_DEFINITION.md`:

```dax
// Revenue — CHỈ đọc từ fact_order_item, không đọc từ fact_order (không có cột
// revenue ở đó — tránh double-count order × item, xem bất biến #1 ở chương 06)
Revenue =
CALCULATE(
    SUM(fact_order_item[line_revenue_usd]),
    fact_order_item[is_revenue_status] = TRUE()
)

// Contribution Profit — đọc thẳng từ mart đã tính sẵn trong dbt, không tính
// lại công thức locked trong DAX (tránh hai nơi cùng định nghĩa một chỉ số)
Contribution Profit =
SUM ( mart_order_profit[contribution_profit_usd] )
```

Một lỗi thật đã được review-fix trong file này minh họa vì sao quan hệ một
chiều (§1) đòi hỏi cẩn thận: `[Revenue per Country]` ban đầu chỉ tái dùng
`[Revenue]` với `dim_country` trên trục — nhưng vì `fact_order_item` không có
`country_sk` (cột đó nằm ở `fact_order`) và quan hệ là một chiều, bộ lọc
country không lan được sang `fact_order_item`, khiến mọi country hiện ra cùng
một con số tổng. Bản sửa dùng `TREATAS` để "bắc cầu" tập `order_sk` đã lọc theo
country từ `fact_order` sang `fact_order_item`:

```dax
Revenue per Country =
CALCULATE (
    [Revenue],
    TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] )
)
```

Đây là ví dụ thực tế cho thấy: khi mô hình có quan hệ một chiều nhưng chỉ số
cần cộng dồn qua nhiều fact — phải xử lý tường minh bằng DAX, không dựa vào
auto-filter ngầm định.

## 3. Gating lợi nhuận bằng measure — biến quy tắc ở chương 08 thành hành vi

Ba measure biến coverage (chương 08) thành cơ chế ẩn/hiện tự động:

```dax
// Đọc thẳng dòng '__ALL__' từ bảng recon bị cô lập (§1)
Cost Coverage % =
CALCULATE (
    MAX ( recon_cost_coverage[cost_coverage_pct] ),
    recon_cost_coverage[site_sk] = "__ALL__"
)

// Cờ hiển thị: 1 nếu coverage ≥ 80%, ngược lại 0
Profit Visible Flag =
IF ( [Cost Coverage %] >= 80, 1, 0 )

// Banner chỉ hiện khi coverage đỏ; BLANK() khi không — card tự thu gọn
Profit Unavailable Banner =
IF (
    [Cost Coverage %] < 80,
    "Profit unavailable — cost coverage too low",
    BLANK ()
)
```

Cơ chế áp dụng: mọi visual liên quan tới lợi nhuận (card, chuỗi line chart,
histogram margin, scatter, màu trên map) có một **visual-level filter** trên
`[Profit Visible Flag] = 1`. Khi coverage tụt xuống dưới 80% trong tương lai,
flag tự chuyển về 0 và visual tự trống — không cần ai vào sửa dashboard bằng
tay. Các measure "wrapper" (`[Contribution Profit]` v.v.) cũng tự trả `BLANK()`
khi flag = 0, nên card tự ẩn theo hai lớp độc lập.

Tương tự, `[Payment Fee Chip]` đọc `[Payment Fee Coverage %]` (dòng `__ALL__`
của `recon_payment_fee_coverage`) và chỉ hiện text cảnh báo khi < 80%. Trạng
thái sống trên FOS: Cost Coverage 98.79% (GREEN) và Payment Fee Coverage
98.03% — cả hai banner/chip đều **BLANK** (ẩn), chỉ **Profit Caveat Banner**
(giải thích COGS đã gồm shipping, doanh thu là net-of-refund) luôn hiện cạnh
mọi visual lợi nhuận, vì đó là caveat cố định chứ không phải cảnh báo có điều
kiện.

## 4. Các trang dashboard

`docs/DASHBOARD_SPEC.md` định nghĩa 9 trang, nhưng Phase 4 chỉ build 5 trang
(1, 2, 3, 4, 9) — các trang Phase 5/6 (Fulfillment, GA4, Marketing) bị ẩn cho
tới khi dữ liệu tương ứng tồn tại:

| Trang | Nội dung chính | Gate/disclosure bắt buộc |
|---|---|---|
| **1. Executive Overview** | Revenue, Net Revenue, Orders, AOV, Shipping Charged, Refund/Cancellation Rate, Open Backlog, + card lợi nhuận (tier-gated) | Profit Caveat Banner (luôn hiện khi profit hiện); Profit Unavailable Banner (ẩn khi GREEN) |
| **2. Product Performance** | Top 20 sản phẩm theo Contribution Profit/Revenue, scatter Revenue vs Margin, donut theo `product_type` | Chip vàng khi `cost_allocation_method != 'line_exact'` (chi phí được phân bổ theo tỷ lệ doanh thu, không phải chi phí dòng chính xác) |
| **3. Country/Market** | Map theo Revenue + màu theo Margin, bảng theo country, Shipping Charged Ratio | Nhãn bắt buộc: "shipping charged to customer / revenue (NOT shipping cost)" — không bao giờ gọi là "shipping cost" |
| **4. Customer/Repeat** | Distinct Customers, Repeat Share, cohort retention heatmap | Disclosure guest-checkout: khách hàng suy ra từ email đã băm; một người 2 email = 2 khách hàng; hộp thư chung = 1 khách hàng |
| **9. Data Quality** | Cost Coverage % + tier, Payment Fee Coverage % + source mix, 3 bảng drift (CSV vs Woo revenue, CSV vs dbt profit, Woo vs CSV shipping) | Luôn bật (always-on operational page) |

Mỗi trang có chung: một slicer ngày (`dim_date[date_day]`, mặc định "30 ngày gần
nhất", đồng bộ qua **Sync slicers**), slicer site + country, và một **Data
Quality strip** nhỏ (2 card: `[Cost Coverage %]`, `[Payment Fee Coverage %]`) —
để người xem luôn thấy độ tin cậy của số liệu ngay trên trang đang xem, không
phải chuyển sang trang riêng mới biết.

**Trạng thái sống hiện tại (kiểm tra trước khi lưu `.pbix`):** Cost Coverage
98.79% (GREEN, ≥ 95%) → mọi card/chart lợi nhuận **hiện, không chip**. Payment
Fee Coverage 98.03% (≥ 80%) → Payment Fee Chip **tắt**. Nghĩa là bản MVP hiện
tại hiển thị lợi nhuận đầy đủ và "sạch" — không banner, không chip cảnh báo nào
— nhưng cơ chế gating vẫn nằm sẵn trong measure, sẽ tự kích hoạt nếu coverage
tương lai giảm.

## Khái niệm áp dụng được

- **Semantic model tách biệt khỏi transform:** Power BI Import chỉ nạp dữ liệu
  đã sạch từ dbt — không Transform Data thêm, tránh một lớp business logic thứ
  hai nằm ngoài tầm kiểm soát của dbt.
- **Quan hệ dim→fact một chiều là mặc định an toàn**; khi cần chỉ số cộng dồn
  qua nhiều fact không share cùng cột khóa, xử lý tường minh bằng `TREATAS`
  trong DAX thay vì bật cross-filter hai chiều.
- **Bảng lookup không cùng grain với star schema (ở đây: recon coverage) nên bị
  cô lập có chủ đích**, đọc bằng `CALCULATE` + filter dòng `__ALL__`, không ép
  vào quan hệ.
- **Đặt tên measure theo nghiệp vụ, không theo kỹ thuật** — tên measure là giao
  diện người dùng nhìn thấy trực tiếp.
- **Coverage đo được (chương 08) chỉ có giá trị khi được nối vào measure gating
  thật** (`Profit Visible Flag`, banner/chip trả `BLANK()` khi không áp dụng) —
  nếu không, "gating" chỉ là tài liệu, không phải hành vi dashboard.
- **Mọi visual có caveat nghiệp vụ (ví dụ nhãn shipping, disclosure khách
  hàng) phải có bản text cố định trên trang**, không dựa vào việc người xem tự
  nhớ đọc tài liệu.

Xem thêm: chương 06 (nguồn gốc các bất biến mà measure phải tôn trọng), chương
08 (định nghĩa coverage/gating mà chương này thực thi), chương 10 (đúc kết toàn
bộ các khái niệm tái sử dụng).
