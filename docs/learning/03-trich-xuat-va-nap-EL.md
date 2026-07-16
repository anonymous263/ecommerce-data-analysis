# 03 — Trích xuất và Nạp dữ liệu (Extract & Load — EL)

> Đọc trước: chương 00, 01, 02. Nguồn đối chiếu: `src/extract/woo_api.py`,
> `src/extract/csv_order_management.py`, `sql/ddl/01_raw_woo.sql`, `sql/ddl/02_raw_manual.sql`,
> `docs/PIPELINE_DESIGN.md`, `CLAUDE.md` (mục Privacy).

Chương 02 đã trả lời "dữ liệu từ đâu". Chương này trả lời câu tiếp theo: **"kéo dữ liệu đó về
bằng cách nào cho an toàn, lặp lại được (idempotent), và không làm rò rỉ thông tin cá nhân?"**.
Đây là công việc của lớp **Python EL (Extract & Load)** — nằm ở `src/extract/`.

## 1. Nguyên tắc cốt lõi: EL chỉ "kéo, nạp, ghi log" — không có business logic

Đây là ranh giới kiến trúc quan trọng nhất của toàn dự án (đã nêu ở chương 01, nhắc lại ở đây vì
nó chi phối *mọi* dòng code trong `src/extract/`): **Python không được tính toán, diễn giải, hay
làm sạch dữ liệu theo nghĩa nghiệp vụ.** Nó chỉ:

1. **Extract (trích xuất)** — gọi API hoặc đọc file nguồn.
2. **Load (nạp)** — ghi gần như nguyên văn (verbatim) vào schema `raw` trong Postgres.
3. **Log (ghi log)** — ghi lại mỗi lần chạy vào `raw.pipeline_runs` (số dòng, trạng thái, lỗi).

Docstring của `woo_api.py` nói thẳng: *"this module copies the API payload verbatim and computes
no business metrics — all typing/FX/hashing/joins happen in dbt."* Việc ép kiểu (typing), quy đổi
tiền tệ (FX), băm PII (hashing), join dữ liệu — tất cả đều thuộc **dbt**: làm sạch/chuẩn hóa ở lớp `staging`
(chương 05), còn quy đổi FX và join/tính lợi nhuận ở lớp `fact`/`marts` (chương 06) — không
phải ở đây. Lý do: nếu logic nghiệp vụ nằm rải rác trong cả Python lẫn SQL, không ai có thể chạy
lại một transform và nhận được cùng kết quả một cách chắc chắn — mất tính **idempotent** và mất
khả năng kiểm tra (testability) qua `dbt test`.

## 2. Kéo WooCommerce API: phân trang & watermark tăng dần

### Phân trang (pagination)

WooCommerce REST API trả về dữ liệu theo trang (mặc định 100 bản ghi/trang). Hàm tiện ích
`paginate()` (trong `src/utils/http.py`) lặp qua từng trang cho tới khi hết dữ liệu — ví dụ gọi
`paginate(client, "/orders", params)` sẽ tự động lấy hết toàn bộ đơn hàng thỏa điều kiện, dù có
hàng nghìn trang.

Với các endpoint "full-pull" (kéo toàn bộ) như `/products`, `/customers`, `/coupons`, hàm
`_extract_simple()` không dồn hết dữ liệu vào bộ nhớ rồi mới ghi — nó **stream theo batch 500
bản ghi** (`STREAM_BATCH_SIZE = 500`) và upsert ngay khi đủ một batch. Với catalog 58.168 sản
phẩm của site FOS, cách này giữ bộ nhớ ổn định và giúp một lần dừng giữa chừng chỉ mất tối đa
một batch — lần chạy sau, upsert tự khớp lại phần còn thiếu.

### Watermark tăng dần (incremental high-watermark)

Thay vì kéo lại **toàn bộ** đơn hàng mỗi lần chạy, pipeline lưu một "mốc nước cao nhất"
(watermark) — giá trị `date_modified_gmt` lớn nhất đã thấy — trong bảng `raw.pipeline_state`.
Lần chạy sau chỉ hỏi Woo: *"cho tôi mọi đơn hàng đã sửa đổi SAU mốc này"* (`modified_after`).
Đây là kỹ thuật chuẩn để tránh kéo lại dữ liệu không đổi mỗi ngày.

Một chi tiết tinh tế đáng học: bộ lọc `modified_after` của Woo là **exclusive** (lớn hơn nghiêm
ngặt), nên một đơn hàng sửa đổi đúng cùng giây với watermark có thể bị bỏ sót vĩnh viễn. Code xử
lý bằng cách trừ đi 1 giây chồng lấn (`WATERMARK_OVERLAP_SECONDS = 1`) khi truy vấn lại — việc
kéo lại đơn hàng đó lần nữa là vô hại vì **upsert là idempotent** (chạy lại không tạo dòng trùng,
chỉ ghi đè). Đây là một nguyên tắc thiết kế quan trọng: *"thà kéo trùng một chút còn hơn bỏ sót
dữ liệu"* — và điều đó chỉ an toàn nếu bước nạp có tính idempotent.

Ngoài ra, **watermark chỉ được cập nhật sau khi toàn bộ trang dữ liệu đã kéo và ghi thành công**
(`new_watermark = max_watermark(orders)` chạy ở cuối, sau khi `upsert_rows` đã xong) — nếu pipeline
lỗi giữa chừng, watermark cũ vẫn còn nguyên, lần chạy sau sẽ kéo lại đúng khoảng đã lỡ dở, không
để lại khoảng trống dữ liệu.

### Idempotent upsert & làm mới order_items

Mỗi bảng raw có khóa chính là `(site_code, woo_<entity>_id)`, và việc nạp luôn dùng **UPSERT**
(`INSERT ... ON CONFLICT DO UPDATE`) — chạy lại cùng một cửa sổ dữ liệu sẽ ghi đè tại chỗ, không
bao giờ tạo dòng trùng.

Riêng bảng `raw.woo_order_items` (các dòng sản phẩm trong đơn) cần xử lý đặc biệt: nếu một đơn
hàng được sửa để **xóa bớt** một dòng sản phẩm, một upsert bình thường sẽ để lại dòng cũ mồ côi
(orphaned) trong raw — khiến dbt đếm nhầm số lượng. Hàm `_load_order_items()` giải quyết bằng
một giao dịch (transaction) gồm hai bước: **DELETE** toàn bộ dòng item hiện có của các đơn hàng
vừa kéo về, rồi **INSERT** lại đúng danh sách `line_items[]` hiện tại. Đây là mẫu
**"delete-then-insert" (xóa rồi chèn lại)** — hữu ích bất cứ khi nào nguồn dữ liệu có thể xóa
phần tử con của một thực thể cha.

### Tối ưu dựa trên audit thực tế: bỏ qua request thừa

`docs/WOO_PAYLOAD_AUDIT.md` xác nhận chỉ **34 / 4.757 đơn hàng** thực sự có hoàn tiền (mảng tóm
tắt `refunds` trong payload đơn hàng không rỗng). Vì vậy `_extract_orders_and_refunds()` chỉ gọi
API con `/orders/<id>/refunds` (chậm, một request mỗi đơn) khi đơn đó có tóm tắt hoàn tiền —
tránh 4.757 request không cần thiết chỉ để lấy dữ liệu 34 đơn thực sự cần. Đây là một bài học
tổng quát: **luôn audit dữ liệu thật trước khi tối ưu** — tối ưu dựa trên phỏng đoán dễ sai hướng.

## 3. Nạp CSV Order Management: forward-fill, drop PII, truncate-reload

`src/extract/csv_order_management.py` xử lý một nguồn hoàn toàn khác về bản chất: một file CSV do
con người chỉnh sửa tay, xuất từ Google Sheet. Sheet này có cấu trúc "lộn xộn" theo kiểu con người
quen dùng — không phải theo kiểu máy dễ đọc:

- **Bỏ qua 2 dòng sub-header** (`skiprows=[1, 2]`) — dòng tiêu đề thật ở dòng 0, còn hai dòng kế
  tiếp là dòng phụ đề/tổng cộng mà người quản lý sheet sẽ không xóa đi.
- **Forward-fill theo `Order Code`**: với đơn hàng nhiều sản phẩm, sheet chỉ điền các cột **ở
  cấp đơn hàng** (order-level, ví dụ `CoGS`, `Total`) trên dòng vật lý **đầu tiên** của đơn đó;
  các dòng con (item-level) để trống. Hàm `forward_fill_order_level()` nhóm theo `Order Code` và
  **điền xuôi (forward-fill)** giá trị của dòng đầu xuống các dòng con — nhưng chỉ với cột
  order-level; các cột item-level (`Product name`, `Type`...) giữ nguyên riêng biệt cho từng dòng.
- **Dedupe về grain đơn hàng**: sau khi forward-fill, `build_raw_rows()` chỉ giữ **dòng đầu tiên**
  cho mỗi `(site_code, woo_order_id)` — vì `fact_order_cost` (đích cuối cùng) có grain là một
  dòng/đơn hàng, không phải một dòng/sản phẩm.
- **Tin tưởng cột `Currency`**: số tiền được parse bằng `parse_money()`, loại bỏ ký hiệu tiền tệ
  và ký tự mojibake (lỗi encoding) — nhưng ký hiệu đó **không** được dùng để suy luận đơn vị tiền
  tệ; đơn vị tiền tệ luôn lấy từ đúng cột `Currency` của sheet. Đây là nguyên tắc "một nguồn sự
  thật cho một thuộc tính" áp dụng ngay trong nội bộ một file.

### Drop PII TRƯỚC khi ghi raw — không phải sau

Đây là điểm khác biệt lớn nhất so với nguồn Woo. Với Woo, PII (email, tên khách hàng) được phép
nằm trong `raw.woo_customers` và chỉ bị băm (hash)/loại bỏ ở tầng **staging** của dbt. Nhưng với
CSV Order Management, quy tắc nghiêm ngặt hơn: các cột `Name`, `Email`, `Phone`, `Ship to` bị
**loại bỏ ngay trong Python, trước khi bất kỳ dòng nào được ghi vào `raw.csv_order_management`**
(`drop_pii_columns()`, chạy trước cả `forward_fill_order_level()`). Do đó
`raw.csv_order_management` **không phải** bản sao byte-for-byte của sheet gốc — nó là một bản
trích xuất đã được lọc PII ngay từ cổng vào. Mã tracking / URL fulfillment vẫn được phép vào raw
(trong `_payload`), nhưng **phải** được băm trước khi lên staging/marts (Phase 5) — chưa bao giờ
được để dạng plaintext vượt qua ranh giới `raw → staging`.

Lý do quy tắc khác nhau giữa hai nguồn: Woo là hệ thống có sẵn cơ chế truy vết (audit trail) và
việc hash ở staging vẫn đảm bảo PII không rời khỏi raw dạng thô ra ngoài dbt; còn CSV là file thủ
công, dễ bị xuất/chia sẻ nhầm — nên dự án chọn xóa PII sớm nhất có thể, giảm diện tích rủi ro
(attack surface) ngay từ điểm nạp.

### Truncate-reload: ngữ nghĩa snapshot, không phải incremental

Khác với Woo (incremental upsert theo watermark), CSV được nạp theo kiểu **TRUNCATE rồi nạp lại
toàn bộ (truncate-reload)** mỗi lần chạy — vì sheet không có khái niệm "mới sửa đổi từ khi nào".
Hàm `truncate_reload()` chạy TRUNCATE và INSERT **trong cùng một transaction**
(`truncate_first=True`), nên nếu quá trình nạp lỗi giữa chừng, transaction rollback về snapshot
tốt trước đó thay vì để bảng trống. Hệ quả nghiệp vụ quan trọng: nếu một dòng bị **xóa** khỏi
sheet, nó cũng **biến mất** khỏi `raw.csv_order_management` ở lần chạy kế tiếp — khác hẳn hành vi
của upsert incremental, nơi dữ liệu cũ không bao giờ tự mất.

## 4. Thiết kế schema `raw`: append-only, mang theo ngữ cảnh

Nhìn vào `sql/ddl/01_raw_woo.sql` và `02_raw_manual.sql`, mọi bảng raw đều tuân theo cùng một
khuôn mẫu:

```sql
CREATE TABLE raw.woo_orders (
    site_code         TEXT        NOT NULL,   -- multi-site (chương 02)
    woo_order_id      BIGINT      NOT NULL,   -- khóa tự nhiên phía nguồn
    ...                                        -- vài cột "thăng hạng" để lọc/watermark rẻ
    date_modified_gmt TIMESTAMPTZ,             -- nguồn watermark tăng dần
    extracted_at      TIMESTAMPTZ NOT NULL,    -- khi nào dòng này được kéo về
    _payload          JSONB       NOT NULL,    -- toàn bộ response gốc — lưới an toàn JSON
    PRIMARY KEY (site_code, woo_order_id)
);
```

Bốn nguyên tắc lặp lại ở mọi bảng raw:

- **`site_code`** — luôn có mặt, phân biệt cửa hàng (chương 02).
- **`extracted_at`** — dấu thời gian của lần kéo, phục vụ debug ("dòng này có mới nhất
  không?") và khác với thời gian nghiệp vụ (`date_created_gmt`/`date_modified_gmt`).
- **`_payload JSONB`** — **lưới an toàn (safety net)**: toàn bộ response API/CSV gốc được giữ
  nguyên dạng JSON, kể cả những trường chưa được "thăng hạng" (promote) thành cột riêng. Khi Woo
  thêm trường mới trong tương lai, nó tự động nằm sẵn trong `_payload` — dbt staging chỉ cần
  `SELECT` thêm trường đó ra, không cần chỉnh Python hay DDL.
- **Một vài cột được "thăng hạng"** (ví dụ `date_modified_gmt`, `status`, `currency`) — đây chỉ
  là **bản sao y nguyên** (verbatim), phục vụ watermark và lọc rẻ tiền (index), **không phải**
  một phép biến đổi. Việc ép kiểu/diễn giải thật sự vẫn thuộc về dbt staging.

Ngoài các bảng thực thể, schema `raw` còn có hai bảng vận hành xuất hiện trong mọi pipeline EL
nghiêm túc:

- **`raw.pipeline_state`** — lưu watermark theo `(site_code, entity)`.
- **`raw.pipeline_runs`** — nhật ký mỗi lần chạy: `run_id`, thời gian bắt đầu/kết thúc, trạng thái
  (`running`/`success`/`failed`), số dòng, và `error_text` khi lỗi. Đây là nơi đầu tiên bạn nhìn
  vào khi dashboard "có vẻ thiếu dữ liệu hôm nay".

## 5. Quy tắc PII khi nạp — tóm tắt theo nguồn

| Nguồn | PII đi vào raw dạng gì? | Khi nào được băm/loại bỏ? |
|---|---|---|
| WooCommerce (`raw.woo_customers`, `raw.woo_orders`) | Có thể có (email, tên, địa chỉ) trong `_payload` | Ở **dbt staging** — `hash_pii.sql` băm SHA-256(email chuẩn hóa + `PII_SALT`), xóa tên/SĐT/địa chỉ |
| CSV Order Management | **Đã bị xóa** (`Name`, `Email`, `Phone`, `Ship to`) trước khi ghi raw | Ngay tại Python, trước khi ghi — không có "giai đoạn sau" cho các cột này |
| Tracking ID / URL fulfillment (cả hai nguồn) | Có thể nằm trong `_payload` | Phải băm trước khi lên staging/marts (Phase 5) — không bao giờ ở dạng plaintext ngoài `raw` |

Quy tắc bao trùm tất cả (`CLAUDE.md`): **PII không bao giờ được vượt qua ranh giới
`raw → staging` ở dạng chưa băm.** Vì các trang web dùng "guest checkout" (khách không cần đăng
ký), việc liên kết khách hàng hoàn toàn dựa vào email đã băm — nên `PII_SALT` (muối băm) phải
được sao lưu ngoại tuyến: mất nó nghĩa là mất khả năng liên kết mọi khách hàng trong toàn bộ kho
dữ liệu.

## Khái niệm áp dụng được

- Giữ ranh giới cứng: lớp trích xuất (EL) **chỉ** pull/land/log; mọi transform nghiệp vụ dồn về
  một lớp duy nhất (ở đây là dbt) — dễ kiểm tra, dễ chạy lại, dễ audit.
- Kéo dữ liệu tăng dần bằng **watermark**, và chỉ commit watermark **sau khi** dữ liệu đã ghi
  thành công — không bao giờ "lạc quan" cập nhật mốc trước khi chắc chắn dữ liệu đã an toàn.
- Khi API có ngữ nghĩa "exclusive" ở bộ lọc thời gian, hãy chồng lấn (overlap) một khoảng nhỏ và
  dựa vào **upsert idempotent** để việc lấy trùng trở nên vô hại.
- Với entity có danh sách con (như `line_items`), cân nhắc mẫu **delete-then-insert** trong một
  transaction để xử lý trường hợp phần tử con bị xóa ở nguồn.
- Stream theo batch khi full-pull một tập dữ liệu lớn — đừng load hết vào RAM trước khi ghi.
- Luôn giữ payload gốc trong một cột JSON (`_payload`) làm lưới an toàn — nó cho phép schema
  nguồn tiến hóa mà không phá vỡ pipeline trích xuất.
- Với dữ liệu do con người nhập tay (CSV/sheet), hãy xử lý PII **sớm nhất có thể** (ngay tại
  điểm nạp), nghiêm ngặt hơn so với dữ liệu API có audit trail sẵn.
- Luôn có bảng nhật ký vận hành (`pipeline_runs`) và bảng trạng thái watermark
  (`pipeline_state`) — đây là nơi đầu tiên để chẩn đoán khi dữ liệu "biến mất" hoặc "trùng lặp".
