# 10 — Bài học & Cách áp dụng cho dự án BI/DA khác

> Đây là chương **đúc kết**. Không giải thích lại từ đầu — mỗi mục là một
> **nguyên tắc tái sử dụng được**, kèm *vì sao nó quan trọng* và *cách mang nó sang
> dự án BI/DA tiếp theo*, dù dự án đó là bán lẻ, SaaS, fintech hay bất kỳ domain nào.

---

## 1. Tách EL khỏi Transform (kiến trúc ELT, không phải ETL)

**Nguyên tắc:** Lớp trích xuất/nạp (Extract & Load — "EL") chỉ được phép **kéo dữ liệu thô và
lưu nguyên trạng**. Mọi logic nghiệp vụ (ép kiểu, tính toán, join, quy đổi tiền tệ, lọc trạng
thái) đều nằm ở lớp biến đổi (dbt), **không** nằm trong code Python.

**Vì sao:** Khi EL và Transform trộn lẫn, một thay đổi nghiệp vụ nhỏ (ví dụ đổi công thức lợi
nhuận) buộc phải sửa và deploy lại code Python thu thập dữ liệu — rủi ro cao, khó test, khó
tái chạy lại từ đầu (re-run). Tách riêng giúp: (a) raw data luôn là "nguồn sự thật" bất biến,
có thể replay bất cứ lúc nào; (b) transform có thể test độc lập bằng SQL/dbt tests mà không
cần gọi API thật.

**Áp dụng lần sau:** Bất kể nguồn dữ liệu là API, webhook, hay file CSV — viết code nạp dữ
liệu (ingestion) **không có `if/else` nghiệp vụ**. Nếu thấy mình viết `if status == 'completed':
revenue += ...` trong code Python/ingestion, đó là dấu hiệu logic nghiệp vụ đang rò rỉ sai lớp.

---

## 2. Phân lớp raw → staging → marts (bronze/silver/gold)

**Nguyên tắc:** Ba lớp, mỗi lớp một trách nhiệm rõ ràng:

| Lớp | Tương đương | Trách nhiệm |
|---|---|---|
| `raw` | bronze | Y nguyên dữ liệu nguồn, append-only, có `_payload` JSONB để không mất thông tin |
| `staging` | silver | Ép kiểu, hash PII, dedupe, chuẩn hóa tên cột — **1 model / 1 nguồn** |
| `marts` | gold | Join nhiều nguồn, áp dụng công thức nghiệp vụ, tối ưu cho truy vấn BI |

**Vì sao:** Khi có lỗi số liệu, bạn cần biết lỗi nằm ở "dữ liệu nguồn sai" hay "logic biến đổi
sai". Có ranh giới lớp rõ ràng giúp debug theo từng bước (raw đúng chưa? → staging đúng chưa?
→ marts đúng chưa?) thay vì phải dò một khối SQL khổng lồ.

**Áp dụng lần sau:** Luôn tạo 3 schema/thư mục riêng biệt ngay từ đầu, kể cả dự án nhỏ. Đừng
join thẳng từ raw sang marts "cho nhanh" — nợ kỹ thuật này rất đắt khi dữ liệu nguồn thay đổi
cấu trúc.

---

## 3. Một chỉ số — một nguồn sự thật (Single Source of Truth)

**Nguyên tắc:** Mỗi số liệu cốt lõi (doanh thu, chi phí, lợi nhuận) chỉ được **định nghĩa và
lưu trữ ở đúng một bảng/cột**, không lặp lại ở nhiều nơi với công thức khác nhau.

**Ví dụ trong dự án này:** `revenue_usd` **chỉ tồn tại** ở `fact_order_item.line_revenue_usd`
(grain = dòng sản phẩm trong đơn). `fact_order` (grain = đơn hàng) **cố tình không có cột
`revenue_usd`** — nếu có, người dùng Power BI dễ SUM nhầm ở cả hai bảng và nhân đôi doanh thu
khi kéo theo cả `fact_order` lẫn `fact_order_item` vào cùng visual.

**Vì sao:** Đây là lỗi kinh điển nhất trong BI — "double counting" khi một chỉ số tồn tại ở
nhiều grain khác nhau. Ẩn hẳn cột nguy hiểm khỏi bảng grain sai còn hiệu quả hơn là ghi chú
"đừng SUM cột này ở đây".

**Áp dụng lần sau:** Trước khi tạo fact table mới, tự hỏi: "chỉ số này có thể bị cộng nhầm ở
grain nào khác không?". Nếu có, **thiết kế để không thể cộng sai** (bỏ cột, đổi tên rõ ràng
như `line_revenue_usd` thay vì `revenue_usd`), thay vì chỉ dựa vào tài liệu nhắc nhở.

---

## 4. Grain rõ ràng + surrogate key — nền tảng star schema

**Nguyên tắc:** Mọi fact table phải khai báo rõ **grain** (1 dòng = 1 gì?) trước khi viết SQL.
Mọi dimension dùng **surrogate key** riêng (không dùng khóa nghiệp vụ của nguồn) để join, giữ
được lịch sử khi khóa nguồn đổi hoặc trộn nhiều nguồn (multi-site).

**Vì sao:** Grain mơ hồ là nguyên nhân số 1 gây sai số liệu tổng hợp. Surrogate key giúp mô
hình chịu được thay đổi từ hệ thống nguồn (đổi ID, hợp nhất nhiều site) mà không phải sửa lại
toàn bộ các fact liên quan.

**Áp dụng lần sau:** Viết grain thành một câu tiếng Việt đơn giản ngay trong docstring của
model dbt, ví dụ: `-- grain: 1 dòng = 1 sản phẩm trong 1 đơn hàng`. Khóa tự nhiên (natural key)
nên là tổ hợp có ý nghĩa nghiệp vụ (ví dụ `site_code + woo_order_id`), còn surrogate key nội bộ
dùng để join nhanh và ổn định.

---

## 5. PII: drop sớm, hash có salt, sao lưu salt offline

**Nguyên tắc:** Dữ liệu định danh cá nhân (PII) phải được xử lý **ngay tại điểm nạp** hoặc
chậm nhất là ở lớp staging — không bao giờ để lọt PII thô xuống marts hoặc lên git.

**Bài học thực tế từ dự án:** từng có sự cố rò rỉ do dump ~205MB dữ liệu kèm PII bị commit
nhầm (Woo API key cũng từng bị lộ trên GitHub và phải rotate). Quy tắc rút ra:
- Xóa cột PII thô (tên, email, SĐT, địa chỉ) **trước khi ghi vào `raw`**, không đợi đến staging.
- Với các trường cần liên kết khách hàng (ví dụ email của khách vãng lai/guest checkout), **hash
  bằng `SHA-256(giá trị đã chuẩn hóa || salt bí mật)`** — không hash trần vì dễ bị dò ngược bằng
  bảng tra cứu (rainbow table) nếu không có salt.
- **Salt phải được sao lưu offline, tách khỏi git và tách khỏi database** — mất salt nghĩa là
  mất khả năng liên kết khách hàng vĩnh viễn (không thể hash lại để so khớp).
- File dữ liệu thật (CSV, raw export) đưa vào `.gitignore` **trước khi** tạo file, không phải sau.

**Áp dụng lần sau:** Trước khi viết dòng code nạp dữ liệu đầu tiên, viết `.gitignore` cho thư
mục dữ liệu thật và quyết định danh sách cột PII cần drop/hash. Không "để sau dọn".

---

## 6. Coverage gating — thà ẩn số còn hơn hiện số sai

**Nguyên tắc:** Khi một chỉ số phụ thuộc dữ liệu bổ sung chưa đầy đủ (ví dụ COGS chỉ có trong
CSV thủ công, không phải 100% đơn hàng có COGS), dashboard phải **đo độ phủ (coverage %)** và
**gác cổng (gate) hiển thị** theo ngưỡng, thay vì hiển thị số liệu tính trên dữ liệu thiếu như
thể nó đầy đủ.

**Ví dụ ngưỡng dùng trong dự án:** `<80% → ẩn visual lợi nhuận + banner "Profit unavailable"`;
`80–95% → hiện kèm chip vàng "partial coverage"`; `≥95% → tin cậy hoàn toàn`.

**Vì sao:** Một dashboard hiển thị "lợi nhuận: $50,000" trông rất đáng tin dù chỉ tính được từ
60% đơn hàng có COGS — người xem không biết để nghi ngờ. Gating buộc sự thiếu hụt dữ liệu phải
**hiển thị ra**, không bị chôn giấu dưới lớp số liệu trông hợp lý.

**Áp dụng lần sau:** Với mọi chỉ số phụ thuộc nguồn dữ liệu "không đảm bảo 100% đầy đủ" (dữ
liệu thủ công, tích hợp bên thứ ba, plugin parser...), luôn đi kèm: (1) cột/measure đo coverage
%, (2) ngưỡng gate 3 mức, (3) UI feedback tương ứng (ẩn / chip cảnh báo / tin cậy).

---

## 7. Reconciliation — đối chiếu chéo để bắt drift sớm

**Nguyên tắc:** Khi có 2 nguồn cùng phản ánh một khái niệm gần giống nhau (ví dụ: phí ship
trong CSV thủ công vs phí ship thu của khách trong Woo API), xây **view đối chiếu (recon)**
so sánh 2 nguồn thay vì chỉ tin một nguồn.

**Vì sao:** Sai lệch giữa 2 nguồn là tín hiệu sớm của: nhập liệu sai, đổi định nghĩa cột, hoặc
lỗi pipeline — phát hiện qua recon view **trước khi** nó lan ra dashboard và bị người dùng cuối
phát hiện trước.

**Áp dụng lần sau:** Bất cứ khi nào có "dữ liệu thủ công" song song với "dữ liệu hệ thống" (rất
phổ biến: kế toán nhập tay vs ERP, CS ghi chú vs CRM), luôn dựng `recon_*` view/mart riêng, và
để các cột "không chính thức" (Revenue/Profit tự tính trong CSV) chỉ tồn tại trong recon —
không bao giờ copy sang làm chỉ số chính thức.

---

## 8. Ghi log thay đổi định nghĩa chỉ số (Metric Changes Log)

**Nguyên tắc:** Mỗi khi công thức của một chỉ số (metric) thay đổi, ghi lại: ngày, chỉ số, công
thức cũ, công thức mới, lý do, ảnh hưởng thực tế lên số liệu, và cách đã verify — trong một
file append-only riêng (`METRIC_CHANGES.md`), không sửa âm thầm.

**Bài học thực tế (H1/H4):** Coverage % ban đầu tính trên **mẫu số "tất cả đơn hàng"**
(`all orders`), khiến ~900 đơn hủy/thất bại (chưa từng phát sinh phí thanh toán) bị tính là
"thiếu dữ liệu" — coverage đo được 79.5% (dưới ngưỡng 80%, kích hoạt cảnh báo sai). Sau khi đổi
mẫu số về **"chỉ đơn có doanh thu" (revenue orders)** — đúng logic vì lợi nhuận/phí chỉ có ý
nghĩa với đơn đã phát sinh doanh thu — coverage thực tế là 98.03%. Bài học tổng quát: **chọn
đúng mẫu số (denominator) quan trọng ngang chọn đúng công thức**, và một chỉ số coverage phải
dùng cùng cơ sở mẫu số với chỉ số nó đang gate.

**Áp dụng lần sau:** Trước khi định nghĩa bất kỳ tỷ lệ % nào (coverage, conversion, match rate),
tự hỏi: "mẫu số có bao gồm các trường hợp *về bản chất không thể* có tử số không?" Nếu có, đó
là dấu hiệu chọn sai mẫu số. Và luôn duy trì một log thay đổi định nghĩa — nó là "git blame" cho
số liệu, giúp trả lời câu hỏi "tại sao số này tuần trước khác tuần này" trong vòng 30 giây thay
vì phải đào lại lịch sử commit.

---

## 9. Tài liệu hóa là một phần của sản phẩm dữ liệu

**Nguyên tắc:** Từ điển dữ liệu (data dictionary), định nghĩa chỉ số (metrics definition), và
tài liệu kiến trúc **không phải là việc làm thêm sau khi xong code** — chúng là một phần bàn
giao bắt buộc, ngang hàng với chính pipeline.

**Vì sao:** Một kho dữ liệu không có tài liệu chỉ có giá trị với người đã xây nó. Data
dictionary trả lời "cột này nghĩa là gì, đơn vị gì, nguồn nào" — khi thiếu, người dùng BI (kể cả
chính bạn 6 tháng sau) sẽ đoán mò và tạo ra DAX sai. Metrics definition là hợp đồng giữa
kỹ thuật và nghiệp vụ về ý nghĩa một con số.

**Áp dụng lần sau:** Viết `DATA_MODEL.md` (schema/grain/công thức), `METRICS_DEFINITION.md`
(định nghĩa từng chỉ số + DAX), và `METRIC_CHANGES.md` (log thay đổi) **song song** với lúc viết
model dbt đầu tiên — không để "sprint sau" vì sprint sau sẽ không bao giờ tới.

---

## Checklist: Bắt đầu một dự án BI/DA mới

1. **Xác định nguồn sự thật (source of truth)** cho từng domain dữ liệu (đơn hàng, chi phí,
   hành vi web...) — lập bảng "hệ thống nào là chuẩn" trước khi viết bất kỳ dòng code nào.
2. **Thiết kế `.gitignore` và quy tắc PII trước** — quyết định cột nào drop, cột nào hash, salt
   lưu ở đâu (offline, tách khỏi git/db).
3. **Dựng 3 schema `raw` / `staging` / `marts`** (hoặc bronze/silver/gold) ngay từ đầu, kể cả
   dự án nhỏ.
4. **Viết Python/EL chỉ để kéo & nạp** — không nghiệp vụ. Mọi transform để dbt (hoặc công cụ
   transform tương đương) xử lý.
5. **Định nghĩa grain + surrogate key** cho từng fact/dimension trước khi viết SQL model.
6. **Xác định chỉ số cốt lõi và nơi nó "sống" duy nhất** (single source of truth) — tránh để một
   chỉ số có thể bị cộng nhầm ở nhiều grain.
7. **Viết `METRICS_DEFINITION.md`** cho từng chỉ số kèm công thức, và **`METRIC_CHANGES.md`**
   append-only ngay từ chỉ số đầu tiên.
8. **Thêm dbt tests + recon views** đối chiếu các nguồn dữ liệu song song (thủ công vs hệ thống).
9. **Thiết kế coverage gating** cho mọi chỉ số phụ thuộc dữ liệu chưa chắc đầy đủ — ẩn/cảnh báo
   thay vì hiển thị số sai.
10. **Data dictionary + tài liệu kiến trúc** viết song song với code, không để "làm sau".
11. Chỉ sau khi 1–10 ổn định mới bắt đầu build dashboard Power BI/BI tool — dashboard đẹp trên
    số liệu sai vẫn là sai.
