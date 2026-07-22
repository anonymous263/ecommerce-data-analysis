# 12 — Format DAX chuẩn SQLBI: viết công thức đọc được như văn xuôi

> Chương này giải thích **bộ quy tắc format DAX của SQLBI** (Marco Russo & Alberto Ferrari —
> nhóm tác giả uy tín nhất về DAX, người xây [daxformatter.com](https://www.daxformatter.com)),
> vì sao từng quy tắc tồn tại, và áp dụng lên **chính các measure thật** của project này.
> Toàn bộ 66 measures trong `_Measures` + 25 UDF trong `powerbi/measures/udf_period_delta.txt`
> đã được reformat theo chuẩn này (2026-07-22).
>
> Tài liệu gốc: [Rules for DAX code formatting — SQLBI](https://www.sqlbi.com/articles/rules-for-dax-code-formatting/)

---

## 1. Vì sao phải format DAX?

DAX không nhạy cảm với khoảng trắng — engine chạy `CALCULATE(SUM(x),y=1)` y hệt
`CALCULATE ( SUM ( x ), y = 1 )`. Vậy format để làm gì?

1. **Đọc để tìm lỗi.** 90% thời gian với một measure là *đọc lại* nó (khi số sai, khi
   review, khi 6 tháng sau quên sạch). Công thức format tốt cho phép mắt "quét cấu trúc"
   trước khi đọc chi tiết: hàm nào bọc hàm nào, có mấy đối số, filter nằm ở đâu.
2. **So sánh được.** Hai measure cùng format thì diff (git, so mắt thường) chỉ ra đúng
   phần khác nhau về *logic*, không nhiễu vì khác *trình bày*.
3. **Chuẩn chung của cộng đồng.** Code mẫu trong sách SQLBI, DAX Guide, các blog lớn đều
   theo chuẩn này — quen mắt với nó là đọc được tài liệu của cả hệ sinh thái.

> **Nguyên tắc gốc mà mọi rule bên dưới phục vụ:** *người đọc phải nhận ra CẤU TRÚC của
> biểu thức trước khi đọc nội dung của nó.*

---

## 2. Bộ quy tắc — từng rule, kèm lý do

### Rule 1 — Space trước dấu mở ngoặc của hàm, space quanh đối số

```dax
-- ĐÚNG
SUM ( fact_order_item[quantity] )

-- SAI
SUM(fact_order_item[quantity])
```

Tên hàm cách `(` một space; bên trong ngoặc, đối số cách hai đầu ngoặc một space.
**Lý do:** tách "tên hàm" khỏi "khối đối số" — khi các hàm lồng nhau 3–4 tầng, chuỗi
`))))` dính liền không cho biết ngoặc nào đóng hàm nào; `) ) ) )` có space cũng không
tốt hơn — cách chữa thật sự là rule 4 (xuống dòng), nhưng space giúp trường hợp một dòng.

Áp dụng cho cả hàm **không đối số**: `TRUE ()`, `BLANK ()`, `TODAY ()` — vẫn có space.

### Rule 2 — Cột LUÔN kèm tên bảng; measure KHÔNG BAO GIỜ kèm tên bảng

```dax
-- ĐÚNG
SUM ( fact_order_item[line_revenue_usd] )     -- cột: có bảng
DIVIDE ( [Revenue], [Paid Orders] )           -- measure: chỉ [tên]

-- SAI
SUM ( [line_revenue_usd] )                    -- cột "mồ côi" — bảng nào?
DIVIDE ( _Measures[Revenue], ... )            -- measure kèm bảng — thừa và gây hiểu nhầm
```

**Lý do:** đây là quy tắc *ngữ nghĩa* quan trọng nhất. Nhìn `x[y]` → biết ngay là **cột**
(giá trị thay đổi theo dòng, cần row context). Nhìn `[y]` trần → biết ngay là **measure**
(tự mang CALCULATE ngầm, có context transition). Đọc công thức người khác mà không phân
biệt được 2 loại này là nguồn bug lớn nhất trong DAX.

### Rule 3 — Biểu thức ngắn thì MỘT dòng, dài thì xuống dòng

Nếu toàn bộ biểu thức nằm gọn một dòng dễ đọc (SQLBI không cứng nhắc số ký tự, thực dụng
~80–100) — giữ một dòng:

```dax
AOV =
DIVIDE ( [Revenue], [Paid Orders] )
```

Không "trải" một biểu thức ngắn ra 5 dòng cho có vẻ nghiêm túc. Ngược lại, đã phải xuống
dòng thì xuống **cho đủ cấu trúc** theo rule 4 — không xuống nửa vời.

### Rule 4 — Khi xuống dòng: mỗi đối số một dòng, thụt 4 spaces, đóng ngoặc thẳng cột với tên hàm

Đây là rule "xương sống". Mẫu chuẩn:

```dax
Quantity Sold =
CALCULATE (
    SUM ( fact_order_item[quantity] ),
    fact_order_item[is_revenue_status] = TRUE ()
)
```

Phân tích từng chi tiết:

- `CALCULATE (` — tên hàm + ngoặc mở **ở cuối dòng**, không có gì phía sau.
- Mỗi đối số một dòng, thụt **4 spaces** so với tên hàm.
- Dấu phẩy nằm **cuối dòng** của đối số trước (không đầu dòng đối số sau).
- `)` đóng **thẳng cột với chữ C của CALCULATE** — mắt dò dọc theo cột là thấy ngay
  ngoặc này đóng cho hàm nào. Đây chính là thứ chuỗi `))))` không làm được.

Lồng nhiều tầng thì lặp lại quy tắc ở từng tầng:

```dax
Lapsed Share =
DIVIDE (
    CALCULATE (
        COUNTROWS ( mart_customer_summary ),
        mart_customer_summary[Recency Segment] = "Lapsed 12+mo"
    ),
    [Distinct Customers]
)
```

Đọc "quét cấu trúc": `DIVIDE` có 2 đối số → tử là một `CALCULATE` (đếm khách lapsed),
mẫu là `[Distinct Customers]`. Chưa cần đọc nội dung đã hiểu hình dạng.

### Rule 5 — Toán tử có space hai bên; toán tử ở ĐẦU dòng khi phải ngắt

```dax
-- ĐÚNG
[COGS] + [Design Fee] + [Payment Fee]
dim_date[date_day] >= CM1 && dim_date[date_day] <= CM2

-- Khi biểu thức toán tử quá dài, ngắt TRƯỚC toán tử:
Total Cost =
[COGS]
    + [Design Fee]
    + [Payment Fee]
```

**Lý do ngắt trước toán tử:** dòng bắt đầu bằng `+` báo ngay "tôi là phần nối tiếp",
không thể đọc nhầm thành một biểu thức mới. (Measure `Total Cost` của project đủ ngắn
nên giữ một dòng.)

### Rule 6 — `VAR` / `RETURN`

```dax
Cumulative Revenue =
VAR CurrentRevenue = [Revenue]
RETURN
    CALCULATE (
        [Revenue],
        FILTER (
            ALLSELECTED ( dim_product[product_name] ),
            [Revenue] >= CurrentRevenue
        )
    )
```

- Mỗi `VAR` một dòng; gán ngắn thì cùng dòng (`VAR CurrentRevenue = [Revenue]`),
  gán dài thì biểu thức xuống dòng thụt 4 spaces dưới tên biến.
- `RETURN` đứng **một mình một dòng**, thẳng cột với `VAR`.
- Biểu thức sau `RETURN` thụt 4 spaces.
- **Đặt tên biến có nghĩa** — project vừa đổi `VAR cur` → `VAR CurrentRevenue` chính vì
  rule này: biến là "tài liệu miễn phí", đừng lãng phí bằng tên 3 chữ cái.

**Vì sao nên dùng VAR nhiều:** ngoài dễ đọc, VAR chỉ tính **một lần** và "đóng băng" giá
trị tại context lúc khai báo — vừa nhanh hơn vừa tránh bug context transition. Trong
`Cumulative Revenue`, `CurrentRevenue` phải là VAR: nếu viết `[Revenue] >= [Revenue]`
trong FILTER thì vế phải bị tính lại theo từng dòng của ALLSELECTED — sai hoàn toàn logic
Pareto.

### Rule 7 — Viết HOA tên hàm và từ khóa

`CALCULATE`, `SUM`, `VAR`, `RETURN`, `TRUE ()` — luôn HOA. Tên bảng/cột giữ nguyên như
trong model (project này dùng snake_case: `fact_order_item[line_revenue_usd]`).

### Rule 8 — Tên measure ở dòng đầu, biểu thức bắt đầu từ dòng mới

```dax
Revenue =
CALCULATE (
    SUM ( fact_order_item[line_revenue_usd] ),
    fact_order_item[is_revenue_status] = TRUE ()
)
```

**Lý do:** mọi measure đều bắt đầu biểu thức ở cùng một cột (cột 0) — dán 66 measures
cạnh nhau vẫn thẳng hàng, không phụ thuộc tên measure dài hay ngắn. (Với measure một
dòng như `AOV` ở rule 3, xuống dòng sau `=` vẫn được ưu tiên trong project này để đồng
nhất.)

---

## 3. Trước / Sau — chính measure của project

### Ví dụ 1: sai kiểu "thụt lung tung"

```dax
-- TRƯỚC (thụt đầu dòng ngẫu nhiên, không space sau tên hàm, đóng ngoặc lơ lửng)
Quantity Sold = CALCULATE(
            SUM(fact_order_item[quantity]),
            fact_order_item[is_revenue_status] = TRUE()
        )

-- SAU
Quantity Sold =
CALCULATE (
    SUM ( fact_order_item[quantity] ),
    fact_order_item[is_revenue_status] = TRUE ()
)
```

Lỗi của bản "trước": (1) biểu thức bắt đầu ngay sau `=` nên mức thụt phụ thuộc độ dài
tên measure; (2) `CALCULATE(` `SUM(` `TRUE()` dính liền; (3) `)` cuối thụt 8 spaces —
không thẳng với bất cứ thứ gì, mắt không dò được nó đóng cho hàm nào.

### Ví dụ 2: hàm lồng 3 tầng

```dax
-- TRƯỚC (một dòng — đọc được nhưng phải "đếm ngoặc" bằng mắt)
Revenue per Country = CALCULATE ( [Revenue], TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] ) )

-- SAU (cấu trúc lộ ra: CALCULATE có 2 đối số, TREATAS là filter)
Revenue per Country =
CALCULATE (
    [Revenue],
    TREATAS ( VALUES ( fact_order[order_sk] ), fact_order_item[order_sk] )
)
```

Chú ý: `TREATAS ( ... )` bên trong **vẫn giữ một dòng** vì nó ngắn — rule 3 áp dụng đệ
quy ở từng tầng, không phải "đã xuống dòng thì mọi thứ phải xuống dòng".

### Ví dụ 3: DIVIDE hai vế dài

```dax
-- SAU
Payment Fee Rate =
DIVIDE (
    SUM ( fact_order[payment_fee_usd] ),
    SUM ( fact_order[order_total_usd] )
)
```

Tử và mẫu mỗi vế một dòng — nhìn phát biết ngay "phí chia tổng giá trị đơn".

---

## 4. Format cho UDF (user-defined function)

UDF (preview 2025) thêm cú pháp `FUNCTION ... => ...`. Chuẩn project này
(xem `powerbi/measures/udf_period_delta.txt`):

```dax
FUNCTION MoM_Perc = ( _measure : expr ) =>
    VAR MaxD = Last_Data_Date ( _measure )
    VAR CM1  = DATE ( YEAR ( MaxD ), MONTH ( MaxD ), 1 )
    VAR CM2  = EOMONTH ( MaxD, 0 )
    VAR PM1  = EOMONTH ( MaxD, -2 ) + 1
    VAR PM2  = EOMONTH ( MaxD, -1 )
    VAR CM   = CALCULATE ( _measure, FILTER ( ALL ( dim_date[date_day] ), dim_date[date_day] >= CM1 && dim_date[date_day] <= CM2 ) )
    VAR PM   = CALCULATE ( _measure, FILTER ( ALL ( dim_date[date_day] ), dim_date[date_day] >= PM1 && dim_date[date_day] <= PM2 ) )
    RETURN DIVIDE ( CM - PM, PM, BLANK () )
```

Quy ước:

- Header `FUNCTION Tên = ( _thamso : kiểu ) =>` một dòng; thân hàm thụt 4 spaces.
- Tham số đặt tên có tiền tố `_` (`_measure`, `_value`) — phân biệt với measure/cột thật.
- Các `VAR` **canh thẳng dấu `=`** (`MaxD`, `CM1`, `CM2`... cùng cột) — khi một hàm có
  5–7 VAR cùng dạng, canh cột biến chúng thành "bảng tra" đọc rất nhanh. Đây là ngoại lệ
  thẩm mỹ được chấp nhận cho nhóm VAR ngắn cùng chủ đề.
- Trong file toolkit, các dòng `VAR CM = CALCULATE ( ... FILTER ... )` để một dòng dù dài
  — đánh đổi có chủ đích: 8 hàm cùng khuôn, giữ mỗi VAR một dòng giúp **so sánh dọc**
  giữa các hàm (MoM vs YoY chỉ khác đúng 4 dòng VAR). Nếu viết measure đơn lẻ, hãy
  xuống dòng đầy đủ theo rule 4.

---

## 5. Công cụ — đừng format bằng tay

| Công cụ | Cách dùng |
|---|---|
| **daxformatter.com** | Dán DAX → Format. Chính SQLBI vận hành; là "trọng tài" khi tranh cãi format. Chọn *Long line* (mỗi đối số một dòng) hoặc *Short line*. |
| **DAX query view** (Power BI Desktop) | Chuột phải → **Format query**, hoặc `Shift+Alt+F` — dùng đúng engine của daxformatter. |
| **Tabular Editor** | Chọn measure → Format DAX (tích hợp daxformatter API); format hàng loạt bằng script C#. |
| **Formula bar** | `Shift+Enter` xuống dòng thủ công — chỉ dùng khi chỉnh nhỏ. |

> **Mẹo thực dụng:** viết logic trước, đúng số trước — rồi format cuối cùng bằng công cụ.
> Đừng vừa nghĩ logic vừa canh space.

---

## 6. Checklist khi review một measure

- [ ] Tên hàm HOA + space trước `(`; `TRUE ()` / `BLANK ()` có space?
- [ ] Cột có tên bảng, measure không có tên bảng?
- [ ] Ngắn → một dòng; dài → mỗi đối số một dòng, thụt 4 spaces?
- [ ] Dấu `)` đóng thẳng cột với tên hàm mở nó?
- [ ] `VAR` tên có nghĩa; `RETURN` một mình một dòng?
- [ ] Ngắt dòng biểu thức toán tử → toán tử đầu dòng?
- [ ] Biểu thức bắt đầu ở dòng mới sau `Tên =`?

---

## 7. Khái niệm áp dụng được (cho dự án khác)

1. **Format là công cụ đọc-cấu-trúc, không phải thẩm mỹ.** Mọi rule đều trả lời: "mắt
   tìm thấy gì nhanh hơn?" — áp dụng tư duy này cho cả SQL (dbt style guide) và Python (PEP 8).
2. **Quy tắc `table[column]` vs `[measure]`** là rule ngữ nghĩa đáng giá nhất của DAX —
   enforce nó trong code review.
3. **VAR = tài liệu + hiệu năng + chốt context.** Ba lý do trong một từ khóa.
4. **Dùng máy format, người review logic.** daxformatter/`Shift+Alt+F` cho format;
   con người dành thời gian cho grain, filter context, và dân số tử/mẫu (xem chương 11).
5. **Đồng nhất > tối ưu cục bộ.** Một file 66 measures cùng khuôn đọc nhanh hơn 66
   measures mỗi cái "đẹp kiểu riêng".
