# 06 — Marts: Biến đổi & Tổng hợp

> Đọc trước: chương 04 (`04-mo-hinh-hoa-kimball.md`) để nắm fact/dim/grain, và
> chương 05 (`05-staging-lam-sach-chuan-hoa.md`) để biết `staging` đã làm sạch
> gì trước khi tới đây. Nguồn đối chiếu: `dbt/models/marts/**`,
> `docs/DATA_MODEL.md` (§3, §4), `CLAUDE.md` ("Non-negotiable domain rules"),
> `docs/METRICS_DEFINITION.md`.

## Lớp `marts` là gì, và vì sao nó khác `staging`

`staging` trả lời câu hỏi "dữ liệu thô này, làm sạch rồi, trông như thế nào?"
— nó ép kiểu, đổi tiền tệ, băm PII, nhưng **chưa** áp bất kỳ logic kinh doanh
nào (không cộng, không phân bổ chi phí, không tính lợi nhuận).

`marts` trả lời câu hỏi khác hẳn: "công ty này có lãi không, ở đâu, bao
nhiêu?" Đây là lớp mà mọi **logic nghiệp vụ** (business logic) sống — công
thức lợi nhuận, cách xử lý hoàn tiền, cách phân bổ chi phí xuống từng dòng
sản phẩm. Trong dự án này, `marts` được chia làm 4 nhóm, mỗi nhóm một schema
Postgres riêng:

| Schema | Vai trò | Model chính |
|---|---|---|
| `marts_core` | Fact + dimension "sạch, đã join" cho đơn hàng/sản phẩm/khách hàng, và các mart lợi nhuận | `fact_order`, `fact_order_item`, `fact_refund`, `dim_*`, `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `mart_customer_summary` |
| `marts_operations` | Chi phí vận hành nhập tay | `fact_order_cost` |
| `marts_reconciliation` (recon) | Đối chiếu số liệu giữa các nguồn, không phải số liệu chính thức | `recon_cost_coverage`, `recon_payment_fee_coverage`, `recon_csv_vs_dbt_profit`, `recon_csv_vs_dbt_revenue`, `recon_woo_vs_csv_shipping_charged`, `recon_unmatched_csv_cost` |
| `marts_marketing` | (chưa build — chờ Phase 6, GA4) | — |

Ý tưởng cốt lõi: **fact core** (sạch, một-nguồn-một-sự-thật) được các
**mart lợi nhuận** join lại với **fact chi phí thủ công**, để cho ra con số
kinh doanh cuối cùng. `recon` không tạo ra con số mới — nó chỉ so sánh hai
con số đã có để phát hiện lệch (drift), phục vụ kiểm định chất lượng
(xem chương 08).

## Nhóm 1 — `core`: đơn hàng, dòng hàng, hoàn tiền

### `fact_order` — một dòng = một đơn hàng (header)

Grain: `site_code + woo_order_id`. Model đọc `stg_woo_orders`, join tỷ giá
`fx_rates` (date-aware — dùng đúng ngày đặt hàng, không phải "tỷ giá mới
nhất"), rồi tính `payment_fee_usd` theo thứ tự ưu tiên: `plugin_parser` (đọc
được từ order meta) → `seed_estimate` (ước tính từ bảng `payment_fees` seed)
→ `missing`. Cột `payment_fee_source` ghi lại nguồn nào đã thắng — đây chính
là cột mà `docs/DASHBOARD_SPEC.md §K` dùng để gắn chip "estimated payment
fee" khi độ phủ thấp.

**Điểm mấu chốt (bất biến #1 trong `CLAUDE.md`): `fact_order` KHÔNG có cột
`revenue_usd`.** Đây không phải thiếu sót — đó là quyết định thiết kế có chủ
đích. Nếu `fact_order` có `revenue_usd` VÀ `fact_order_item` cũng có
`line_revenue_usd`, một dashboard vô tình `SUM` cả hai bảng sau khi join sẽ
nhân đôi doanh thu (mỗi đơn có nhiều dòng → mỗi dòng lại kéo theo
`order.revenue_usd` của đơn cha, cộng dồn N lần). Cách phòng ngừa triệt để
nhất không phải là "nhắc nhở trong tài liệu" mà là **không để cột đó tồn
tại** ở nơi có thể gây nhầm. `fact_order` chỉ giữ các số ở cấp header không
lặp lại theo dòng: `shipping_charged_usd` (phí ship **thu của khách**, phía
doanh thu — không bao giờ là chi phí), `discount_usd`, `tax_usd`,
`payment_fee_usd`.

### `fact_order_item` — nơi doanh thu sống DUY NHẤT

Grain: một dòng sản phẩm trong một đơn. Đây là **nguồn sự thật duy nhất về
doanh thu** trong toàn bộ hệ thống:

```
Revenue (USD) = SUM(fact_order_item.line_revenue_usd)
```

`line_revenue_usd` được tính từ `line_total_src` (tổng dòng, đã trừ
discount) nhân tỷ giá ECB thật của đúng ngày đặt hàng. Model cũng gắn hai cột
quan trọng cho việc lọc doanh thu chính thức:

- `order_status` — copy từ đơn cha
- `is_revenue_status` — `true` khi `status IN ('completed', 'processing',
  'refunded')`

Comment trong code nhấn mạnh một chi tiết dễ bị hiểu sai: **`line_revenue_usd`
không bị zero-out** với các đơn không phải revenue-status (failed/cancelled/
pending) — cột đó vẫn giữ số tiền dòng thật. Điều này có nghĩa là **mọi truy
vấn doanh thu chính thức bắt buộc phải thêm `WHERE is_revenue_status`**,
nếu không sẽ vô tình cộng cả các đơn thất bại/hủy vào doanh thu. Đây chính là
lý do vì sao mọi mart lợi nhuận phía dưới (`mart_order_profit`,
`recon_cost_coverage`, `recon_payment_fee_coverage`...) đều filter bằng
`is_revenue_status` khi tính "revenue orders".

### `fact_refund` — grain cấp đơn hàng (không phải cấp dòng)

Theo `docs/WOO_PAYLOAD_AUDIT.md §7`, Woo trả về refund với `line_items` luôn
rỗng — nghĩa là API không cho biết refund áp dụng cho dòng sản phẩm nào, chỉ
biết refund thuộc đơn nào. Vì vậy `fact_refund` có grain **order-level**
(`order_item_sk` luôn `NULL`), và số tiền được quy đổi tỷ giá theo **ngày
hoàn tiền** (`refund_date`), không phải ngày đặt hàng — vì một refund có thể
xảy ra ở một ngày khác hẳn, và tỷ giá tại thời điểm hoàn tiền mới đúng
(`DATA_MODEL §9`, "book on refund date").

## Nhóm 2 — `operations`: `fact_order_cost`

Đây là bảng nạp COGS từ `Order Management.csv` (nguồn sự thật cho chi phí,
theo bảng "hệ thống nào là nguồn sự thật" ở chương 02). Grain: một dòng =
một đơn Woo. `fact_order_cost` join **INNER** với `stg_woo_orders` — nghĩa
là bất kỳ dòng chi phí nào trong sheet mà không khớp được `woo_order_id`
(sai chính tả, đơn của site khác, đơn chưa ingest) sẽ **rơi ra khỏi bảng
này mà không báo lỗi**. Đó chính là lý do tồn tại của
`recon_unmatched_csv_cost` (xem bên dưới) — nó "vợt" đúng những dòng bị rơi
đó để không mất dấu.

Cột `cogs_usd` ở đây **đã bao gồm phí ship của nhà cung cấp** (supplier
fulfillment/shipping fee) — bất biến #6 trong `CLAUDE.md`. Không có cột
`actual_shipping_cost_usd` nào trong toàn bộ model, và nếu bạn thấy tham
chiếu tới khái niệm đó ở đâu, đó là bug.

## Nhóm 3 — lợi nhuận: `mart_order_profit`, `mart_product_profit`, `mart_country_profit`, `mart_customer_summary`

Đây là phần **quan trọng nhất** của chương này — nơi các bất biến nghiệp vụ
được mã hoá thành SQL thật.

### Công thức lợi nhuận đóng góp (contribution profit)

```
contribution_profit_usd = net_revenue_usd − cogs_usd − design_fee_usd − payment_fee_usd
  net_revenue_usd = (doanh thu sản phẩm + tiền ship khách trả) − effective_refund_usd
```

**Tiền ship khách trả LÀ doanh thu (Approach A, 2026-07-21).** `shipping_charged_usd`
là tiền khách đã trả và store đã nhận → nó thuộc phía **doanh thu**. Còn `cogs_usd`
(cột U trong CSV) là **toàn bộ chi phí fulfill một đơn** — đã bao gồm sẵn phí ship
mà nhà cung cấp thu. Store vừa **thu** tiền ship của khách vừa **trả** tiền fulfill
cho NCC, nên **cả hai vế đều phải xuất hiện**. Công thức cũ trừ COGS (đã gồm ship của
NCC) nhưng lại **bỏ quên** tiền ship khách trả → thiếu lợi nhuận đúng bằng phần ship
(~$40k cho FOS: $47.5k → $87.1k). Xem `docs/METRIC_CHANGES.md` (2026-07-21).

Lưu ý quan trọng để không nhầm: ta **không bao giờ trừ ship như một chi phí** (chi phí
ship của NCC đã nằm trong COGS rồi — bất biến #6); ship chỉ được **cộng vào doanh thu**
(bất biến #4). Cột CSV `Shipping` chỉ dùng để đối chiếu (`recon_woo_vs_csv_shipping_charged`);
nguồn chính thức của phí ship khách là `fact_order.shipping_charged_usd`.

### `net_revenue_usd` và refund netting có trần (capped)

```
net_revenue_usd           = gross_revenue_usd − effective_refund_usd
gross_revenue_usd         = gross_product_revenue_usd + shipping_charged_usd   -- product + ship (order-total)
gross_product_revenue_usd = SUM(fact_order_item.line_revenue_usd) FILTER (WHERE is_revenue_status)
shipping_charged_usd      = fact_order.shipping_charged_usd                    -- phí ship khách trả (doanh thu)
refunds_usd               = SUM(fact_refund.refund_amount_usd)   -- số tiền THẬT đã hoàn (gồm cả ship), dương
effective_refund_usd      = LEAST(refunds_usd, gross_revenue_usd) -- chặn trần ở base order-total
```

Vì sao vẫn cần "trần" (cap):

1. `is_revenue_status` coi đơn có status `'refunded'` là **có doanh thu** (đơn đó
   đã từng bán được hàng thật). Nếu không trừ `refunds_usd` ra, một đơn đã hoàn
   tiền 100% vẫn hiện lợi nhuận dương — sai, vì tiền đã trả lại khách.
2. Refund của Woo là **refund cấp toàn đơn** (full-order) — hoàn cả tiền sản phẩm
   **lẫn** tiền ship. **Trước** Approach A, revenue base chỉ có phần sản phẩm, nên
   trừ một refund gồm-ship mà không giới hạn sẽ đẩy doanh thu âm giả tạo (đo được
   ~**$345 over-netting trên 31 đơn**). **Nay** base đã gồm ship → refund và doanh
   thu cùng một cơ sở (order-total), nên cap gần như **không bao giờ chạm**; nó chỉ
   còn là **chốt sàn 0** cho trường hợp hiếm hoàn quá mức.
3. Một đơn hoàn toàn phần net về đúng 0 (đảo ngược giao dịch, không đảo ngược *quá
   mức*), và vẫn gánh COGS đầy đủ → hiện lỗ COGS, điều này **đúng nghiệp vụ**: hàng
   đã fulfill trước khi tiền được hoàn (khác đơn `failed`/`cancelled` — chưa từng
   phát sinh COGS nên bị loại từ đầu, không vào mart này).

`refunds_usd` vẫn được giữ nguyên (số tiền thật đã hoàn, dùng cho các chỉ số về
refund), còn `effective_refund_usd` mới là phần thực sự bị trừ vào doanh thu. Cột
`revenue_usd` trong `mart_order_profit` là **alias của `net_revenue_usd`** — vì vậy
ai đọc "revenue_usd" ở mart này đều nhận số ĐÃ NET (product + ship − refund), không
phải gross.

### Phạm vi (scope) của `mart_order_profit`

`mart_order_profit` chỉ chứa đơn nào có **cả** cost enrichment (INNER JOIN
`fact_order_cost`) **và** `gross_revenue_usd > 0` (trước khi trừ refund).
Nghĩa là:

- Đơn `failed`/`cancelled`/`pending` (không revenue-status) → không có dòng
  nào trong `fact_order_item` thỏa `is_revenue_status` → `gross_revenue_usd`
  không tồn tại → đơn bị loại khỏi mart lợi nhuận (và do đó khỏi
  `mart_product_profit`, `mart_country_profit`).
- Đơn hoàn tiền 100% vẫn **ở lại** trong mart (nó đã từng bán), chỉ là
  `net_revenue_usd` gần bằng 0.

Việc loại trừ dựa trên **gross** (trước refund), không phải net — nếu dựa
trên net thì một đơn hoàn tiền toàn phần (net = 0) sẽ bị hiểu nhầm là "chưa
từng bán" và bị âm thầm loại bỏ, trong khi thực tế công ty vẫn phải gánh
COGS của đơn đó.

### Phân bổ chi phí xuống từng dòng: `mart_product_profit`

COGS, design fee, payment fee trong sheet/Woo chỉ tồn tại ở **cấp đơn hàng**
— sheet không ghi "COGS của riêng dòng áo thun size M". Để có lợi nhuận theo
từng sản phẩm, `mart_product_profit` **phân bổ theo tỷ trọng doanh thu**
(revenue-share allocation):

```
revenue_share       = line.line_revenue_usd / order.order_revenue_usd
line_<term>_usd     = order.<term>_usd * revenue_share  -- áp cho shipping, cogs, design_fee, payment_fee, effective_refund
line_net_revenue_usd = line.line_revenue_usd + line_shipping_usd − line_refund_usd
line_profit_usd      = line_net_revenue_usd − line_cogs_usd − line_design_fee_usd − line_payment_fee_usd
```

Từ Approach A, **tiền ship khách trả cũng được phân bổ xuống dòng** theo cùng
revenue-share (cột mới `line_shipping_usd`) và cộng vào `line_net_revenue_usd`.
Riêng `line_revenue_usd` vẫn giữ product-only (không bao giờ bị sửa — bất biến #1).

Mỗi dòng được gắn nhãn `cost_allocation_method = 'allocated_by_revenue_share'`
và `cost_confidence = 0.60` — đây là cách dashboard biết để hiển thị "caveat"
(cảnh báo: số liệu này là ước tính phân bổ, không phải số liệu chính xác
từng dòng). `docs/DATA_MODEL.md §4.3` liệt kê 3 phương pháp phân bổ có thể có
(`line_exact` = 1.00, `allocated_by_revenue_share` = 0.60,
`allocated_by_quantity_share` = 0.50) — dự án hiện dùng phương pháp thứ hai
vì sheet chỉ có COGS cấp đơn.

Điểm bảo toàn (conservation) quan trọng: vì mẫu số `order_revenue_usd` trong
`mart_product_profit` (tổng TẤT CẢ các dòng của đơn, không lọc
`is_revenue_status`) bằng đúng `gross_revenue_usd` đã lọc trong
`mart_order_profit` — do `is_revenue_status` là thuộc tính ở cấp ĐƠN, giống
nhau cho mọi dòng của cùng một đơn — nên `SUM(line_profit_usd)` cộng dồn
đúng bằng `mart_order_profit.contribution_profit_usd` của đơn đó, không thừa
không thiếu (tới từng cent).

### `mart_country_profit` và `mart_customer_summary`

Hai mart này chỉ là **roll-up** (tổng hợp lại) từ `mart_order_profit` —
không có logic mới:

- `mart_country_profit`: gom theo `(country_sk, date_sk)`, quốc gia lấy từ
  `fact_order.country_sk` (địa chỉ billing). Vì `mart_order_profit` đã định
  nghĩa `revenue_usd` là NET-of-refund, roll-up này tự động kế thừa net
  revenue/profit mà không cần thêm logic refund nào.
- `mart_customer_summary`: grain một dòng/`customer_hash`. Điểm đáng chú ý:
  doanh thu khách hàng (`total_revenue_usd`) được tính **độc lập** với độ phủ
  chi phí — nó lấy refund thẳng từ `fact_refund` (không qua
  `mart_order_profit`), floor tại 0, để phạm vi bao phủ doanh thu rộng hơn
  phạm vi lợi nhuận (một khách có thể có `total_revenue_usd` nhưng
  `total_profit_usd = NULL` nếu đơn của họ chưa được cost-enrich).

## Nhóm 4 — `reconciliation` (recon): đối chiếu, không phải số liệu chính thức

Các view `recon_*` **không tạo ra chỉ số kinh doanh mới** — chúng so sánh
hai nguồn để phát hiện lệch, phục vụ giám sát chất lượng dữ liệu (chương 08
đi sâu vào phần "gating"):

| View | So sánh gì | Vì sao cần |
|---|---|---|
| `recon_cost_coverage` | % đơn có `cogs_usd > 0` trên tổng đơn **revenue-generating** | Gate hiển thị lợi nhuận trên dashboard |
| `recon_payment_fee_coverage` | % đơn có `payment_fee_usd` trên tổng đơn revenue-generating | Gate chip "estimated payment fee" |
| `recon_csv_vs_dbt_profit` | CSV `Profit` (quan sát) vs `mart_order_profit.contribution_profit_usd` | Phát hiện drift — CSV Profit KHÔNG BAO GIỜ là số chính thức |
| `recon_csv_vs_dbt_revenue` | CSV `Revenue` vs dbt revenue (net) và dbt gross (net + shipping) | CSV Revenue là gross-ish, dbt revenue là net — so sánh đúng basis mới có ý nghĩa |
| `recon_woo_vs_csv_shipping_charged` | Phí ship khách trả: Woo (chính thức) vs CSV `Shipping` | Cả hai đều là DOANH THU, không phải chi phí — chỉ đối chiếu Woo với đúng tập đơn có dòng CSV (like-for-like), tránh coverage-gap giả làm drift |
| `recon_unmatched_csv_cost` | Dòng sheet FOS không khớp `woo_order_id` nào | "Vợt" các dòng bị `INNER JOIN` của `fact_order_cost` âm thầm loại bỏ |

Chi tiết đáng học: `recon_cost_coverage` và `recon_payment_fee_coverage` đều
tính tỷ lệ phủ **trên tập đơn revenue-generating**, không phải trên tổng số
đơn. Lý do: đơn `failed`/`cancelled` không bao giờ có COGS (chưa từng sản
xuất) và không bao giờ có payment fee (chưa từng thanh toán thành công) —
nếu tính coverage trên TẤT CẢ đơn, những đơn "chết" này sẽ kéo tỷ lệ phủ
xuống giả tạo (dữ liệu thực tế: all-order coverage cho payment fee là
79.50% trong khi revenue-order coverage là 98.03%). `recon_cost_coverage`
cũng phân biệt rõ "có dòng `fact_order_cost`" khác với "có `cogs_usd > 0`
thật sự" — một dòng sheet với `cogs_usd = 0/NULL` nghĩa là "chi phí chưa
biết", không phải "đã ghi nhận chi phí"; nếu đếm nhầm sẽ thổi phồng độ phủ.

## Số liệu thật minh họa (Phase 3, tại thời điểm viết tài liệu này)

Chạy trên dữ liệu thật của site FOS:

- **4,757 đơn hàng** (toàn bộ Woo orders đã ingest)
- **Cost coverage: 98.79%** (đơn revenue-generating có `cogs_usd > 0`) →
  tier **GREEN** (≥ 95%, "fully trusted", theo bảng gating ở
  `docs/DASHBOARD_SPEC.md §K` — xem chương 08)
- **Tổng contribution profit: $87,138.04** (Approach A — đã cộng ship vào
  doanh thu, đã net-of-refund, đã cap refund netting; trước Approach A là
  $47,535.65 do bỏ quên phần ship khách trả)

Ba con số này đến từ 3 commit gần nhau trong lịch sử dự án:
`631c8c1` (feat: Phase 3 manual cost enrichment), `9914ca6` (fix: base
cost-coverage tier on revenue orders + like-for-like recon), và `727055c`
(fix: net refunds into profit — capped — + require real COGS cho coverage)
— mỗi commit sửa đúng một trong các bất biến vừa giải thích ở trên.

## Khái niệm áp dụng được

- **Doanh thu sống ở một nơi duy nhất, cấp mịn nhất (grain mịn nhất).** Đừng
  lặp lại tổng doanh thu ở cấp header nếu đã có ở cấp chi tiết — double-count
  là lỗi âm thầm và nguy hiểm nhất trong BI, phòng bằng cách **không để cột
  đó tồn tại** thay vì chỉ ghi chú "đừng dùng cột này".
- **`is_<x>_status` (hay bất kỳ cờ lọc trạng thái nào) phải được áp dụng
  nhất quán ở MỌI nơi tính rollup** — nếu một mart quên filter mà mart khác
  có, hai con số sẽ lệch nhau và không ai biết vì sao.
- **Khi cộng dồn hai đại lượng có "phạm vi" khác nhau (vd: refund toàn đơn
  vs doanh thu chỉ-tính-sản-phẩm), luôn đặt trần (cap) bằng `LEAST`/`GREATEST`
  thay vì trừ trực tiếp** — nếu không, kết quả có thể âm một cách vô nghĩa.
- **Phân bổ chi phí cấp-cao xuống cấp-chi-tiết cần đi kèm nhãn độ tin cậy**
  (`cost_allocation_method`, `cost_confidence`) để tầng trình bày (dashboard)
  biết khi nào cần hiển thị cảnh báo.
- **Recon (đối chiếu) là một lớp riêng, tách khỏi số liệu chính thức** — nó
  tồn tại để phát hiện lệch giữa các nguồn, không phải để cung cấp một phiên
  bản "số liệu thay thế". Đặt tên rõ ràng (`recon_*`) để không ai nhầm nó với
  mart chính thức.
- **`INNER JOIN` âm thầm loại bỏ dữ liệu — luôn có một view "vợt" phần bị
  loại** (như `recon_unmatched_csv_cost`), nếu không, dữ liệu thiếu sẽ không
  bao giờ được phát hiện cho tới khi ai đó thắc mắc vì sao tổng số không
  khớp.
- **Coverage/tỷ lệ phủ nên đo trên đúng tập hợp có ý nghĩa nghiệp vụ** (đơn
  revenue-generating), không phải trên toàn bộ tập dữ liệu thô — nếu không,
  các bản ghi "chết" (không bao giờ có dữ liệu) sẽ kéo tỷ lệ phủ xuống giả
  tạo và gây hoảng loạn không cần thiết.
