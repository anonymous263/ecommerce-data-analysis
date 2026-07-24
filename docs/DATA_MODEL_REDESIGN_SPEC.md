# Data Model Redesign Spec — Conformed Dimensions & Grain-Correct Facts

> **Status: PROPOSAL (chờ duyệt).** Chưa sửa `DATA_MODEL.md`, `CAPSTONE_BUILD_GUIDE.md`, hay model dbt. Tài liệu này mô tả *sẽ đổi gì* để một slicer bất kỳ (country, customer, product, payment…) lan truyền đúng trên mọi page, và xoá họ measure "per-dimension" + các TREATAS workaround.
> **Ngày:** 2026-07-24 · **Người duyệt:** owner-analyst · **Áp dụng khi:** cập nhật docs ngay; sửa model dbt khi resume Phase 2.

---

## 1. Vấn đề (evidence từ chính repo)

Model hiện tại nối `dim` tới `fact` **không đủ**: mỗi conformed dimension chỉ chạm 1–2 fact, trong khi các đại lượng chính nằm ở fact khác.

`CAPSTONE_BUILD_GUIDE.md §1.3b` liệt kê thẳng hiện trạng — bảng nào **không** cắt được theo dim nào:

| Bảng | Cắt được | **KHÔNG** cắt được |
|---|---|---|
| `fact_order_item` (revenue) | date, site, product | **country, customer, payment** |
| `mart_order_profit` (profit) | date, site | **country, customer, payment**, product |
| `mart_product_profit` | date, site, product | country, customer, payment |
| `fact_refund` | date | country, customer, payment |

**Hệ quả đang phải gánh** (đều nằm trong guide):

1. **TREATAS virtual-relationship** để mượn filter qua `order_sk`:
   - `Revenue per Country = CALCULATE([Revenue], TREATAS(VALUES(fact_order[order_sk]), fact_order_item[order_sk]))` (§2.6a)
   - `Method Payment Fee = CALCULATE(SUM(mart_order_profit[payment_fee_usd]), TREATAS(VALUES(fact_order[order_sk]), mart_order_profit[order_sk]))` (§2.6f)
2. **Cả một họ measure "per-dimension"** chỉ để vượt quan hệ thiếu: `Revenue per Country`, `Country Profit`, `Country Net Revenue`, `Country Margin`, `Country Orders`, `AOV per Country` … (§2.6, §2.9d).
3. **Bẫy "không báo lỗi"** (guide tự cảnh báo là *nguồn lỗi số 1*): đặt measure lên dim không quan hệ → Power BI trả **grand-total giống nhau mọi dòng**, dễ tưởng đúng.
4. `[Refund Rate]` **bị loại khỏi tooltip Market** vì `fact_refund` không nối `dim_country`.

Đây là triệu chứng của **FK thiếu ở fact grain**, không phải bản chất Kimball.

---

## 2. Nguyên tắc thiết kế

### 2.1 Hai loại "không cắt được" — xử lý ngược nhau

- **Loại A — FK thiếu (SỬA: đẩy key xuống grain).** Order chỉ có *một* country / customer / payment / date → mọi fact order-grain & line-grain *nên* mang đủ các FK đó, kế thừa từ order lúc build. Đây là chuyện bình thường của Kimball ("fact mang FK tới mọi dim cần để phân tích measure của nó").
- **Loại B — grain không cho phép (KHÔNG sửa bằng FK).** Một order chứa *nhiều* product → không có `product_sk` ở order grain. Snapshot lifetime (`mart_customer_summary`) không cắt theo date. Funnel cần đơn failed/cancelled → phải đọc `fact_order` (mart không chứa). Các case này giữ nguyên — dùng đúng fact ở đúng grain.

### 2.2 Ba quy tắc

1. **Trong cùng một grain, mọi fact mang đủ bộ conformed key.** Order-grain: `{date, site, country, customer, payment}`. Line-grain: bộ trên **+ product**.
2. **Product chỉ ở line grain.** Mọi measure "by product" đọc line-grain fact (`fact_order_item` / `mart_product_profit`). Order-grain "by product" = bất khả → đây chính là lý do tồn tại 2 mart profit.
3. **Base measure viết một lần, đọc đúng-grain fact.** Không nhân bản "per country / per product / per method".

### 2.3 Degenerate & role-playing

- **Order = degenerate dimension.** Không tạo `dim_order`. `order_sk` / `woo_order_id` / `order_natural_key` cưỡi trên fact — đúng chuẩn.
- **Status = degenerate/junk.** Giữ dạng cột trên fact; tuỳ chọn copy `order_status` xuống line grain nếu cần "revenue completed vs refunded".
- **Date = role-playing** (order/ship/deliver/refund) trỏ chung một `dim_date` — giữ nguyên, dùng `USERELATIONSHIP` cho vai phụ.

---

## 3. Ma trận FK đích (BEFORE → AFTER)

`✅` có · `✅*` native/degenerate · `➕` **THÊM** · `—` grain N/A · `attr` thuộc tính snapshot (inactive)

> **Quyết định đã chốt (2026-07-24):** FK "tuỳ chọn" → **đưa hết vào** (full). `mart_country_profit` → **bỏ hẳn**. Ship-to country → **không** (chỉ billing). Ma trận dưới đã áp quyết định.

| Fact (grain) | date | site | country | customer | product | payment | status |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **fact_order_item** (line) | ✅ | ✅ | ➕ | ➕ | ✅* | ➕ | ➕ |
| **mart_product_profit** (line) | ✅ | ✅ | ➕ | ➕ | ✅* | ➕ | ➕ |
| **fact_order** (order) | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅* |
| **mart_order_profit** (order) | ✅ | ✅ | ➕ | ➕ | — | ➕ | ➕ |
| **fact_refund** (order) | ✅ | ➕ | ➕ | ➕ | — | ➕ | ✅* |
| **fact_order_cost** (order) | ✅ | ✅ | ➕ | ➕ | — | ➕ | — |
| **fact_fulfillment** (order, P5) | ✅ | ➕ | ➕ | ➕ | — | — | ✅* |
| **mart_customer_summary** (customer snapshot) | — | ✅ | attr | ✅* | — | — | — |
| ~~mart_country_profit~~ | **BỎ HẲN** — country đọc trực tiếp `mart_order_profit` (đã có `country_sk`) | | | | | | |

**Tổng FK cần thêm:** country ×6 · customer ×6 · payment ×5 · site ×2 · status ×4.

---

## 4. Thay đổi từng fact (nguồn dẫn FK trong dbt)

Tất cả FK mới đều **kế thừa từ `fact_order`** qua `order_sk` (join sẵn có trong staging) — không cần nguồn dữ liệu mới.

| Fact | FK thêm | Cách dẫn (dbt) |
|---|---|---|
| `fact_order_item` | `country_sk`, `customer_sk`, `payment_method_sk`, `order_status` (degenerate) | `LEFT JOIN fact_order USING (order_sk)` ở staging, `SELECT` các key |
| `mart_order_profit` | `country_sk`, `customer_sk`, `payment_method_sk`, `order_status` | Mart đã join order-level → thêm cột vào `SELECT` |
| `mart_product_profit` | `country_sk`, `customer_sk`, `payment_method_sk`, `order_status` | Kế thừa từ order khi allocate cost xuống line |
| `fact_refund` | `country_sk`, `customer_sk`, `site_sk`, `payment_method_sk` | Join `fact_order` trên `order_sk` |
| `fact_order_cost` | `country_sk`, `customer_sk`, `payment_method_sk` | Join `fact_order` trên `order_sk` |
| `fact_fulfillment` (P5) | `country_sk`, `customer_sk`, `site_sk` | Join `fact_order` trên `order_sk` |

> **Lưu ý allocation:** `mart_product_profit` đã allocate cost order→line theo revenue-share (DATA_MODEL §4.3). Việc thêm FK không đụng logic allocation — chỉ mang thêm dimension context xuống line. `SUM(line_profit_usd)` vẫn khớp `mart_order_profit` tới cent.

---

## 5. Quan hệ Power BI (BEFORE → AFTER)

**BEFORE** (guide §1.3): `dim_country → {fact_order, mart_country_profit}` · `dim_payment_method → {fact_order}` · `dim_customer → {fact_order, mart_customer_summary}`.

**AFTER** — mỗi dim nối **thẳng** tới mọi fact ở grain phù hợp, tất cả **1:\*, single-direction, active**:

| Dim (one) | Facts (many) — AFTER |
|---|---|
| `dim_date` | fact_order, fact_order_item, fact_refund, fact_order_cost, mart_order_profit, mart_product_profit *(role-playing: refund date qua quan hệ phụ inactive)* |
| `dim_country` | fact_order, **fact_order_item**, **mart_order_profit**, **mart_product_profit**, **fact_refund**, **fact_order_cost** |
| `dim_customer_anonymized` | fact_order, **fact_order_item**, **mart_order_profit**, **mart_product_profit**, **fact_refund**, **fact_order_cost**, mart_customer_summary |
| `dim_product` | fact_order_item, mart_product_profit |
| `dim_payment_method` | fact_order, **mart_order_profit**, **fact_order_item**, **mart_product_profit**, **fact_refund**, **fact_order_cost** |
| `dim_site` | fact_order, fact_order_item, mart_order_profit, **fact_refund**, mart_product_profit |

> `mart_country_profit` đã **bỏ** — không còn quan hệ nào tới nó.

Đậm = quan hệ **mới**. Không bidirectional, không fact-to-fact, không dùng `order_sk` làm cầu nối filter.

---

## 6. Thay đổi measure (BEFORE → AFTER)

### 6.1 XOÁ — clone chỉ tồn tại vì FK thiếu (dùng base measure thay thế)

| Measure xoá | Thay bằng (base, đã có) | Ghi chú |
|---|---|---|
| `Revenue per Country` | `[Revenue]` + `dim_country` trên trục | hết TREATAS |
| `Country Profit` | `[Contribution Profit]` | đọc mart_order_profit (đã có country_sk) |
| `Country Net Revenue` | `[Profit Base Net Revenue]` | |
| `Country Margin` | `[Profit Margin]` | |
| `Country Orders` | `[Paid Orders]` | |
| `AOV per Country` | `[AOV]` | |
| `Method Payment Fee` | `[Payment Fee]` + `dim_payment_method` trên trục | hết TREATAS |

→ `mart_country_profit` **BỎ HẲN** (quyết định 2026-07-24): country đọc trực tiếp `mart_order_profit` (đã có `country_sk`). Xoá khỏi grain table, relationships, danh mục mart, và mọi tham chiếu measure.

### 6.2 VIẾT LẠI — giữ measure nhưng bỏ tham chiếu per-country

| Measure | Sửa |
|---|---|
| `Revenue Share` | thay `[Revenue per Country]` → `[Revenue]` |
| `Top Market Name` | thay `[Revenue per Country]` → `[Revenue]` |
| `Best Margin Major Market` | `[Revenue per Country]`→`[Revenue]`, `[Country Margin]`→`[Profit Margin]` |
| `International Share` | `[Revenue per Country]` → `[Revenue]` |

### 6.3 GIỮ NGUYÊN — đúng grain/scope, KHÔNG phải smell

| Measure / họ | Vì sao giữ |
|---|---|
| `Product Profit`, `Product Net Revenue`, `Product Margin` (§2.5b) | **Loại B**: profit-by-product chỉ có ở line grain + cost allocation. Khác `[Contribution Profit]` (số exact, order grain). Hai measure là **đúng thiết kế 2-mart**. |
| `Order Attempts`, `Method Approval Rate`, `Method Lost`, `Failed/Cancellation Rate`, `Open Backlog` | Đọc `fact_order` **mọi status** (gồm failed/cancelled) — mart không chứa. **Scope boundary**, giữ trên fact_order. |
| `Distinct Customers`, `Repeat Rate`, `Orders per Customer`, `LTV`, `Seg *` | Snapshot lifetime — non-additive theo date là **đúng bản chất**. |
| `Markets Served = DISTINCTCOUNT(fact_order[country_sk])` | Count thuần, giữ. |

### 6.4 CASE ĐẶC BIỆT — `Country Repeat %`

`Country Repeat %` (§2.9d) tính "khách có ≥2 đơn paid **trong nước đang xét**". Đây là giao **customer-lifetime × country** — một khách có thể mua từ nhiều nước, nên "repeat theo country" có **định nghĩa semantic**, không chỉ là FK thiếu.

- **Quyết định cần chốt:** (a) giữ công thức hiện tại trên `fact_order` (repeat = ≥2 đơn *trong nước đó*), hay (b) định nghĩa lại "repeat customer" ở cấp toàn cửa hàng rồi gán về country billing đầu tiên. Khuyến nghị **(a)** — sát ý "thị trường nào khách chịu quay lại". Giữ measure, ghi rõ định nghĩa.

---

## 7. Quyết định thiết kế (CHỐT 2026-07-24)

1. **Geography — billing vs shipping.** ✅ **Chỉ billing** (giữ nguyên 1 `country_sk` = billing). Ship-to country **không** đưa vào lần này; để lại cho Phase sau nếu audit Phase 1 xác nhận shipping country land ở raw.
2. **Status xuống line grain.** ✅ **Có** — copy `order_status` (degenerate) xuống `fact_order_item` + `mart_product_profit` để cắt "revenue/profit completed vs refunded" ở line.
3. **Payment method xuống refund/item.** ✅ **Đầy đủ** — `payment_method_sk` xuống `fact_order_item`, `mart_product_profit`, `fact_refund`, `fact_order_cost` (không chỉ `mart_order_profit`).
4. **`mart_country_profit`.** ✅ **Bỏ hẳn** — country đọc trực tiếp `mart_order_profit`. Xoá khỏi grain table (§2 DATA_MODEL), mart list (§7.3 DATA_MODEL & §1.1 guide), relationships, và measure family.
5. **`Country Repeat %`** (case §6.4): giữ định nghĩa hiện tại (repeat = ≥2 đơn paid *trong nước đó*, tính trên `fact_order` có cả country+customer), ghi rõ định nghĩa. *(Xác nhận theo khuyến nghị (a).)*

---

## 8. Kế hoạch triển khai

| Bước | Nội dung | Trạng thái |
|---|---|---|
| 0 | Duyệt spec này + chốt mục §7 | ⬜ chờ owner |
| 1 | Cập nhật `docs/DATA_MODEL.md` (§6 FK theo grain, §8 sơ đồ quan hệ, §5/§9 ghi chú degenerate/role-playing) | ⬜ |
| 2 | Cập nhật `CAPSTONE_BUILD_GUIDE.md` (§1.3 quan hệ mới, §1.3b viết lại, §2.6 xoá TREATAS+country family, §2.9d/f sửa) | ⬜ |
| 3 | Ghi `docs/METRIC_CHANGES.md`: danh sách measure xoá/viết-lại + lý do | ⬜ |
| 4 | *(Khi resume Phase 2)* sửa staging/mart dbt: thêm FK, thêm test `relationships` cho mỗi FK mới | ⬜ hoãn |

> **Nguyên tắc an toàn:** pipeline dbt đang *paused* cho capstone → Bước 1–3 (docs) làm ngay để capstone build đúng từ đầu; Bước 4 (model thật) chờ resume. Không có thay đổi phá vỡ nào ở dữ liệu hiện có — chỉ **thêm cột FK** (không đổi grain, không đổi measure số học của base).

---

## 9. Tác động tóm tắt

- **Xoá:** 7 clone measure + **2 TREATAS**. **Viết lại:** 4 measure ranking/share. **Giữ:** toàn bộ product family, funnel family, customer-snapshot family (đúng grain).
- **Kết quả:** một `dim_country` / `dim_customer` / `dim_payment_method` chung → **một slicer lan truyền mọi page**; `[Refund Rate]` cắt được theo nước; hết bẫy grand-total âm thầm; model đọc đúng "star" chuẩn Kimball.
- **Chi phí:** vài `LEFT JOIN … USING(order_sk)` trong dbt (một lần build). Không thêm nguồn dữ liệu.
