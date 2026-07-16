# 08 — Chất lượng dữ liệu và kiểm định (Data Quality & Validation)

## Vì sao chương này tồn tại

Một kho dữ liệu có thể chạy `dbt build` xanh (không lỗi) nhưng vẫn cho ra **số sai** —
vì "không lỗi cú pháp" khác với "số liệu đáng tin". Trong dự án này, **profit
(lợi nhuận)** phụ thuộc vào một file CSV nhập tay (`Order Management.csv`), không
phải API chính thức như Woo. Nếu file CSV thiếu dữ liệu cho 30% đơn hàng, thì hiển
thị "Contribution Profit = $47,535" lên dashboard là **lừa dối chính mình** — con số
đó chỉ tính trên 70% đơn hàng, phần còn lại coi như chi phí bằng 0 (sai).

Vì vậy dự án này tách rời hai câu hỏi:
1. **Coverage (độ phủ):** trong tổng số đơn hàng, bao nhiêu % có đủ dữ liệu để tính đúng?
2. **Gating (gác cổng):** nếu độ phủ thấp, dashboard có nên **ẩn** số liệu đó không?

Đây là nguyên tắc "đo trước khi tin" — áp dụng cho bất kỳ dự án BI nào có nguồn dữ
liệu thủ công hoặc nguồn thứ cấp.

## 1. Coverage là gì, đo thế nào

**Coverage (độ phủ)** = tỷ lệ số dòng/đơn hàng có dữ liệu đầy đủ cho một chỉ số,
trên tổng số dòng/đơn hàng *cần* có dữ liệu đó. Hai coverage quan trọng nhất của
dự án, định nghĩa tại `docs/METRICS_DEFINITION.md` §H:

### H1 — Cost Coverage % (độ phủ chi phí COGS)

```
Cost Coverage % = COUNT(đơn có doanh thu VÀ có fact_order_cost VÀ cogs_usd > 0)
                   / COUNT(đơn có doanh thu)
```

Hai điểm tinh tế, dễ làm sai:

- **Mẫu số (denominator) chỉ là "đơn có doanh thu"** (`is_revenue_status = true`
  trên ít nhất 1 dòng), **không phải mọi đơn hàng**. Đơn `failed`/`cancelled`/`pending`
  không bao giờ có COGS thật (không có gì để giao), nên không thể "thiếu chi phí" —
  đưa chúng vào mẫu số sẽ pha loãng coverage một cách giả tạo.
- **"Có dòng `fact_order_cost`" không đồng nghĩa với "được phủ".** Một dòng chi
  phí thủ công có thể tồn tại nhưng `cogs_usd = 0` hoặc `NULL` — nghĩa là "chưa biết
  chi phí", không phải "chi phí đã ghi nhận". Model `recon_cost_coverage.sql` lọc
  rõ: `covered_revenue_orders_with_cogs` chỉ đếm khi `cogs_usd > 0`.

Giá trị thật trên dữ liệu FOS: **98.79%** → tầng **GREEN** (≥ 95%, xem §3).

### H4 — Payment Fee Coverage % (độ phủ phí thanh toán)

```
Payment Fee Coverage % = COUNT(đơn có doanh thu VÀ payment_fee_usd IS NOT NULL)
                          / COUNT(đơn có doanh thu)
```

Cùng nguyên tắc mẫu số như H1 — và đây chính là bài học quan trọng nhất của
chương này (xem §2).

## 2. Bài học: rebase mẫu số (denominator) — H4 ngày 2026-07-16

`docs/METRIC_CHANGES.md` ghi lại: công thức H4 **cũ** tính trên **mọi đơn hàng**:

```
COUNT(fact_order WHERE payment_fee_usd IS NOT NULL) / COUNT(fact_order)   -- CŨ, SAI MẪU SỐ
```

Kết quả: **79.50%** — dưới ngưỡng 80%, kích hoạt chip cảnh báo "estimated payment
fee" trên mọi biểu đồ lợi nhuận.

Nhưng con số này **sai về mặt khái niệm**: trong 4,757 đơn hàng của FOS, có
**900 đơn** ở trạng thái `failed`/`cancelled`/`pending` — những đơn này **chưa bao
giờ thanh toán thành công**, nên không hề có phí gateway (PayPal/Stripe) nào bị
tính. `payment_fee_usd = NULL` trên các đơn này là **đúng**, không phải "thiếu dữ
liệu". Đưa 900 đơn "chết" này vào mẫu số khiến coverage bị đánh giá thấp giả tạo.

Công thức **mới** (rebase về cùng cơ sở với H1 — chỉ tính trên đơn có doanh thu):

```
COUNT(đơn có doanh thu VÀ payment_fee_usd IS NOT NULL) / COUNT(đơn có doanh thu)  -- MỚI, ĐÚNG
```

Kết quả: **98.03%** (3,740 / 3,815 đơn có doanh thu) → tầng ≥ 80%, **chip tắt**.

| | Mẫu số cũ (mọi đơn hàng) | Mẫu số mới (đơn có doanh thu) |
|---|---|---|
| Coverage | 79.50% | **98.03%** |
| Tầng | dưới 80% → chip bật | ≥ 80% → chip tắt |
| Khoảng cách thu thập thật | — | chỉ 75 đơn có doanh thu thiếu phí (CSV `Fee` bù lại ~70) |

**Bài học tái sử dụng:** khi đo coverage cho một chỉ số chỉ có ý nghĩa với một
tập con dữ liệu (ở đây: "phí thanh toán" chỉ có ý nghĩa với đơn *đã thanh toán*),
mẫu số phải khớp với tập con đó — không phải toàn bộ bảng. Đây chính xác là lý do
H1 (cost coverage) đã được rebase trước đó ở commit `727055c`, và H4 lặp lại đúng
lý luận này (`9914ca6` → `727055c` → `2026-07-16`). Giá trị 79.50% không bị xóa —
nó vẫn được giữ làm cột `all_order_coverage_pct` mang tính tham khảo (informational),
vì nó phản ánh đúng "tỷ lệ plugin bắt được phí" ở tầng nguồn (`WOO_PAYLOAD_AUDIT.md`).

## 3. Gating theo tầng (tiered gating) — biến coverage thành hành vi dashboard

Coverage chỉ là một con số — **gating** là quy tắc biến con số đó thành hành vi
UI. Từ `docs/METRICS_DEFINITION.md` §J / `docs/DASHBOARD_SPEC.md` §K:

| Cost Coverage % (H1, đơn có doanh thu) | Hiển thị lợi nhuận | UI |
|---|---|---|
| `< 80%` | **Ẩn hoàn toàn** | Banner "Profit unavailable — cost coverage too low" |
| `80% – 95%` | **Hiện, có cảnh báo** | Chip vàng "Partial cost coverage (XX%)" |
| `≥ 95%` | **Tin cậy hoàn toàn** | Không chip |

Thêm một lớp gate thứ hai: nếu **Payment Fee Coverage < 80%**, mọi biểu đồ lợi
nhuận có thêm chip "Estimated payment fee — XX%". Trạng thái sống trên FOS: cost
coverage 98.79% (GREEN, không banner/chip) và payment-fee coverage 98.03% (chip
tắt) — nghĩa là dashboard MVP hiện lợi nhuận **đầy đủ, không cảnh báo nào**.

Nguyên tắc thiết kế ở đây: **gating không phải để làm khó người dùng, mà để
không cho một con số chưa đủ tin cậy đội lốt con số chính thức.** Khi coverage
xuống thấp trong tương lai (ví dụ nguồn CSV bị gián đoạn), dashboard tự động ẩn
— không cần ai nhớ để tắt thủ công.

## 4. dbt tests: generic vs singular

dbt có hai loại test:

**Generic tests** — tái sử dụng, khai báo trong `schema.yml`, áp cho một cột:

```yaml
- name: order_natural_key
  tests: [unique, not_null]
- name: status
  tests:
    - accepted_values:
        values: [completed, processing, cancelled, failed, refunded, pending]
- name: site_sk
  tests:
    - relationships: { to: ref('dim_site'), field: site_sk }
```

Bốn loại chính: `not_null` (không rỗng), `unique` (không trùng), `relationships`
(khóa ngoại phải tồn tại ở bảng dim — chống "orphan fact"), `accepted_values`
(cột enum chỉ được chứa giá trị định trước — bắt lỗi status lạ do Woo đổi API).

**Singular tests** — SQL viết tay cho logic nghiệp vụ riêng, đặt ở
`dbt/tests/singular/`. Test "pass" khi **không trả về dòng nào**; mỗi dòng trả về
là một vi phạm. Ba ví dụ trong dự án:

- `assert_site_seed_matches_config.sql` — seed `dim_site_seed.csv` phải khớp
  chính xác danh sách site kỳ vọng (`FOS`), tránh site "ma" hoặc thiếu site.
- `assert_cost_coverage_tiers.sql` — cảnh báo khi cost coverage (đơn có doanh
  thu, `cogs_usd > 0`) dưới 95% (tầng GREEN).
- `assert_payment_fee_coverage_at_least_80.sql` — cảnh báo khi payment-fee
  coverage (đơn có doanh thu) dưới 80%.

**Severity: warn vs error.** Mặc định một test fail sẽ làm `dbt build` báo lỗi
(error, exit code khác 0). Nhưng hai test coverage trên khai báo
`{{ config(severity='warn') }}` — vì độ phủ dữ liệu thấp là **tín hiệu chất
lượng dữ liệu**, không phải **lỗi pipeline**: pipeline vẫn chạy đúng, chỉ là dữ
liệu nguồn (CSV thủ công) chưa đầy đủ. Dùng `error` ở đây sẽ chặn build một cách
không cần thiết mỗi khi nhân viên nhập liệu chậm; dùng `warn` cho phép build
tiếp tục nhưng vẫn có tín hiệu để theo dõi (`dbt build` in ra `WARN=1`).

## 5. Recon views — đối chiếu phát hiện drift

`marts_recon` chứa các view **không phải để dùng làm KPI chính thức**, mà để
**giám sát độ lệch (drift)** giữa các nguồn — cảnh báo sớm khi có gì đó bất
thường.

- **`recon_cost_coverage`** — một dòng theo site + dòng `__ALL__` tổng, phơi ra
  `cost_coverage_pct`, `cogs_coverage_pct`, `all_order_coverage_pct`, và
  `coverage_tier` (green/yellow/red). Đây là view mà measure `[Cost Coverage %]`
  trong Power BI đọc trực tiếp.
- **`recon_payment_fee_coverage`** — tương tự, group theo `payment_fee_source`
  (`api_exact`/`plugin_parser`/`seed_estimate`/`missing`) + dòng `__ALL__`.
- **`recon_csv_vs_dbt_revenue`** — so sánh `Revenue` trong CSV với doanh thu dbt
  chính thức. Điểm quan trọng: CSV `Revenue` ≈ doanh thu **gộp cả shipping**
  (gross), còn doanh thu dbt là **net line-item** (shipping tách riêng ở
  `fact_order.shipping_charged_usd`). Nên view này phơi cả `delta_usd` (so với
  net — lệch lớn "theo thiết kế", vì bản chất khác nhau) và `delta_vs_gross_usd`
  (so với net + shipping — độ lệch thật, gần 0). **So sánh phải like-for-like**,
  nếu không sẽ tưởng nhầm là lỗi.
- **`recon_csv_vs_dbt_profit`** — so `Profit` trong CSV với
  `mart_order_profit.contribution_profit_usd`. CSV không nhất thiết trừ refund
  giống dbt, nên lệch ở đơn có hoàn tiền là dự kiến, không phải bug.
- **`recon_woo_vs_csv_shipping_charged`** — so `shipping_charged_usd` (Woo,
  chính thức) với cột `Shipping` trong CSV, theo (site, ngày). View này **chỉ
  join với các đơn có dòng CSV cost** (`INNER JOIN fact_order_cost`) — nếu so
  toàn bộ Woo với CSV đã phủ, chênh lệch coverage sẽ giả trang thành "drift".
  So sánh like-for-like cho kết quả lệch thật chỉ ~2% (mục tiêu ≤ 5%).
- **`recon_unmatched_csv_cost`** — phơi các dòng CSV của site FOS mà `Order
  Code` không khớp đơn Woo nào (lỗi gõ, đơn bị xóa, hoặc chưa ingest) — dữ liệu
  này bị `fact_order_cost` âm thầm loại bỏ (`INNER JOIN`), nên view này là nơi
  duy nhất để phát hiện và sửa tại nguồn.

## 6. METRIC_CHANGES.md — vì sao phải log thay đổi định nghĩa

`docs/METRICS_DEFINITION.md` §L quy định: **mọi thay đổi công thức chỉ số phải
ghi vào `docs/METRIC_CHANGES.md`** — ngày, công thức cũ, công thức mới, lý do.
Đây là **append-only log** (chỉ thêm, không xóa/sửa lại lịch sử).

Lý do tồn tại quy tắc này:

1. **Chỉ số kinh doanh là hợp đồng ngầm** với người xem dashboard. Nếu "Payment
   Fee Coverage" hôm nay là 79.50% và ngày mai đột nhiên là 98.03% mà không giải
   thích, người xem sẽ nghi ngờ toàn bộ hệ thống — dù thay đổi là **đúng** (sửa
   một mẫu số sai).
2. **Khả năng truy vết (traceability).** Khi một con số trên dashboard "tự
   nhiên" đổi, người review (hoặc chính bạn 6 tháng sau) cần biết: đổi vì dữ
   liệu thay đổi, hay vì công thức thay đổi? Nếu không log, hai nguyên nhân này
   không phân biệt được.
3. **Ví dụ thật (H4, 2026-07-16):** entry ghi rõ công thức cũ/mới, hiệu ứng
   trên số liệu sống (79.50% → 98.03%, tầng chip bật → tắt), lý do (900 đơn
   failed/cancelled/pending không thể có phí), và **danh sách đầy đủ mọi file
   bị ảnh hưởng** (model SQL, singular test, 3 tài liệu, 2 file Power BI) — để
   không sót chỗ nào khi áp dụng thay đổi.

## Khái niệm áp dụng được

- **Coverage phải cùng mẫu số với ý nghĩa nghiệp vụ của chỉ số** — không lấy
  "tổng mọi dòng" làm mặc định nếu chỉ một tập con dòng có thể có giá trị đó.
- **"Có dòng dữ liệu" ≠ "được phủ".** Một dòng cost/fee tồn tại nhưng giá trị
  0/NULL vẫn là "chưa biết", phải loại khỏi coverage.
- **Gating theo tầng (đỏ/vàng/xanh)** biến một con số đo lường thành hành vi UI
  tự động — dashboard tự ẩn/cảnh báo khi dữ liệu chưa đủ tin, không cần con
  người nhớ tắt thủ công.
- **dbt test severity `warn` cho tín hiệu chất lượng dữ liệu, `error` cho lỗi
  pipeline** — đừng chặn build vì dữ liệu nguồn chưa hoàn hảo.
- **Recon/drift view phải so sánh like-for-like** (cùng tập hợp, cùng định
  nghĩa) — nếu không, độ lệch do khác biệt tập hợp (coverage gap) sẽ bị hiểu
  nhầm thành lỗi số liệu.
- **Log mọi thay đổi định nghĩa chỉ số** (ngày, cũ, mới, lý do, phạm vi ảnh
  hưởng) — biến "con số tự nhiên đổi" thành "thay đổi có thể truy vết".

Xem thêm: chương 06 (bất biến nghiệp vụ), chương 07 (từ điển dữ liệu), chương 09
(cách các coverage/gating này được thể hiện trong Power BI).
