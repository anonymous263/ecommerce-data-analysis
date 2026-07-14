# Maven Fuzzy Factory — Data Dictionary (practice/demo dataset)

> English translation + summary of `E-commerce data sample/[Đọc cái này trước] Tài liệu Data Dictionary.docx`.
> This is the **Maven Fuzzy Factory** teaching dataset used for practice only. Per project rules it lives in an
> **isolated namespace and is never mixed with the real WooCommerce marts**. The `.docx` and its CSVs are gitignored.

## Scope

Six tables covering a simplified e-commerce clickstream + order model: web sessions → pageviews → orders → order
items → refunds, plus a product catalog. Grain and keys below match the source dictionary.

## Tables

### 1. `orders` — order header
General information about placed orders.

| Field | Description |
|---|---|
| `order_id` | Unique identifier for each order (**PK**). |
| `created_at` | Timestamp the order was placed. |
| `website_session_id` | The web session the order belongs to (**FK**). |
| `user_id` | Unique identifier of the purchasing user (**FK**). |
| `primary_product_id` | The primary product when the order is a combo/bundle (**FK**). |
| `items_purchased` | Number of products in the order. |
| `price_usd` | Total order value in USD. |
| `cogs_usd` | Total cost of goods sold for the order, in USD. |

### 2. `order_items` — order line detail
Detail of each specific product within an order.

| Field | Description |
|---|---|
| `order_item_id` | Unique identifier for each item line (**PK**). |
| `created_at` | Timestamp the item was recorded on the order. |
| `order_id` | The order this item belongs to (**FK**). |
| `product_id` | Product identifier (**FK**). |
| `is_primary_item` | Binary flag; `1` if this is the order's primary product. |
| `price_usd` | Sale price of this item alone, in USD. |
| `cogs_usd` | Cost of goods for this item alone, in USD. |

### 3. `order_item_refunds` — item refunds
Tracks refunds issued to customers.

| Field | Description |
|---|---|
| `order_item_refund_id` | Unique identifier for each refund (**PK**). |
| `created_at` | Timestamp the refund was issued. |
| `order_item_id` | The specific item being refunded (**FK**). |
| `order_id` | The order containing the refunded item (**FK**). |
| `refund_amount_usd` | Amount refunded to the customer, in USD. |

### 4. `products` — product catalog
Catalog of products on the system.

| Field | Description |
|---|---|
| `product_id` | Unique product identifier (**PK**). |
| `created_at` | Timestamp the product was launched/added. |
| `product_name` | Product name. |

### 5. `website_sessions` — web sessions
User visits to the website.

| Field | Description |
|---|---|
| `website_session_id` | Unique identifier for each session (**PK**). |
| `created_at` | Timestamp the session started. |
| `user_id` | User identifier (**FK**). |
| `is_repeat_session` | Binary flag; `1` if the user has visited before (returning customer). |
| `utm_source` | Traffic source (e.g. google, facebook, bing). |
| `utm_campaign` | Marketing campaign name that drove the visit. |
| `utm_content` | Specific ad content or content variant. |
| `device_type` | Device used (`mobile` or `desktop`). |
| `http_referer` | URL of the previous page that referred the user. |

### 6. `website_pageviews` — pageviews
Each page a user viewed within a session.

| Field | Description |
|---|---|
| `website_pageview_id` | Unique identifier for each pageview (**PK**). |
| `created_at` | Timestamp the page was viewed. |
| `website_session_id` | The session this pageview belongs to (**FK**). |
| `pageview_url` | URL path of the viewed page. |

## Technical notes
- **PK (Primary Key):** distinguishes rows; must be unique.
- **FK (Foreign Key):** links information across tables.

## Relationship to this project
This dataset is **not** part of the real WooCommerce warehouse. Do not join it to `raw.woo_*`, `staging`, or any
`marts_*` schema. It is retained as a second public/demo dataset alongside the synthetic Woo sample (Phase 7). Note the
naming differs from the real model: here order-level `cogs_usd` and `price_usd` live on `orders`, whereas the real model
keeps **revenue only on `fact_order_item`** and derives cost from the manual sheet — see `docs/DATA_MODEL.md`.
