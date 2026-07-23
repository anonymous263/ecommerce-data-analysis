# 11 — Từ điển measure & DAX (giải thích từng công thức)

> **Thể loại:** tra cứu, không phải đọc một mạch — giống chương 07 (từ điển dữ liệu).
> **Nguồn gốc:** `powerbi/measures/dax_measures.txt` (công thức) + `docs/METRICS_DEFINITION.md` (spec chính thức, tiếng Anh).
> **Quan hệ với các chương khác:** chương 09 dạy *khái niệm* DAX và gating; chương này đi *từng measure một*.

## Vì sao chương này tồn tại

`METRICS_DEFINITION.md` trả lời câu hỏi **"metric này là gì"** — cực kỳ cô đọng, mỗi metric 2–3 dòng, tiếng Anh, dùng làm spec chính thức và là đích của mọi cross-link từ `Description` của 48 measure.

Nhưng khi bạn ngồi trước Power BI và nhìn vào:

```dax
Revenue per Country =
CALCULATE ( [Revenue], TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] ) )
```

thì spec không trả lời được: *`TREATAS` là gì? Tại sao phải viết vòng vo thế này? Nếu viết đơn giản hơn thì sai chỗ nào?*

Chương này trả lời đúng những câu đó. Với **mỗi measure**: công thức, đọc hiểu từng dòng, **tại sao viết như vậy**, **viết sai thì hỏng ra sao**, và **bài học mang đi được**.

> **Quy ước:** mọi §-reference (§A1, §B5…) trỏ tới `docs/METRICS_DEFINITION.md`. Giữ nguyên số hiệu để hai file luôn khớp nhau.

---

## Bản đồ 48 measure

| Nhóm | Số measure thật | Nội dung |
|---|---|---|
| **A. Sales** | 13 | Doanh thu, đơn, AOV/AIV, phí ship thu khách, backlog, 4 measure MoM |
| **B. Profit + gating** | 17 | Chi phí, lợi nhuận đóng góp, margin/ROI, coverage, và 7 measure điều khiển hiển thị |
| **C. Refund** | 7 | Hoàn tiền, huỷ đơn, tỷ lệ |
| **G. Site & Geography** | 3 | Doanh thu theo country, 2 measure chốt cỡ mẫu |
| **H. Data Quality** | 4 | Coverage đọc từ recon, mix nguồn phí thanh toán, drift |
| **I. Customer** | 4 | Khách hàng duy nhất, khách quay lại |
| | **48** | |

**Không phải mục nào trong file cũng là measure.** Có 3 loại mục:

1. **Measure thật** — có công thức DAX, phải tạo trong `_Measures`.
2. **Reuse** — comment một dòng, nghĩa là "dùng lại measure khác + kéo cột dim vào visual". Ví dụ `[Revenue per Site]`.
3. **VISUAL** — comment ghi rõ "VISUAL, not a measure", nghĩa là dựng bảng/biểu đồ trực tiếp từ bảng recon, không cần DAX.

---

# Phần 0 — Nền tảng: cách đọc một measure DAX

Đọc phần này một lần, các nhóm sau sẽ nhẹ đi rất nhiều.

## 0.1. Filter context — khái niệm quan trọng nhất

Một measure **không có giá trị cố định**. Nó được tính lại cho **từng ô** trong visual, dựa trên **bộ lọc đang tác động lên ô đó** — gọi là **filter context** (ngữ cảnh lọc).

Ví dụ `[Revenue]` trong một bảng có `dim_country[country_name]` ở trục:

| Ô | Filter context | `[Revenue]` trả về |
|---|---|---|
| Dòng "Vietnam" | `country_name = "Vietnam"` | Doanh thu của riêng Vietnam |
| Dòng "USA" | `country_name = "USA"` | Doanh thu của riêng USA |
| Dòng Total | (không lọc country) | Tổng toàn bộ |

Cùng **một** công thức, **ba** kết quả khác nhau. Đây là lý do DAX khó hơn SQL: trong SQL bạn viết `GROUP BY` tường minh, còn trong DAX **visual tự áp filter context** và measure phải sống chung với nó.

**Hệ quả thực tế:** rất nhiều lỗi DAX không phải sai công thức, mà là **filter context không lan tới nơi cần lan** — đúng như toàn bộ nhóm G của dự án này.

## 0.2. `CALCULATE` — hàm duy nhất sửa được filter context

`CALCULATE(<biểu thức>, <điều kiện 1>, <điều kiện 2>, …)` tính `<biểu thức>` sau khi **sửa** filter context bằng các điều kiện.

```dax
CALCULATE( SUM(fact_order_item[line_revenue_usd]), fact_order_item[is_revenue_status] = TRUE() )
```

**Bẫy quan trọng nhất của `CALCULATE`:** một điều kiện đặt trên cột X sẽ **THAY THẾ** (không phải giao với) filter đang có trên chính cột X.

```dax
// Visual đang lọc payment_fee_source = "api_exact" ở dòng hiện tại
CALCULATE( SUM(...[order_count]), ...[payment_fee_source] <> "__ALL__" )
// → filter "api_exact" bị XOÁ, thay bằng "<> __ALL__"  → trả về TỔNG mọi source
```

Đây chính là lỗi HIGH đã xảy ra ở `[Payment Fee Source Share]` — khiến mọi dòng hiện 100%. Thuốc giải là `KEEPFILTERS` (xem §H).

## 0.3. Measure gọi measure

DAX cho phép measure tham chiếu measure khác bằng `[Tên]`. Dự án này dùng rất nhiều:

```dax
AOV = DIVIDE([Revenue], [Orders])
```

**Lợi ích lớn:** khi định nghĩa `[Revenue]` thay đổi, **mọi** measure phụ thuộc tự cập nhật. Đây là lý do file có `[Profit Base Net Revenue]` riêng thay vì lặp lại `SUM(...)` ở 3 nơi. Nguyên tắc DRY áp dụng nguyên vẹn vào DAX.

**Quy tắc của dự án:** không bao giờ chép lại logic của một measure đã có — luôn gọi lại nó.

## 0.4. `VAR … RETURN`

```dax
VAR OrderCount = [Orders]
RETURN IF ( OrderCount >= 10, [AOV], BLANK () )
```

`VAR` tính **một lần**, dùng nhiều lần. Ba lợi ích: nhanh hơn (không tính lặp), dễ đọc hơn, và **cố định thời điểm đánh giá** — giá trị `VAR` được "đóng băng" tại filter context lúc khai báo, không bị `CALCULATE` phía sau làm đổi.

## 0.5. `DIVIDE` thay vì `/`

```dax
DIVIDE([Revenue], [Orders])   // ĐÚNG — mẫu số 0 → BLANK
[Revenue] / [Orders]          // SAI  — mẫu số 0 → lỗi Infinity/NaN trên visual
```

Toàn bộ dự án dùng `DIVIDE`. Không có ngoại lệ. `BLANK()` khiến Power BI **ẩn dòng** thay vì hiện lỗi — hành vi mong muốn.

## 0.6. Chuỗi format (nhắc lại, vì đây là nguồn lỗi âm thầm)

| Format | Dùng cho | Ghi chú |
|---|---|---|
| `\$#,0.00` | Tiền | `\$` là dấu `$` literal; backslash **không bắt buộc** ở đây |
| `#,0` | Đếm nguyên | |
| `0.0%` | **Phân số 0–1** | `%` **nhân 100** |
| `0.00\%` / `0.0"%"` | **Số đã ở thang 0–100** | `\%` và `"%"` là `%` literal, **không nhân** |
| `0.00` | Tỷ số không đơn vị | |
| (không) | Measure trả về text | |

**Quy tắc nhận biết:** thân measure có `DIVIDE(...)` trên cột thô → phân số → `0.0%`. Thân measure là `MAX(recon_…[…_pct])` → dbt đã scale sẵn 0–100 → format literal.

**Sai chỗ này = lỗi 100×.** Cho `[Cost Coverage %]` (trả về `98.92`) format `0.0%` sẽ hiện `9892.0%`, và vì `[Coverage Tier]` so sánh `>= 95` nên gating vẫn báo "green" — **sai âm thầm, không có thông báo lỗi nào**.

---

# Nhóm A — Sales (13 measure)

*Spec: §A1–A8, §D4. Bảng: `fact_order`, `fact_order_item`, `dim_date`.*

## A-1. `[Revenue]` — measure nền tảng nhất của dự án

```dax
Revenue =
CALCULATE(
    SUM(fact_order_item[line_revenue_usd]),
    fact_order_item[is_revenue_status] = TRUE()
)
```

**Format:** `\$#,0.00` · **Spec:** §A1

**Đọc hiểu:** cộng `line_revenue_usd` ở **cấp dòng hàng** (item), chỉ trên các dòng thuộc đơn có trạng thái tính doanh thu.

**Vì sao đọc từ `fact_order_item` chứ không phải `fact_order`?**

Đây là **bất biến #1** của dự án, và là quyết định thiết kế quan trọng nhất trong toàn bộ mô hình:

> **Doanh thu chỉ tồn tại ở đúng một chỗ: `fact_order_item.line_revenue_usd`.**
> `fact_order` **không có** cột revenue — cố ý.

Lý do: nếu revenue nằm ở cả hai bảng, thì một truy vấn join `fact_order` với `fact_order_item` sẽ **nhân bản doanh thu theo số dòng hàng**. Đơn có 3 sản phẩm → doanh thu bị đếm 3 lần. Đây là lỗi kinh điển của star schema, gọi là **fan-out trap**. Cách phòng vệ triệt để nhất là **không để cột đó tồn tại** ở bảng cha.

**Vì sao cần `is_revenue_status`?**

Các dòng hàng của đơn `failed`/`cancelled`/`pending` **vẫn có** `line_revenue_usd` khác null (Woo vẫn ghi giá). Không lọc thì doanh thu bị thổi phồng bằng những đơn chưa từng thu được tiền. Cột `is_revenue_status` do dbt tính sẵn, `TRUE` với `completed`/`processing`/`refunded` (theo `WOO_PAYLOAD_AUDIT.md` §5).

Lưu ý `refunded` **có** tính doanh thu — vì đây là doanh thu **gross** (trước hoàn tiền). Hoàn tiền bị trừ ở `[Net Revenue]`.

**Bài học mang đi:** khi thiết kế star schema, hãy chủ động **xoá** cột đo lường khỏi bảng có grain thô hơn, thay vì tin rằng "mình sẽ nhớ không dùng nó". Ràng buộc bằng cấu trúc mạnh hơn ràng buộc bằng kỷ luật.

## A-2. `[Net Revenue]`

```dax
Net Revenue = [Revenue] - [Refund Amount]
```

**Format:** `\$#,0.00` · **Spec:** §A2

Doanh thu gross trừ hoàn tiền. `[Refund Amount]` định nghĩa ở nhóm C.

**Điểm dễ nhầm — dự án có HAI net revenue:**

| Measure | Công thức | Dùng ở đâu |
|---|---|---|
| `[Net Revenue]` | `[Revenue] - [Refund Amount]` — tính live trong DAX | Card hiển thị, MoM |
| `[Profit Base Net Revenue]` | `SUM(mart_order_profit[net_revenue_usd])` — đọc từ mart | **Mẫu số của Profit Margin** |

Hai cái **gần bằng nhau nhưng không đảm bảo bằng tuyệt đối**, vì mart áp thêm logic netting/capping hoàn tiền ở tầng dbt. Khi cần **khớp chính xác với dbt** (ví dụ Profit Margin), luôn dùng bản đọc từ mart. Chính comment trong file cũng ghi rõ điều này.

**Bài học mang đi:** khi một con số phải tie-out với hệ thống thượng nguồn, **đọc thẳng số đã tính sẵn**, đừng tính lại ở tầng BI. Tính lại = hai nguồn sự thật = lệch nhau lúc nào không biết.

## A-3. `[Orders]`

```dax
Orders =
CALCULATE(
    DISTINCTCOUNT(fact_order[order_sk]),
    fact_order[status] IN { "processing", "completed", "on-hold" }
)
```

**Format:** `#,0` · **Spec:** §A3

`DISTINCTCOUNT` chứ không phải `COUNTROWS`: đảm bảo một đơn chỉ đếm một lần kể cả khi filter context làm bảng bị nhân dòng.

**Lưu ý cần biết (điểm quan sát, không phải bug):** population của `[Orders]` (`processing`/`completed`/`on-hold`) **không trùng** population của `[Revenue]` (`completed`/`processing`/`refunded`). Cụ thể:

- Đơn `refunded` → **có** revenue, **không** được đếm vào Orders.
- Đơn `on-hold` → **được** đếm vào Orders, **không** có revenue.

Nghĩa là `AOV = [Revenue] / [Orders]` đang chia hai tập hơi lệch nhau. Cả hai đều **đúng theo spec** (§A1 và §A3 định nghĩa vậy), nên đây không phải lỗi DAX — nhưng khi diễn giải AOV bạn cần biết. Nếu số đơn `on-hold`/`refunded` tăng mạnh, AOV sẽ trôi mà không do giá trị đơn thay đổi.

## A-4. `[Quantity Sold]`

```dax
Quantity Sold =
CALCULATE(
    SUM(fact_order_item[quantity]),
    fact_order_item[is_revenue_status] = TRUE()
)
```

**Format:** `#,0` · **Spec:** §A4

**REVIEW (HIGH — đã sửa):** bản gốc là `SUM(fact_order_item[quantity])` **không có filter**. Hậu quả: đếm cả số lượng của đơn `cancelled`/`failed`/`pending`, khiến population lệch với `[Revenue]` và **AIV bị hạ thấp giả tạo** (mẫu số phình, tử số không đổi). Đã sửa bằng cách thêm đúng filter mà `[Revenue]` dùng.

> ⚠️ **Doc drift:** `METRICS_DEFINITION.md §A4` vẫn ghi công thức cũ `SUM(fact_order_item.quantity)` không kèm điều kiện. Spec đang **lệch** với DAX thực tế. Cần cập nhật §A4 thành `SUM(fact_order_item.quantity) WHERE is_revenue_status`.

**Bài học mang đi:** khi hai measure tạo thành **tử số và mẫu số** của một tỷ lệ, chúng **bắt buộc** phải lọc trên cùng một population. Đây là lớp lỗi khó thấy nhất trong BI: mỗi measure tách riêng đều đúng, chỉ khi chia nhau mới sai.

## A-5. `[AOV]` — giá trị đơn hàng trung bình

```dax
AOV = DIVIDE([Revenue], [Orders])
```

**Format:** `\$#,0.00` · **Spec:** §A5

Không có gì phức tạp — nhưng chú ý lưu ý ở A-3 về lệch population.

## A-6. `[AIV]` — giá trị mỗi sản phẩm trung bình

```dax
AIV = DIVIDE([Revenue], [Quantity Sold])
```

**Format:** `\$#,0.00` · **Spec:** §A6

Sau khi sửa A-4, tử số và mẫu số **cùng** population `is_revenue_status = TRUE()`. Đây là điều làm AIV đáng tin hơn AOV về mặt nhất quán tập hợp.

## A-7. `[Shipping Charged to Customer]`

```dax
Shipping Charged to Customer = SUM(fact_order[shipping_charged_usd])
```

**Format:** `\$#,0.00` · **Spec:** §A7

**Đây là chỗ dễ hiểu sai nhất của toàn dự án.** Đọc kỹ:

> Đây là **phí ship KHÁCH TRẢ** khi checkout. Nó thuộc **phía doanh thu**. Nó **KHÔNG PHẢI chi phí**.

**Bất biến #3:** `actual_shipping_cost_usd` **không tồn tại** trong dự án này. Không có ở model, không có ở DAX, không có ở đâu cả. Nếu bạn thấy tham chiếu tới nó ở bất kỳ đâu — đó là bug.

**Bất biến #6:** chi phí ship của nhà cung cấp **đã nằm sẵn bên trong `cogs_usd`** (cột U = chi phí fulfill all-in một đơn). Nên khi tính profit ta **không bao giờ trừ ship như một chi phí lần nữa**.

**Bất biến #2 + #4 (Approach A, 2026-07-21):** vì ship khách trả LÀ doanh thu (tiền store nhận về), nó được **cộng vào cơ sở doanh thu** của profit: `net_revenue = (product + shipping) − refund`. Store vừa **thu** ship của khách vừa **trả** COGS all-in để fulfill → cả hai vế đều xuất hiện. Công thức cũ bỏ quên vế thu này → thiếu ~$40k lợi nhuận ($47.5k → $87.1k); xem `docs/METRIC_CHANGES.md`.

Ghép lại, **hai lỗi cần tránh**: (1) **trừ** `- [Shipping Charged to Customer]` vào công thức profit như một chi phí — sai, vì ship đã là doanh thu và chi phí ship NCC đã nằm trong COGS; (2) **quên cộng** ship vào doanh thu — chính là lỗi model cũ. Đúng là: ship nằm ở **phía doanh thu**, một lần, đã gộp sẵn trong `mart_order_profit[net_revenue_usd]`.

Đây chính là lý do tồn tại `[Profit Caveat Banner]` (xem B-16) — dán cảnh báo này **thẳng lên dashboard**.

**Bài học mang đi:** khi một khái niệm nghiệp vụ có hai mặt dễ lẫn (phí thu khách vs chi phí trả NCC), hãy **đặt tên dài và tường minh** (`shipping_charged_usd` chứ không phải `shipping`), và ghi bất biến vào tài liệu ở chỗ người ta buộc phải đọc.

## A-8. `[Shipping Charged % of Revenue]`

```dax
Shipping Charged % of Revenue = DIVIDE([Shipping Charged to Customer], [Revenue])
```

**Format:** `0.0%` · **Spec:** §A8

Tỷ lệ phí ship thu khách trên doanh thu — cho biết nước nào khách chịu phí ship nặng so với giá trị đơn.

**Cạm bẫy:** measure này **chỉ đúng ở cấp tổng hoặc theo site**. Kéo `dim_country` vào visual là sai — xem chi tiết ở nhóm G. Nhãn trên dashboard phải ghi *"shipping charged to customer / revenue"*, tuyệt đối không gọi là cost ratio.

## A-9. `[Open Order Backlog]`

```dax
Open Order Backlog =
CALCULATE(
    DISTINCTCOUNT(fact_order[order_sk]),
    fact_order[status] = "processing"
)
```

**Format:** `#,0` · **Spec:** §D4

Số đơn đang chờ fulfill. Thuộc nhóm D (Operations) trong spec nhưng đặt ở nhóm A trong file DAX vì nó là measure vận hành **duy nhất** khả dụng ở Phase 4 — phần còn lại của nhóm D cần `fact_fulfillment` (Phase 5).

## A-10 → A-13. Bốn measure MoM (Month-over-Month)

Bốn measure cùng **một khuôn mẫu**, chỉ khác measure gốc:

```dax
Revenue MoM % =
VAR CurrentPeriod = [Revenue]
VAR PriorPeriod = CALCULATE( [Revenue], DATEADD(dim_date[date_day], -1, MONTH) )
RETURN DIVIDE(CurrentPeriod - PriorPeriod, PriorPeriod)
```

**Format:** `0.0%` (cả bốn)

| Measure | Measure gốc | Spec |
|---|---|---|
| `[Revenue MoM %]` | `[Revenue]` | §A1 |
| `[Net Revenue MoM %]` | `[Net Revenue]` | §A2 |
| `[Shipping Charged MoM %]` | `[Shipping Charged to Customer]` | §A7 |
| `[Contribution Profit MoM %]` | `[Contribution Profit]` (nhóm B) | §B |

**`DATEADD(dim_date[date_day], -1, MONTH)` làm gì:** lấy tập ngày đang có trong filter context, **dịch lùi 1 tháng**, rồi dùng tập đó làm filter mới. Nếu ô hiện tại là tháng 7 thì `PriorPeriod` là `[Revenue]` của tháng 6.

**Hai điều kiện bắt buộc** để `DATEADD` chạy đúng — thiếu một trong hai là ra số sai **âm thầm**:

1. **`dim_date` phải được Mark as date table** (Table tools → Mark as date table). Không đánh dấu, DAX time-intelligence không biết đâu là cột ngày chuẩn.
2. **`dim_date` phải liên tục** — đủ mọi ngày, không thủng lỗ. `DATEADD` dịch theo **vị trí trong bảng ngày**, không phải theo số học lịch. Bảng thiếu ngày → dịch sai.

Xem `BUILD_GUIDE.md` §2 để biết bước đánh dấu.

**Vì sao dùng `VAR`:** `PriorPeriod` được dùng **hai lần** (ở tử số và mẫu số). Không có `VAR` thì `CALCULATE` chạy hai lần — chậm hơn và dễ sai nếu context đổi giữa chừng.

**Điểm cần biết:** khi `PriorPeriod = 0` hoặc BLANK (tháng đầu tiên của dữ liệu), `DIVIDE` trả về BLANK → card hiện trống thay vì `∞`. Đây là hành vi đúng, đừng "sửa".

---

# Nhóm B — Lợi nhuận + gating (17 measure)

*Spec: §B1–B8, §J, §K. Bảng: `mart_order_profit`, `mart_product_profit`, `fact_order`, `recon_cost_coverage`, `recon_payment_fee_coverage`.*

Nhóm này chia làm **hai nửa có bản chất khác hẳn nhau**:

- **B-1 → B-8: đo lường** — các con số lợi nhuận.
- **B-9 → B-17: điều khiển hiển thị** — không đo gì cả, chúng **quyết định dashboard được phép hiện gì**. Đây là phần độc đáo nhất của dự án và đáng học nhất.

## B-1. `[COGS]`

```dax
COGS = SUM ( mart_order_profit[cogs_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §B1

Giá vốn hàng bán, đọc từ mart cấp đơn.

**Điều bắt buộc phải nhớ (bất biến #6):**

> `cogs_usd` **ĐÃ BAO GỒM** phí fulfillment/ship của nhà cung cấp.

Nghĩa là **không được cộng thêm bất kỳ số hạng ship nào** lên trên nó. Xem lại A-7 để hiểu vì sao đây là cái bẫy chết người.

Nguồn dữ liệu: `Order Management.csv` (Google Sheet thủ công) → `fact_order_cost` → `mart_order_profit`. COGS **chỉ tồn tại ở sheet thủ công** — Woo không biết giá vốn. Đây là lý do Phase 3 (cost enrichment) phải làm **trước** Phase 4 (Power BI).

## B-2. `[Payment Fee]`

```dax
Payment Fee = SUM ( mart_order_profit[payment_fee_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §B2

Phí cổng thanh toán, đọc từ **mart** — cùng cột mà `[Contribution Profit]` đem đi trừ.

> ⚠️ **Bẫy (đã từng sai thật):** bản cũ đọc `SUM(fact_order[payment_fee_usd])` = **$7,069.77**, trong khi profit thực sự trừ **$7,131.11** từ mart. Hệ quả: `COGS + Design Fee + Payment Fee` **không bao giờ cộng ra đúng** contribution profit — hụt **$61.34**.
>
> Hai nguyên nhân chồng lên nhau:
> 1. `fact_order` gồm **cả đơn không phải revenue** (failed/cancelled), còn mart chỉ có đơn revenue.
> 2. Mart có **fallback sang cột `Fee` của CSV** cho ~20% đơn mà Woo không có phí — `fact_order` hoàn toàn không có phần này:
>    `coalesce(fact_order.payment_fee_usd, fact_order_cost.payment_fee_fallback_usd, 0)`
>
> Nhớ quy tắc chung: **mọi số hạng chi phí trong P&L phải đọc từ cùng một bảng mà profit được tính ra.** `[COGS]` và `[Design Fee]` vốn đã đọc mart — `[Payment Fee]` là cái duy nhất lạc nhịp.

Mỗi đơn mang thêm cột `payment_fee_source` — luôn là **một trong bốn** giá trị, theo thứ tự ưu tiên:

| `payment_fee_source` | Nghĩa | Độ tin |
|---|---|---|
| `api_exact` | Lấy thẳng từ field trong Woo API | Chính xác |
| `plugin_parser` | Parse từ payload của plugin | Chính xác |
| `seed_estimate` | Ước lượng từ `seeds/payment_fees.csv` theo phương thức + nước | **Ước lượng** |
| `missing` | `NULL`, cờ `payment_fee_needs_review = TRUE` | Không có |

Hai giá trị cuối là "không chắc chắn" — tỷ trọng của chúng chính là thứ `[Payment Fee Coverage %]` đo, và nếu vượt 20% thì `[Payment Fee Chip]` bật lên. Xem B-10 và B-15.

**Bài học mang đi:** khi một con số có thể đến từ nhiều nguồn với độ tin khác nhau, hãy **lưu nguồn gốc ngay cạnh giá trị** (cột `*_source`). Nhờ vậy dashboard mới tự nói được "số này ước lượng bao nhiêu phần trăm" thay vì im lặng giả vờ chính xác.

## B-3. `[Design Fee]`

```dax
Design Fee = SUM ( mart_order_profit[design_fee_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §B3

Phí thiết kế — một trong ba thành phần chi phí. Cũng từ sheet thủ công.

## B-4. `[Gross Profit]`

```dax
Gross Profit = [Revenue] - [COGS]
```

**Format:** `\$#,0.00` · **Spec:** §B4

**Chú ý cơ sở tính:** dùng `[Revenue]` — **GROSS** (§A1, trước hoàn tiền). Cố ý **không** trừ design fee và payment fee (đó là việc của contribution profit), và **không bao giờ** trừ ship.

**So sánh hai loại lợi nhuận — đọc kỹ bảng này:**

| | `[Gross Profit]` | `[Contribution Profit]` |
|---|---|---|
| Cơ sở doanh thu | **Gross** (§A1) | **Net** (đã trừ refund) |
| Trừ COGS | ✅ | ✅ |
| Trừ Design Fee | ❌ | ✅ |
| Trừ Payment Fee | ❌ | ✅ |
| Trừ ship | ❌ (không bao giờ) | ❌ (không bao giờ) |
| Tính ở đâu | DAX | **dbt** (đọc sẵn) |

Hai measure này **không so sánh trực tiếp được** vì khác cả cơ sở doanh thu lẫn thành phần chi phí. Đừng lấy hiệu của chúng.

## B-5. `[Profit Base Net Revenue]`

```dax
Profit Base Net Revenue = SUM ( mart_order_profit[net_revenue_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §B6

Mẫu số chính xác của Profit Margin = **(product + ship) − refund** (Approach A). Giá trị thực FOS: **$157,614.83**.

Vì sao tồn tại riêng thay vì dùng `[Net Revenue]` (A-2)? Hai lý do: (1) phải **khớp tuyệt đối với mart**; (2) `[Net Revenue]` (A-2) là net **product-only** cho báo cáo sales, còn mẫu số margin phải là net **product + ship** (Approach A). Chênh giữa hai bên chính bằng phần ship khách trả (~$40k). `[Net Revenue]` tính live trong DAX; measure này đọc số dbt đã chốt — khi lệch, **luôn tin bản của mart**.

## B-6. `[Contribution Profit]` — công thức bị khoá

```dax
Contribution Profit = SUM ( mart_order_profit[contribution_profit_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §B5 · **Giá trị thực FOS: $86,670.64**

**Công thức khoá (bất biến #2, Approach A):**

```
Contribution Profit = Net Revenue − COGS − Design Fee − Payment Fee
  Net Revenue = (product + ship khách trả) − refund
```

**Ship nằm ở vế doanh thu, không phải vế chi phí.** Ship khách trả được **cộng vào** Net Revenue; còn chi phí ship của NCC đã nằm trong COGS nên **không trừ ship lần nữa** như một chi phí.

**Điểm thiết kế quan trọng nhất:** DAX **không tự tính** công thức này. Nó chỉ `SUM` một cột dbt đã tính sẵn.

Vì sao? Nếu viết `[Profit Base Net Revenue] - [COGS] - [Design Fee] - [Payment Fee]` trong DAX, bạn tạo ra **nguồn sự thật thứ hai**. Ngày nào đó dbt đổi cách netting refund, DAX vẫn tính theo cách cũ, và hai con số lệch nhau — không ai biết bên nào đúng. Đọc thẳng cột đã tính = **một nguồn sự thật duy nhất**, nằm ở dbt, có test bảo vệ.

**Bài học mang đi (áp dụng được cho mọi dự án BI):** logic nghiệp vụ thuộc về **tầng transform** (dbt/SQL), không thuộc tầng BI. DAX chỉ nên làm ba việc: tổng hợp (`SUM`), tỷ lệ (`DIVIDE`), và trình bày (format/gating). Mọi công thức nghiệp vụ phức tạp mà bạn thấy mình đang viết bằng DAX — hãy hỏi "cái này có nên nằm ở dbt không?".

## B-7. `[Profit Margin]`

```dax
Profit Margin = DIVIDE ( [Contribution Profit], [Profit Base Net Revenue] )
```

**Format:** `0.0%` · **Spec:** §B6 · **Giá trị thực FOS: 55.19%**

Mẫu số là **net revenue gồm ship** (`[Profit Base Net Revenue]` = product + ship − refund, Approach A), **không** phải `[Net Revenue]` product-only. Cả tử và mẫu đều đọc từ cùng mart `mart_order_profit`, nên tự động nhất quán population.

## B-8. `[ROI]`

```dax
ROI = DIVIDE ( [Contribution Profit], [COGS] )
```

**Format:** `0.0%` · **Spec:** §B7

Lợi nhuận trên mỗi đô giá vốn. Đây là **định nghĩa ROI riêng của POD**, không phải ROI tài chính chuẩn.

**Bất biến #5:** cột `ROI` trong CSV **không bao giờ** được dùng. Chỉ dùng số dbt tính. CSV chỉ xuất hiện ở các view `recon_csv_vs_dbt_*` để theo dõi lệch.

---

## Nửa sau của nhóm B — 9 measure điều khiển hiển thị

Từ đây trở đi, các measure **không đo lường gì cả**. Chúng đọc chỉ số chất lượng dữ liệu rồi **quyết định dashboard hiện gì**. Đây là cách dự án biến quy tắc ở chương 08 thành hành vi thật.

**Ý tưởng cốt lõi:** thay vì để người xem tự đoán "số lợi nhuận này có đáng tin không", dashboard **tự biết** độ phủ chi phí của chính nó và tự ẩn/gắn cảnh báo.

## B-9. `[Cost Coverage %]` — nguồn điều khiển của toàn bộ gating

```dax
Cost Coverage % =
CALCULATE (
    MAX ( recon_cost_coverage[cost_coverage_pct] ),
    recon_cost_coverage[site_sk] = "__ALL__"
)
```

**Format:** `0.00\%` · **Spec:** §J · **Giá trị thực: 98.92% (GREEN)**

Độ phủ chi phí: tỷ lệ **đơn có doanh thu** có `cogs_usd > 0`.

**Ba chi tiết kỹ thuật đáng học:**

**1. Vì sao `MAX()`?** Sau khi lọc `site_sk = "__ALL__"` chỉ còn **đúng một dòng**. `MAX` ở đây không mang nghĩa "lấy lớn nhất" — nó chỉ là cách hợp lệ để lấy **một giá trị vô hướng** từ một cột. DAX không cho phép trả về cột trực tiếp. Đây là **mẫu chuẩn** (idiom) trong DAX, sẽ gặp lại rất nhiều.

**2. Dòng `'__ALL__'` là gì?** Bảng `recon_cost_coverage` có một dòng cho mỗi site, **cộng thêm** một dòng tổng hợp mang khoá `'__ALL__'`. Đây là kỹ thuật đặt sẵn dòng roll-up ở tầng dbt để BI khỏi phải tự tính tổng có trọng số (coverage là tỷ lệ — **không cộng được**, phải tính lại từ tử/mẫu gốc).

**3. Thang 0–100.** dbt đã scale sẵn (`98.92`, không phải `0.9892`) → phải dùng format `%` literal. Xem §0.6.

**Bài học mang đi:** với các chỉ số **không cộng được** (tỷ lệ, trung bình có trọng số), hãy tính sẵn dòng roll-up ở tầng transform thay vì để BI tự gộp. BI gộp tỷ lệ = gần như luôn sai (nó sẽ lấy trung bình của các tỷ lệ, thay vì tỷ lệ của các tổng).

## B-10. `[Payment Fee Coverage %]`

```dax
Payment Fee Coverage % =
CALCULATE (
    MAX ( recon_payment_fee_coverage[fee_coverage_pct] ),
    recon_payment_fee_coverage[payment_fee_source] = "__ALL__"
)
```

**Format:** `0.00\%` · **Spec:** §H4/§K · **Giá trị thực: 98.03%** (cơ sở đơn-có-doanh-thu)

Cùng khuôn mẫu với B-9. Đo tỷ lệ đơn có `payment_fee_usd` khác NULL.

**Câu chuyện đằng sau con số này rất đáng học.** Ban đầu nó tính trên **mọi đơn** → ra **79.50%**, dưới ngưỡng 80% → chip cảnh báo bật. Nhưng nghĩ kỹ: đơn `failed`/`cancelled`/`pending` **chưa từng thanh toán**, nên `payment_fee_usd` NULL của chúng là **đúng**, không phải thiếu dữ liệu. Đưa chúng vào mẫu số là **đo sai câu hỏi**.

Ngày 2026-07-16 metric được **rebase** về cơ sở đơn-có-doanh-thu (giống H1) → **98.03%** → chip tắt. Ghi lại ở `docs/METRIC_CHANGES.md`. Con số 79.50% vẫn giữ làm cột tham khảo.

**Bài học mang đi:** khi một coverage metric báo thấp, hỏi trước *"mẫu số có đúng không?"* trước khi kết luận *"dữ liệu thiếu"*. Rất thường xuyên, dữ liệu không thiếu — chỉ là bạn đang đếm cả những dòng lẽ ra không nên đếm. Và khi đổi định nghĩa metric, **phải ghi vào changelog** (`METRIC_CHANGES.md`) với ngày, công thức cũ, công thức mới, lý do.

## B-11. `[Coverage Tier]`

```dax
Coverage Tier =
SWITCH (
    TRUE (),
    [Cost Coverage %] >= 95, "green",
    [Cost Coverage %] >= 80, "yellow",
    "red"
)
```

**Format:** không (text) · **Spec:** §J

Phân tầng chất lượng: `green` / `yellow` / `red`.

**Mẫu `SWITCH(TRUE(), …)` — học một lần dùng mãi:**

`SWITCH` bình thường so sánh **bằng**: `SWITCH([x], 1, "một", 2, "hai")`. Nhưng khi truyền `TRUE()` làm biểu thức, nó thành **chuỗi if-else if**: kiểm tra từng điều kiện, **cái nào TRUE trước thì thắng**.

```dax
SWITCH ( TRUE (),
    <điều kiện 1>, <kết quả 1>,
    <điều kiện 2>, <kết quả 2>,
    <mặc định> )
```

Dễ đọc hơn `IF` lồng nhau rất nhiều. **Thứ tự cực kỳ quan trọng**: `>= 95` phải đứng trước `>= 80`, vì `98.92` thoả **cả hai** — cái đứng trước thắng. Đảo thứ tự → mọi thứ thành "yellow".

**Ba tầng theo bất biến #5:**

| Tầng | Coverage | Dashboard làm gì |
|---|---|---|
| 🟢 green | ≥ 95% | Hiện lợi nhuận, không chip — số đáng tin hoàn toàn |
| 🟡 yellow | 80–95% | Hiện lợi nhuận + chip vàng "partial coverage" — dùng được nhưng chủ chưa duyệt |
| 🔴 red | < 80% | **Ẩn** visual lợi nhuận + banner "Profit unavailable" |

## B-12. `[Profit Visible Flag]`

```dax
Profit Visible Flag = IF ( [Cost Coverage %] >= 80, 1, 0 )
```

**Format:** `#,0` · **Spec:** §J

Trả về `1` khi được phép hiện lợi nhuận, `0` khi không.

**Kỹ thuật đáng học — dùng measure làm bộ lọc visual:**

Bạn **không** dùng measure này để hiện số `1`/`0` lên dashboard. Bạn kéo nó vào ô **Filters on this visual** của mỗi visual lợi nhuận, đặt điều kiện `is 1`. Khi coverage tụt xuống dưới 80%, measure trả `0`, điều kiện lọc không thoả, và **cả visual biến mất khỏi trang**.

Nghĩa là: quy tắc ẩn/hiện **không** nằm trong tay người build dashboard — nó nằm trong **dữ liệu**. Coverage tụt → visual tự ẩn, không cần ai can thiệp.

Vì dùng làm filter nên format `#,0` của nó thực tế chẳng bao giờ hiển thị.

**Bài học mang đi:** đây là mẫu **"data-driven visibility"** — biến quy tắc quản trị thành hành vi tự động của hệ thống. Áp dụng được cho mọi dashboard có vấn đề chất lượng dữ liệu: đừng viết quy tắc vào tài liệu rồi hy vọng người ta nhớ; hãy encode nó thành measure và để hệ thống tự thi hành.

## B-13. `[Profit Unavailable Banner]`

```dax
Profit Unavailable Banner =
IF (
    [Cost Coverage %] < 80,
    "Profit unavailable — cost coverage too low",
    BLANK ()
)
```

**Format:** không (text) · **Spec:** §J

Đi cặp với B-12. Khi B-12 ẩn visual, banner này **giải thích vì sao** — nếu không, người xem chỉ thấy trang trống và tưởng dashboard hỏng.

**Vì sao trả `BLANK()` thay vì `""`?** Card chứa measure BLANK sẽ **tự co lại/biến mất**. Trả chuỗi rỗng `""` thì card vẫn chiếm chỗ, để lại một ô trống lơ lửng. Đây là mẹo nhỏ nhưng dùng ở khắp nơi.

## B-14. `[Partial Coverage Chip]`

```dax
Partial Coverage Chip =
IF (
    AND ( [Cost Coverage %] >= 80, [Cost Coverage %] < 95 ),
    "Partial cost coverage ("
        & FORMAT ( [Cost Coverage %] / 100, "0.0%" )
        & ") — usable but not owner-trusted",
    BLANK ()
)
```

**Format:** không (text) · **Spec:** §J

Chip vàng của tầng giữa.

**Chú ý `[Cost Coverage %] / 100` — vì sao phải chia?**

Đây là chỗ hai thế giới format gặp nhau. `[Cost Coverage %]` ở thang **0–100** (`98.92`). Hàm `FORMAT(<giá trị>, "0.0%")` **nhân 100** rồi thêm `%`. Nếu truyền thẳng `98.92` vào, kết quả là `"9892.0%"`. Chia cho 100 trước → `FORMAT(0.9892, "0.0%")` → `"98.9%"`. Đúng.

Nghĩa là: **chuỗi format trong `FORMAT()` cũng theo đúng luật nhân-100 như format string của measure**. Cùng một cái bẫy, xuất hiện ở tầng khác.

`&` là toán tử nối chuỗi trong DAX (tương đương `+` của các ngôn ngữ khác, hoặc `CONCATENATE`).

## B-15. `[Payment Fee Chip]`

```dax
Payment Fee Chip =
IF (
    [Payment Fee Coverage %] < 80,
    "Estimated payment fee — "
        & FORMAT ( ( 100 - [Payment Fee Coverage %] ) / 100, "0.0%" )
        & " from seed_estimate or missing",
    BLANK ()
)
```

**Format:** không (text) · **Spec:** §K · **Hiện tại: TẮT** (98.03% ≥ 80%)

Chip **thứ hai**, độc lập với B-14. Một visual có thể mang **cả hai** chip cùng lúc (coverage chi phí vàng **và** phí thanh toán thiếu).

`100 - [Payment Fee Coverage %]` = phần **không** chắc chắn (`seed_estimate` + `missing`). Rồi `/100` trước `FORMAT` vì cùng lý do ở B-14.

## B-16. `[Profit Caveat Banner]`

```dax
Profit Caveat Banner =
"Customer shipping charge is counted as revenue. COGS is the all-in per-order fulfilment cost (already includes supplier fulfillment/shipping fee), so shipping is never subtracted as a cost. Revenue is net of refunds."
```

**Format:** không (text) · **Spec:** §B5 (Approach A, 2026-07-21)

**Measure "tĩnh"** — không đọc dữ liệu, luôn trả về đúng một chuỗi. Trông vô dụng, nhưng đây là cách đưa **bất biến #2/#4/#6** lên thẳng mặt dashboard.

Vì sao cần: người xem dashboard **không đọc** `CLAUDE.md`, không đọc `METRICS_DEFINITION.md`. Với Approach A, ship khách trả **đã được cộng vào doanh thu**; banner nói rõ điều đó (ship là doanh thu, không phải chi phí; COGS đã all-in) để không ai hiểu nhầm rồi tự trừ ship như một chi phí — **ngay tại chỗ họ đang nhìn**.

Spec §B5 ghi rõ caveat này **phải xuất hiện trên mọi visual lợi nhuận**.

**Bài học mang đi:** tài liệu ở đúng chỗ người ta cần nó mới có tác dụng. Một bất biến quan trọng mà chỉ nằm trong repo = một bất biến sẽ bị vi phạm.

## B-17. `[Product Profit Allocation Chip]`

```dax
Product Profit Allocation Chip =
VAR NonExactRows =
    CALCULATE (
        COUNTROWS ( mart_product_profit ),
        mart_product_profit[cost_allocation_method] <> "line_exact"
    )
RETURN
    IF (
        NOT ISBLANK ( NonExactRows ) && NonExactRows > 0,
        "Profit allocated by revenue share — not exact line-level cost",
        BLANK ()
    )
```

**Format:** không (text) · **Spec:** §B8

Chip riêng cho **trang sản phẩm**. Bật khi có dòng nào trong filter context hiện tại có chi phí bị **chia theo tỷ lệ doanh thu** thay vì đo chính xác từng dòng.

**Vì sao cần:** sheet thủ công đôi khi chỉ ghi chi phí ở **cấp đơn**, không tách theo từng sản phẩm. Khi đó dbt phải chia chi phí đó xuống các dòng hàng theo tỷ lệ doanh thu. Lợi nhuận **cấp đơn** vẫn chính xác tuyệt đối; nhưng lợi nhuận **cấp sản phẩm** thì chỉ là ước lượng. Chip nói đúng điều đó.

**Chú ý `NOT ISBLANK ( NonExactRows ) && NonExactRows > 0`** — vì sao không chỉ viết `NonExactRows > 0`?

Vì `COUNTROWS` trả về **BLANK** (không phải `0`) khi không có dòng nào thoả. Trong DAX, `BLANK() > 0` cho ra `FALSE`, nên riêng trường hợp này thì viết gọn vẫn chạy đúng — nhưng so sánh với BLANK là vùng có nhiều quy tắc ép kiểu ngầm khó nhớ. Kiểm tra `ISBLANK` tường minh khiến ý định rõ ràng và không phụ thuộc vào việc bạn có nhớ đúng luật ép kiểu hay không.

`&&` là toán tử AND (tương đương `AND(a, b)`, nhưng `&&` nhận nhiều hơn 2 vế).

**So sánh với B-12:** B-12 gác **cả trang** dựa trên coverage toàn cục; B-17 gác **theo ngữ cảnh** — chip bật/tắt tuỳ theo sản phẩm nào đang được chọn. Cùng triết lý, khác phạm vi.

---

# Nhóm C — Hoàn tiền & huỷ đơn (7 measure)

*Spec: §C1–C5. Bảng: `fact_refund`, `fact_order`.*

## C-1. `[Refunded Order Count]`

```dax
Refunded Order Count = COUNTROWS ( fact_refund )
```

**Format:** `#,0` · **Spec:** §C1 · **Giá trị thực: 34**

**REVIEW (LOW — chưa sửa, cố ý giữ nguyên):** measure này đếm **số dòng refund**, không phải **số đơn bị hoàn**. Hiện tại hai con số **trùng nhau** (34 dòng = 34 `order_sk` phân biệt) nên giá trị đang đúng.

Nhưng grain của `fact_refund` là **một dòng cho mỗi sự kiện hoàn tiền**, và Woo cho phép một đơn hoàn **nhiều lần** (hoàn từng phần). Ngày nào đó có đơn hoàn 2 lần → measure này đếm thành 2 → **thổi phồng**.

Bản bền vững hơn: `DISTINCTCOUNT(fact_refund[order_sk])`.

**Vì sao vẫn giữ bản cũ?** Vì tên measure (`Refunded Order Count`) nói "đếm đơn" nhưng công thức đếm dòng — sửa sẽ **đổi ý nghĩa metric**, mà spec §C1 ghi rõ `COUNT(*) FROM fact_refund`. Đây là quyết định của chủ sở hữu metric, không phải quyết định kỹ thuật. Đúng quy trình: ghi REVIEW, để chủ dự án chọn.

**Bài học mang đi:** luôn hỏi **"grain của bảng này là gì?"** trước khi `COUNTROWS`. Grain là khái niệm quan trọng nhất của Kimball (chương 04) và là nguồn của lớp lỗi "đúng hôm nay, sai tháng sau".

## C-2. `[Refund Amount]`

```dax
Refund Amount = SUM ( fact_refund[refund_amount_usd] )
```

**Format:** `\$#,0.00` · **Spec:** §C2 · **Giá trị thực: $1,592.02**

Đơn giản — và `SUM` **an toàn với grain nhiều dòng/đơn**, khác hẳn C-1. Một đơn hoàn 2 lần thì tổng tiền hoàn vẫn đúng.

## C-3. `[Eligible Orders]`

```dax
Eligible Orders =
CALCULATE (
    DISTINCTCOUNT ( fact_order[order_sk] ),
    NOT ( fact_order[status] IN { "failed", "pending" } )
)
```

**Format:** `#,0` · **Spec:** §C3

Mẫu số của mọi tỷ lệ hoàn/huỷ: các đơn đã đạt trạng thái **có thể kết toán**.

**Vì sao loại `failed` và `pending`?** Đơn `failed` (thanh toán lỗi) và `pending` (chưa thanh toán) **chưa từng có tiền**, nên chúng **không thể** bị hoàn. Để chúng trong mẫu số sẽ **pha loãng** tỷ lệ hoàn xuống thấp giả tạo.

Cùng logic với việc rebase payment fee coverage ở B-10: **mẫu số phải là tập có khả năng xảy ra sự kiện đang đo**. Đây là nguyên tắc chung, không phải mẹo riêng.

Chú ý `cancelled` **vẫn nằm trong** mẫu số — đơn huỷ đã từng là đơn thật, và nó chính là một phần **tử số** của refund rate (xem C-4).

## C-4. `[Refunded or Cancelled Orders]` — measure phức tạp nhất nhóm C

```dax
Refunded or Cancelled Orders =
VAR CancelledKeys =
    CALCULATETABLE ( VALUES ( fact_order[order_sk] ), fact_order[status] = "cancelled" )
VAR RefundedKeys =
    TREATAS ( VALUES ( fact_refund[order_sk] ), fact_order[order_sk] )
VAR CombinedKeys =
    DISTINCT ( UNION ( CancelledKeys, RefundedKeys ) )
RETURN
    COUNTROWS ( CombinedKeys )
```

**Format:** `#,0` · **Spec:** §C3

Đếm các đơn **hoặc** bị hoàn **hoặc** bị huỷ, **không đếm trùng** đơn vừa hoàn vừa huỷ.

**Đọc từng bước:**

1. **`CancelledKeys`** — `CALCULATETABLE` giống `CALCULATE` nhưng trả về **bảng** thay vì số. Ở đây: danh sách `order_sk` có status `cancelled`.

2. **`RefundedKeys`** — danh sách `order_sk` **có mặt trong `fact_refund`**. Nhưng bọc trong `TREATAS`.

3. **`CombinedKeys`** — `UNION` hai danh sách, rồi `DISTINCT` khử trùng.

**Vì sao cần `TREATAS` ở bước 2?**

Đây là khái niệm **lineage** (huyết thống) của DAX — khó nhưng đáng học.

Mỗi bảng do DAX tạo ra mang theo "gốc gác": cột này đến từ bảng nào. `VALUES(fact_refund[order_sk])` cho ra cột mang lineage **`fact_refund`**. `VALUES(fact_order[order_sk])` cho ra cột mang lineage **`fact_order`**. Với DAX, hai cột này **khác nhau về bản chất**, dù chứa cùng loại giá trị.

`UNION` hai bảng khác lineage → kết quả có lineage nhập nhằng → `DISTINCT` không khử trùng đúng như bạn tưởng, và filter context sau đó hành xử lạ.

`TREATAS(<bảng>, <cột đích>)` **gán lại lineage**: "hãy coi các giá trị này như thể chúng là `fact_order[order_sk]`". Sau đó `UNION` mới hợp lệ về ngữ nghĩa, `DISTINCT` khử trùng đúng.

**Bài học mang đi:** khi `UNION`/`EXCEPT`/`INTERSECT` hai tập khoá đến từ **hai bảng khác nhau**, gần như luôn cần `TREATAS` để đồng nhất lineage. Đây cũng chính là hàm giải quyết bài toán nhóm G — cùng một công cụ, hai mục đích (ở đây: đồng nhất lineage để hợp tập; ở nhóm G: chuyển filter qua bảng không có quan hệ trực tiếp).

## C-5. `[Refund Rate]`

```dax
Refund Rate = DIVIDE ( [Refunded or Cancelled Orders], [Eligible Orders] )
```

**Format:** `0.0%` · **Spec:** §C3

Tỷ lệ hoàn/huỷ ở **cấp đơn** — không phải cấp dòng hàng, không phải theo tiền. Ghép C-4 (tử) và C-3 (mẫu), cả hai đều đã lo chuyện population đúng.

## C-6. `[Cancellation Rate]`

```dax
Cancellation Rate =
DIVIDE (
    CALCULATE ( DISTINCTCOUNT ( fact_order[order_sk] ), fact_order[status] = "cancelled" ),
    [Eligible Orders]
)
```

**Format:** `0.0%` · **Spec:** §C4

Chỉ tính **huỷ**, không tính hoàn. Là **tập con** của C-5.

Chú ý: tử số viết inline thay vì gọi measure riêng — hơi lệch nguyên tắc DRY (§0.3), vì cùng biểu thức này cũng xuất hiện trong `CancelledKeys` ở C-4. Không sai, nhưng nếu định nghĩa "huỷ" đổi (ví dụ thêm status `refund-requested`), bạn phải nhớ sửa **hai chỗ**. Trong dự án lớn hơn, nên tách `[Cancelled Orders]` thành measure riêng.

## C-7. `[Refund Revenue Share]`

```dax
Refund Revenue Share = DIVIDE ( [Refund Amount], [Revenue] )
```

**Format:** `0.0%` · **Spec:** §C5

Tiền hoàn trên doanh thu **gross**. Khác C-5 ở **đơn vị đo**: C-5 đếm **đơn**, C-7 đo **tiền**.

Hai con số này có thể kể chuyện rất khác nhau. Refund rate 5% nhưng refund revenue share 15% → **các đơn giá trị cao đang bị hoàn nhiều hơn** — tín hiệu quan trọng mà nhìn một mình C-5 không thấy được. Đó là lý do dashboard cần cả hai.

---

# Nhóm G — Site & Geography (3 measure)

*Spec: §G1–G4. Bảng: `fact_order`, `fact_order_item`, `dim_country`, `dim_site`.*

## Vấn đề chung của cả nhóm — đọc trước khi đọc từng measure

Cả nhóm G xoay quanh **một hạn chế mô hình duy nhất**:

> `fact_order_item` **không có** cột `country_sk`. Country nằm ở `fact_order`.

Kết hợp với hai sự thật khác:

- **Bất biến #1:** doanh thu **bắt buộc** đọc từ `fact_order_item[line_revenue_usd]`.
- **Quan hệ trong model là một chiều** (single-direction), theo `BUILD_GUIDE.md` §2.

Filter đi từ `dim_country → fact_order` rồi **dừng lại**. Nó **không** lan tiếp xuống `fact_order_item`, vì `fact_order → fact_order_item` là quan hệ 1-nhiều theo chiều đó và filter chỉ chảy từ "một" sang "nhiều" khi có quan hệ trực tiếp — mà `dim_country` thì không có quan hệ trực tiếp với `fact_order_item`.

**Hệ quả cụ thể:** kéo `dim_country` vào visual rồi dùng `[Revenue]` → **mỗi dòng country hiện TỔNG doanh thu toàn bộ**. Không có thông báo lỗi. Bảng trông vẫn "có số".

**Vì sao model lại thiết kế một chiều?** Vì bidirectional cross-filter gây mơ hồ (ambiguity) khi có nhiều đường đi giữa hai bảng, làm hiệu năng tệ và sinh kết quả khó đoán. Chuẩn Kimball khuyên mặc định một chiều, chỉ mở hai chiều khi thật cần. Dự án chọn giải quyết bằng DAX (`TREATAS`) thay vì mở hai chiều — an toàn hơn.

## G-1. `[Revenue per Site]` — **không phải measure**

```
// Reuse [Revenue] + kéo dim_site[site_name] vào trục
```

**Spec:** §G1

Site **không** dính vấn đề trên, vì `site_sk` có mặt ở **mọi** bảng (thiết kế multi-site của dự án — xem chương 02). Chỉ cần dùng lại `[Revenue]` và kéo `dim_site[site_name]` vào trục visual.

Ghi chú trong file nhắc lại: **không** đọc revenue từ `fact_order`.

## G-2. `[Revenue per Country]` — measure thật

```dax
Revenue per Country =
CALCULATE (
    [Revenue],
    TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] )
)
```

**Format:** `\$#,0.00` · **Spec:** §G2

**REVIEW (HIGH — đã sửa):** bản gốc chỉ reuse `[Revenue]`, và như giải thích ở trên, mỗi country hiện grand total.

**Cách `TREATAS` giải quyết — đọc từ trong ra ngoài:**

1. `VALUES(fact_order[order_sk])` — lấy danh sách `order_sk` **đã bị lọc theo country**. Bước này chạy được vì `dim_country → fact_order` **vẫn** hoạt động bình thường.
2. `TREATAS(<danh sách đó>, fact_order_item[order_sk])` — gán danh sách này thành **filter đặt lên** `fact_order_item[order_sk]`.
3. `CALCULATE([Revenue], <filter đó>)` — `[Revenue]` vẫn cộng từ `fact_order_item`, nhưng giờ chỉ trên các dòng thuộc đúng những đơn của country đó.

Nói cách khác: `TREATAS` **bắc cầu thủ công** cái mà quan hệ một chiều không tự làm.

Chú ý filter `is_revenue_status = TRUE()` **vẫn còn nguyên** — nó nằm bên trong `[Revenue]`, không bị `CALCULATE` bên ngoài xoá (vì `CALCULATE` chỉ thay thế filter trên **cùng cột**, mà ở đây là `order_sk`, khác cột).

**Ba điều cấm (ghi rõ trong file):**

| Đừng làm | Vì sao |
|---|---|
| Đọc revenue từ `fact_order` | Bảng đó **không có** cột revenue — cố ý (bất biến #1) |
| Thay bằng `mart_country_profit[revenue_usd]` | Đó là **NET** revenue (đã trừ refund), không phải gross §A1 |
| Bật bidirectional cho `dim_country` | Được ghi là "giải pháp thay thế" nhưng đánh đổi hiệu năng + mơ hồ |

**Bài học mang đi:** khi một dimension gắn ở fact cấp cha nhưng số đo nằm ở fact cấp con, bạn có 3 lựa chọn: (a) `TREATAS` bắc cầu qua khoá chung, (b) mở bidirectional, (c) đưa `country_sk` xuống luôn `fact_order_item` ở tầng dbt (degenerate dimension). Dự án chọn (a) vì rẻ và không đụng vào model. Nếu bài toán này lặp ở nhiều dimension, (c) mới là lựa chọn đúng về lâu dài.

## G-3. `[AOV (min 10 orders)]`

```dax
AOV (min 10 orders) =
VAR OrderCount = [Orders]
RETURN IF ( OrderCount >= 10, [AOV], BLANK () )
```

**Format:** `\$#,0.00` · **Spec:** §G3

**Mẫu "chốt cỡ mẫu" (sample-size guard).**

Một country có 2 đơn thì AOV của nó là **nhiễu thống kê**, không phải tín hiệu. Một đơn to bất thường sẽ đẩy nó lên đầu bảng xếp hạng và làm người xem kết luận sai.

`BLANK()` khiến Power BI **tự động ẩn dòng** khỏi visual. Không cần filter thủ công, không cần nhớ loại nước nào.

Ngưỡng 10 là quy ước của spec §G3 — không phải con số thiêng. Điều quan trọng là **có** một ngưỡng và nó **nhất quán**.

**Bài học mang đi:** mọi metric dạng **trung bình/tỷ lệ** hiển thị theo nhóm nhỏ (country, sản phẩm, khách) đều cần chốt cỡ mẫu. Đây là điểm khác biệt lớn giữa dashboard nghiệp dư và dashboard dùng được: cái đầu hiện mọi thứ, cái sau biết **giấu cái không đáng tin**.

## G-4. `[Shipping Charged Ratio by Country]` — **CHƯA CÓ MEASURE — việc còn tồn**

```
// Trong file hiện chỉ là comment + REVIEW (MEDIUM) chưa áp dụng
```

**Spec:** §G4

⚠️ **Đây là chỗ cần chú ý nhất nhóm G.**

Nếu bạn lấy `[Shipping Charged % of Revenue]` (§A8) rồi kéo `dim_country` vào visual:

- **Tử số** `SUM(fact_order[shipping_charged_usd])` — **CÓ** lọc theo country (nằm ở `fact_order`) ✅
- **Mẫu số** `[Revenue]` — **KHÔNG** lọc được (nằm ở `fact_order_item`) ❌

→ Kết quả = *ship của 1 country / revenue của **TOÀN BỘ*** — một con số vô nghĩa.

**Vì sao lỗi này nguy hiểm hơn G-2:** ở G-2, mỗi country hiện grand total giống hệt nhau → nhìn phát hiện ra ngay. Ở đây, mỗi country ra một số **khác nhau, nhỏ, trông rất hợp lý** (vì mẫu số quá to nên tỷ lệ nào cũng bé). Không ai nghi ngờ.

**Công thức đúng đã ghi sẵn trong file, cần tạo thành measure thật:**

```dax
Shipping Charged Ratio by Country =
VAR ShipByCountry = SUM ( fact_order[shipping_charged_usd] )
VAR RevByCountry =
    CALCULATE ( [Revenue], TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] ) )
RETURN DIVIDE ( ShipByCountry, RevByCountry )
```

Ý tưởng: ép **cả hai vế** lọc về cùng tập đơn của country — dùng lại đúng thủ thuật `TREATAS` của G-2 cho mẫu số.

**Nhắc lại bất biến #3/#4:** đây là **phí ship thu của khách**, không phải chi phí. Nhãn phải ghi *"shipping charged to customer / revenue"*, **không bao giờ** gọi là cost ratio.

## G-5. `[Refund Rate (min 10 orders)]`

```dax
Refund Rate (min 10 orders) =
VAR EligibleOrderCount = [Eligible Orders]
RETURN IF ( EligibleOrderCount >= 10, [Refund Rate], BLANK () )
```

**Format:** `0.0%` · **Spec:** §G4/§C3

Cùng khuôn mẫu với G-3, nhưng đếm bằng **`[Eligible Orders]`** chứ không phải `[Orders]`.

**Vì sao khác?** Vì mẫu số của refund rate là **đơn đủ điều kiện hoàn** (C-3), không phải mọi đơn. Chốt cỡ mẫu phải chốt trên **đúng cái mẫu số mà tỷ lệ đang dùng** — nếu không, bạn có thể để lọt một country có 12 đơn nhưng chỉ 3 đơn eligible, và tỷ lệ hoàn của nó vẫn là nhiễu.

Chi tiết nhỏ này là ví dụ đẹp cho nguyên tắc xuyên suốt cả dự án: **tử số và mẫu số phải cùng population** (xem A-4, B-10, C-3).

---

# Nhóm H — Chất lượng dữ liệu & độ phủ (4 measure)

*Spec: §H1–H10. Bảng: `recon_cost_coverage`, `recon_payment_fee_coverage`, `recon_woo_vs_csv_*`, `mart_product_profit`.*

Nhóm này nuôi **trang Data Quality** và cơ chế gating. Đặc điểm: phần lớn nội dung là **VISUAL**, không phải measure.

## H-1, H-2. `[Cost Coverage %]`, `[Payment Fee Coverage %]` — **reuse từ nhóm B**

Không định nghĩa lại. Đã có ở B-9 và B-10. Trang Data Quality chỉ **tiêu thụ** chúng.

Giá trị thực: **98.92%** (GREEN) và **98.03%** (≥80% → chip TẮT).

## H-3. `[COGS Coverage %]`

```dax
COGS Coverage % =
CALCULATE (
    MAX ( recon_cost_coverage[cogs_coverage_pct] ),
    recon_cost_coverage[site_sk] = "__ALL__"
)
```

**Format:** `0.0"%"` · **Spec:** §H3 · **Mục tiêu:** ≥ 80%

Tỷ lệ đơn có `cogs_usd` khác null.

**Điểm thiết kế đáng học:** measure **đọc thẳng con số dbt đã tính**, không tính lại bằng DAX.

Vì sao? Nếu tính lại trong DAX, hai bên có thể lệch nhau vì khác cách xử lý biên (null vs 0, đơn nào vào mẫu số…). Khi số trên dashboard **khác** số dbt báo, không ai biết tin bên nào — và người ta sẽ mất niềm tin vào **cả hai**. Đọc thẳng = luôn khớp, bằng cấu trúc.

Đây là cùng một triết lý với B-6 (`[Contribution Profit]` đọc từ mart thay vì tự tính).

## H-4. `[Cost Allocation Coverage %]`

```dax
Cost Allocation Coverage % =
VAR LineExactRows =
    CALCULATE ( COUNTROWS ( mart_product_profit ),
        mart_product_profit[cost_allocation_method] = "line_exact" )
VAR TotalRows = COUNTROWS ( mart_product_profit )
RETURN DIVIDE ( LineExactRows, TotalRows )
```

**Format:** `0.0%` · **Spec:** §H2 · **Tính chất:** tham khảo, **không phải cổng gating**

Tỷ lệ dòng có chi phí được gán bằng **khớp chính xác theo line** (`line_exact`), thay vì bị chia đều từ cấp đơn xuống.

**Đây là tín hiệu về độ mịn của chi phí, không phải cổng.** Coverage thấp **không ẩn** visual nào. Nó chỉ cho biết lợi nhuận theo **sản phẩm** đáng tin tới đâu — lợi nhuận theo **đơn** vẫn chuẩn dù chi phí bị chia đều (chia thế nào thì tổng vẫn thế).

Đi cặp với `[Product Profit Allocation Chip]` (B-17): measure này cho **con số tổng thể**, chip cho **cảnh báo theo ngữ cảnh**.

**⚠️ Chú ý format — đây là cặp đối chiếu hoàn hảo với H-3:**

| | H-3 `[COGS Coverage %]` | H-4 `[Cost Allocation Coverage %]` |
|---|---|---|
| Cách tính | `MAX(recon…[…_pct])` — đọc từ mart | `DIVIDE(...)` — tính live |
| Giá trị trả về | `98.92` (thang 0–100) | `0.9892` (phân số 0–1) |
| Format đúng | `0.0"%"` (**không** nhân) | `0.0%` (**có** nhân) |

Hai measure cạnh nhau, cùng tên "Coverage %", **format ngược nhau**. Đây chính xác là lý do §0.6 tồn tại.

## H-5. `[Payment Fee Source Mix]` — **VISUAL, không phải measure**

**Spec:** §H4b

Dựng bảng/bar trực tiếp trên `recon_payment_fee_coverage`:
- Trục: `payment_fee_source`
- Values: `order_count` + `fee_coverage_pct`
- **Visual-level filter: `payment_fee_source <> '__ALL__'`** ← bắt buộc, nếu không dòng tổng hợp sẽ nằm chung với các dòng chi tiết

## H-6. `[Payment Fee Source Share]` — measure thật, chứa bài học `KEEPFILTERS`

```dax
Payment Fee Source Share =
VAR SourceOrders =
    CALCULATE (
        SUM ( recon_payment_fee_coverage[order_count] ),
        KEEPFILTERS ( recon_payment_fee_coverage[payment_fee_source] <> "__ALL__" )
    )
VAR TotalSourceOrders =
    CALCULATE (
        SUM ( recon_payment_fee_coverage[order_count] ),
        REMOVEFILTERS ( recon_payment_fee_coverage[payment_fee_source] ),
        recon_payment_fee_coverage[payment_fee_source] <> "__ALL__"
    )
RETURN DIVIDE ( SourceOrders, TotalSourceOrders )
```

**Format:** `0.0%` · **Spec:** §H4b

Cho biết mỗi `payment_fee_source` chiếm bao nhiêu % tổng số đơn (đã chuẩn hoá về 100%).

**REVIEW (HIGH — đã sửa). Đây là bài học `CALCULATE` quan trọng nhất của cả dự án.**

Bản gốc **không có** `KEEPFILTERS`. Nhớ lại §0.2: predicate trong `CALCULATE` **THAY THẾ** filter trên cùng cột. Diễn biến:

1. Visual đặt filter dòng hiện tại: `payment_fee_source = "api_exact"`.
2. `CALCULATE` gặp predicate `payment_fee_source <> "__ALL__"` — **cùng cột**.
3. Filter `"api_exact"` bị **XOÁ**, thay bằng `<> "__ALL__"`.
4. Tử số = tổng **mọi** source = mẫu số.
5. **Mọi dòng hiện 100%.**

Lỗi này "chạy được", không báo gì, và con số 100% trông có vẻ... đúng kiểu (nó *là* 100% của cái gì đó mà).

**`KEEPFILTERS` sửa thế nào:** nó bảo `CALCULATE` **GIAO** predicate với filter đang có thay vì đè lên. Kết quả: `payment_fee_source = "api_exact" AND payment_fee_source <> "__ALL__"` → đúng ý định.

**Còn mẫu số dùng `REMOVEFILTERS` — cố ý ngược lại:**

Mẫu số **cần** bỏ filter dòng hiện tại (để lấy tổng **mọi** source), nên `REMOVEFILTERS(…[payment_fee_source])` xoá nó đi. Rồi predicate `<> "__ALL__"` loại dòng tổng hợp ra khỏi tổng — nếu không, `'__ALL__'` (vốn đã bằng tổng các source) bị cộng vào, mẫu số **gấp đôi**, và mọi tỷ lệ chỉ còn **một nửa**.

**Tóm tắt ba hàm chỉnh filter — bảng này đáng thuộc lòng:**

| Hàm | Tác dụng lên filter đang có | Dùng khi |
|---|---|---|
| (mặc định trong `CALCULATE`) | **Thay thế** trên cùng cột | Muốn ép một giá trị bất kể visual chọn gì |
| `KEEPFILTERS(…)` | **Giao** với filter đang có | Muốn thu hẹp thêm, **giữ** lựa chọn của visual |
| `REMOVEFILTERS(…)` | **Xoá sạch** filter trên cột đó | Muốn tính tổng/mẫu số bỏ qua lựa chọn của visual |

Đúng bộ ba này là 90% các bài toán "tỷ lệ trên tổng" (percent-of-total) trong DAX.

## H-7, H-8, H-9. Ba bảng drift — **VISUAL, không phải measure**

**Spec:** §H8, §H9, §H10

| Mục | Bảng nguồn | Nội dung |
|---|---|---|
| `[CSV vs Woo Revenue Drift]` (§H8) | `recon_csv_vs_dbt_revenue` | Dòng theo site + cột delta |
| `[CSV vs dbt Profit Drift]` (§H9) | `recon_csv_vs_dbt_profit` | Lệch lợi nhuận |
| `[Woo vs CSV Shipping Charged Drift]` (§H10) | `recon_woo_vs_csv_shipping_charged` | Lệch phí ship thu khách |

**Bất biến #5 áp cho cả ba:** số CSV (`Revenue` / `Profit` / `ROI` / `Profit Margin`) **chỉ để theo dõi lệch**, **không bao giờ** là KPI chính thức. Lợi nhuận chính thức luôn là `SUM(mart_order_profit[contribution_profit_usd])`.

**Vì sao vẫn giữ các bảng này?** Vì sheet thủ công là nơi chủ shop **tự tính** lợi nhuận. Nếu số dbt lệch xa số sheet, một trong hai sai — và bạn muốn **biết** điều đó, thay vì để chủ shop tự phát hiện rồi mất niềm tin vào dashboard. Đây là **kiểm tra chéo giữa hai hệ thống độc lập**, một thực hành rất đáng mang sang dự án khác.

**Bất biến #3/#4 riêng cho §H10:** **cả hai vế** đều là phí ship thu của khách. Không vế nào là chi phí. Không cột nào trong bảng này được vào công thức profit/COGS.

## H-10. `[Woo vs CSV Shipping Drift %]`

```dax
Woo vs CSV Shipping Drift % = AVERAGE ( recon_woo_vs_csv_shipping_charged[delta_pct] )
```

**Format:** `0.0"%"` · **Spec:** §H10

Thẻ "sức khoẻ đối soát" đặt phía trên bảng chi tiết §H10 — một con số nhìn phát biết ngay hai nguồn có khớp không.

`delta_pct` **đã pre-scaled** (`-1.23` nghĩa là `-1.23%`) → format literal, không nhân 100.

**Chú ý về `AVERAGE`:** đây là **trung bình đơn giản của các delta theo dòng**, không phải delta của các tổng. Hai cái khác nhau: nếu 99 đơn lệch 0% và 1 đơn lệch 100%, `AVERAGE` ra 1% — nghe êm, nhưng thực tế có một đơn sai hoàn toàn. Đây là chỉ số "nhìn nhanh"; muốn tìm thủ phạm phải mở **bảng chi tiết** bên dưới. Đó là lý do card và bảng luôn đi cặp.

---

# Nhóm I — Khách hàng (4 measure)

*Spec: §I1–I4. Bảng: `mart_customer_summary`, `dim_customer_anonymized`.*

**Bối cảnh quan trọng (chương 03):** mọi site đều dùng **guest checkout** — không có tài khoản. Danh tính khách được dựng lại từ **email đã băm** (`SHA-256(lower(trim(email)) || PII_SALT)`). Hệ quả phải ghi lên dashboard:

- Một người dùng hai email = **hai** khách.
- Hộp thư dùng chung = **một** khách.
- Gõ sai email = tạo khách trùng lặp.

Nghĩa là mọi metric nhóm I đều là **ước lượng**, không phải sự thật tuyệt đối.

## I-1. `[Distinct Customers]`

```dax
Distinct Customers =
CALCULATE (
    DISTINCTCOUNT ( mart_customer_summary[customer_hash] ),
    dim_customer_anonymized[is_unknown_email] = FALSE ()
)
```

**Format:** `#,0` · **Spec:** §I1

Số khách **định danh được**.

**Chú ý kỹ thuật:** filter đặt trên `dim_customer_anonymized` nhưng đếm trên `mart_customer_summary` — measure này **dựa vào quan hệ** giữa hai bảng để filter lan sang. Nếu quan hệ đó chưa được nối trong Model view, filter **không có tác dụng** và measure sẽ đếm cả khách không định danh — **sai âm thầm**, không báo lỗi. Kiểm tra `BUILD_GUIDE.md` §2 khi dựng model.

**Vì sao loại `is_unknown_email`?** Các đơn không lấy được email (hoặc email rác) bị gom vào một nhóm "không xác định". Đếm chúng như khách thật sẽ **thổi phồng** số khách và **hạ thấp** repeat rate.

## I-2. `[Repeat Customer Share]`

```dax
Repeat Customer Share =
VAR RepeatCustomers =
    CALCULATE ( COUNTROWS ( mart_customer_summary ),
        mart_customer_summary[is_repeat] = TRUE () )
VAR AllCustomers = COUNTROWS ( mart_customer_summary )
RETURN DIVIDE ( RepeatCustomers, AllCustomers )
```

**Format:** `0.0%` · **Spec:** §I2

Tỷ lệ khách đã mua **hơn một lần**. `is_repeat` do dbt tính sẵn (`total_orders > 1`).

**Điểm không nhất quán nhỏ:** measure này đếm `COUNTROWS(mart_customer_summary)` **không** loại `is_unknown_email`, trong khi I-1 **có** loại. Hai measure đang nói về hai tập khách hơi khác nhau. Grain của `mart_customer_summary` là một dòng/khách nên `COUNTROWS` không sai về kỹ thuật — nhưng nếu bảng này chứa cả dòng khách không định danh thì mẫu số của I-2 rộng hơn `[Distinct Customers]`. Đáng kiểm tra khi dựng model; nếu lệch, cân nhắc dùng `[Distinct Customers]` làm mẫu số cho nhất quán.

## I-3. `[Orders per Customer]`

```dax
Orders per Customer = DIVIDE ( [Orders], [Distinct Customers] )
```

**Format:** `0.00` · **Spec:** §I3

Số đơn trung bình mỗi khách. Format `0.00` (không phải `%`, không phải `$`) — một tỷ số không đơn vị, ví dụ `1.34`.

Tái sử dụng cả hai measure gốc (§0.3) nên filter context luôn nhất quán với phần còn lại của dashboard.

## I-4. `[Repeat Revenue Share]`

```dax
Repeat Revenue Share =
VAR RepeatRevenue =
    CALCULATE ( SUM ( mart_customer_summary[total_revenue_usd] ),
        mart_customer_summary[is_repeat] = TRUE () )
VAR TotalCustomerRevenue = SUM ( mart_customer_summary[total_revenue_usd] )
RETURN DIVIDE ( RepeatRevenue, TotalCustomerRevenue )
```

**Format:** `0.0%` · **Spec:** §I4

Tỷ trọng doanh thu đến từ khách quay lại.

**REVIEW (LOW — chưa sửa, chờ chủ dự án quyết định):**

Spec §I4 ghi mẫu số là **`/ Revenue`** — tức gross revenue §A1. Nhưng measure đang chia cho `SUM(mart_customer_summary[total_revenue_usd])`, vốn là doanh thu **NET** (đã trừ refund, ~117.9k). Lệch cơ sở khoảng **~1%**.

**Vì sao không sửa ngay?** Vì không vi phạm bất biến nào (không đọc `fact_order`, không thêm ship/chi phí), và **cả hai cách đều hợp lý**:

- **Net-basis (hiện tại):** nhất quán nội bộ — tử và mẫu cùng từ một bảng, cùng grain khách. Nhưng **không khớp** với KPI `[Revenue]` ở trang khác.
- **Gross-basis (theo spec):** khớp với KPI chính, nhưng cần quan hệ khách lan được tới `fact_order_item`.

Bản gross-basis đã ghi sẵn trong file:

```dax
DIVIDE ( CALCULATE ( [Revenue], mart_customer_summary[is_repeat] = TRUE () ), [Revenue] )
```

Đây là **quyết định của chủ sở hữu metric**, không phải quyết định kỹ thuật — đúng như §L của spec quy định. Chọn xong phải ghi vào `METRIC_CHANGES.md`.

**Bài học mang đi:** khi review phát hiện chỗ mơ hồ về **định nghĩa nghiệp vụ** (chứ không phải lỗi kỹ thuật), đừng tự sửa. Ghi lại, nêu rõ hai phương án và đánh đổi, để người sở hữu metric quyết. Tự sửa = âm thầm đổi ý nghĩa con số mà không ai biết.

---

# Phụ lục A — Tra cứu hàm DAX dùng trong dự án

| Hàm | Làm gì | Ví dụ trong dự án |
|---|---|---|
| `CALCULATE` | Tính biểu thức sau khi **sửa** filter context | Hầu hết measure |
| `CALCULATETABLE` | Như `CALCULATE` nhưng trả về **bảng** | C-4 `CancelledKeys` |
| `SUM` | Cộng một cột | `[Revenue]`, `[COGS]` |
| `DISTINCTCOUNT` | Đếm giá trị **phân biệt** | `[Orders]`, `[Eligible Orders]` |
| `COUNTROWS` | Đếm **dòng** của bảng | `[Refunded Order Count]` |
| `MAX` | Lấy giá trị lớn nhất — **hoặc** lấy 1 giá trị vô hướng từ 1 dòng | `[Cost Coverage %]` |
| `AVERAGE` | Trung bình cộng | `[Woo vs CSV Shipping Drift %]` |
| `DIVIDE` | Chia **an toàn** (mẫu 0 → BLANK) | Mọi tỷ lệ |
| `VAR … RETURN` | Biến tạm — tính 1 lần, cố định context | Mọi measure nhiều bước |
| `IF` | Rẽ nhánh 2 hướng | `[Profit Visible Flag]` |
| `SWITCH(TRUE(), …)` | Chuỗi if-else if | `[Coverage Tier]` |
| `AND(a,b)` / `&&` | Và logic (`&&` nhận >2 vế) | `[Partial Coverage Chip]`, B-17 |
| `NOT` | Phủ định | `[Eligible Orders]` |
| `IN { … }` | Thuộc tập giá trị | `[Orders]` |
| `BLANK()` | Giá trị rỗng → **ẩn dòng/card** | Mọi guard và chip |
| `ISBLANK` | Kiểm tra rỗng | B-17 |
| `FORMAT` | Số → chuỗi theo format (**cũng nhân 100 với `%`**) | Các chip |
| `&` | Nối chuỗi | Các chip |
| `VALUES` | Danh sách giá trị phân biệt của cột (dạng bảng) | G-2, C-4 |
| `DISTINCT` | Khử trùng một bảng | C-4 |
| `UNION` | Hợp hai bảng (**cần cùng lineage**) | C-4 |
| `TREATAS` | **Gán lại lineage** — bắc cầu filter qua bảng khác | G-2, C-4 |
| `KEEPFILTERS` | **Giao** predicate với filter đang có | H-6 tử số |
| `REMOVEFILTERS` | **Xoá** filter trên cột | H-6 mẫu số |
| `DATEADD` | Dịch tập ngày (**cần marked date table + ngày liên tục**) | 4 measure MoM |

---

# Phụ lục B — Các REVIEW còn tồn

| Measure | Mức | Tình trạng | Nội dung |
|---|---|---|---|
| `[Quantity Sold]` | HIGH | ✅ Đã sửa trong DAX | Nhưng **spec §A4 chưa cập nhật** — doc drift, cần sửa |
| `[Revenue per Country]` | HIGH | ✅ Đã sửa | `TREATAS` thay cho reuse trần |
| `[Payment Fee Source Share]` | HIGH | ✅ Đã sửa | `KEEPFILTERS` |
| `[Shipping Charged Ratio by Country]` | MEDIUM | ❌ **Chưa có measure** | Công thức đã ghi sẵn, cần tạo — xem G-4 |
| `[Refunded Order Count]` | LOW | ⏸️ Giữ nguyên có chủ ý | Đếm dòng ≠ đếm đơn; hiện trùng (34=34) |
| `[Repeat Revenue Share]` | LOW | ⏸️ Chờ chủ dự án | Net-basis vs gross-basis, lệch ~1% |

**Ngoài ra (phát hiện khi viết chương này):**

- **`[Orders]` vs `[Revenue]` lệch population** — `on-hold`/`refunded` xử lý khác nhau, làm AOV chia hai tập hơi lệch. Đúng spec, không phải bug, nhưng cần biết khi diễn giải (xem A-3).
- **`[Repeat Customer Share]` không loại `is_unknown_email`** trong khi `[Distinct Customers]` có loại (xem I-2).

---

# Khái niệm áp dụng được (mang sang dự án BI khác)

Đây là phần đáng giá nhất của chương. Tám nguyên tắc rút ra, **không phụ thuộc** vào dự án này:

**1. Số đo chỉ tồn tại ở đúng một chỗ, ở đúng grain của nó.**
Xoá cột khỏi bảng có grain thô hơn thay vì tin vào kỷ luật. Cấu trúc mạnh hơn quy ước. → A-1

**2. Logic nghiệp vụ thuộc tầng transform, không thuộc tầng BI.**
DAX chỉ nên tổng hợp, chia tỷ lệ, và trình bày. Công thức nghiệp vụ nằm ở dbt, có test bảo vệ. Thấy mình viết công thức phức tạp bằng DAX → hỏi "cái này có nên ở dbt không?". → B-6

**3. Tử số và mẫu số phải cùng population.**
Lớp lỗi khó thấy nhất trong BI: mỗi measure tách riêng đều đúng, chỉ khi chia nhau mới sai. → A-4, B-10, C-3, G-5

**4. Mẫu số phải là tập có khả năng xảy ra sự kiện đang đo.**
Coverage báo thấp → hỏi *"mẫu số có đúng không?"* trước khi kết luận *"dữ liệu thiếu"*. → B-10, C-3

**5. Lưu nguồn gốc ngay cạnh giá trị.**
Cột `*_source` cho phép dashboard tự nói "số này ước lượng X%" thay vì im lặng giả vờ chính xác. → B-2

**6. Chất lượng dữ liệu phải là hành vi, không phải tài liệu.**
Encode quy tắc thành measure và để hệ thống tự thi hành (data-driven visibility), thay vì viết vào tài liệu rồi hy vọng người ta nhớ. → B-12, B-13

**7. Chốt cỡ mẫu cho mọi trung bình/tỷ lệ theo nhóm nhỏ.**
Khác biệt giữa dashboard nghiệp dư và dashboard dùng được: cái sau biết **giấu cái không đáng tin**. → G-3, G-5

**8. Chỗ mơ hồ về nghiệp vụ thì ghi lại, không tự sửa.**
Sửa lỗi kỹ thuật: cứ làm. Đổi ý nghĩa metric: phải là quyết định của chủ sở hữu metric, và phải vào changelog. → C-1, I-4

---

## Đọc tiếp

- **Chương 09** — `09-truc-quan-hoa-powerbi.md`: khái niệm semantic model, quan hệ, gating ở mức tổng quan.
- **Chương 08** — `08-chat-luong-va-kiem-dinh.md`: coverage và gating ở tầng dbt (nguồn của nhóm B nửa sau).
- **Chương 07b** — `07b-schema-marts-core.md`: từ điển từng cột của các bảng mà measure đọc.
- **`powerbi/BUILD_GUIDE.md`** — các bước dựng dashboard thực tế (đổi tên bảng, mark as date table, quan hệ).
- **`docs/METRICS_DEFINITION.md`** — spec chính thức (tiếng Anh), nguồn của mọi §-reference ở chương này.
