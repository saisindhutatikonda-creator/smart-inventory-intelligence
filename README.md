# Smart Inventory Intelligence Website

A full-stack inventory management and analytics website where **SQL does the thinking**.
Built with **Flask + SQLite + vanilla JavaScript (Chart.js)**.

## Run it (2 minutes)

```bash
pip install -r requirements.txt
python seed.py        # creates inventory.db with 40 products and ~6,000 stock movements
python app.py         # open http://127.0.0.1:5000
```

> The charts load Chart.js from a CDN, so keep internet on when you open it.

## What the website does

| Page | Features |
|------|----------|
| Dashboard | KPI cards, revenue trend + 7-day moving average, revenue by category, top products, live alerts |
| Products | Search, filter by status/category, add / edit / delete (soft delete) |
| Stock Movements | Record sales (OUT), purchases (IN), adjustments; full movement history |
| Reorder Alerts | Suggested purchase orders (priority, days of cover, quantity, cost) + stock-out forecast |
| Analytics | ABC (Pareto) analysis, dead stock, inventory turnover |
| Suppliers | Lead time, stock value, items to reorder per supplier |
| SQL Explorer | Run your own read-only SELECT queries, with sample queries |

## SQL concepts used (map to your SQL internship modules)

| Concept | Where |
|---------|-------|
| Relational design, PK / FK, normalisation (3NF) | `schema.sql` - 5 tables |
| CHECK, UNIQUE, NOT NULL, DEFAULT constraints | `schema.sql` |
| Indexes | `idx_mov_product_date`, `idx_mov_type_date`, ... |
| **Triggers** (business rules in the DB) | block negative stock, auto-update stock, raise and auto-resolve alerts |
| **Views** | `v_sales_lines`, `v_product_status` |
| Joins (INNER / LEFT) | almost every endpoint in `app.py` |
| Aggregation, GROUP BY, HAVING | `/api/category-summary`, SQL Explorer samples |
| **CTEs** (incl. a recursive calendar) | `/api/sales-trend`, `/api/kpis` |
| **Window functions** (SUM OVER, RANK, NTILE, AVG OVER, LAG) | ABC analysis, turnover, moving average |
| Subqueries / EXISTS | dead stock, KPIs |
| Transactions and integrity | `add_movement` rolls back when a trigger aborts |
| Security | parameterised queries (no SQL injection), read-only SQL playground |
| Performance | indexes on the hot columns used by the analytics queries |

## Project structure

```
inventory-intelligence/
  schema.sql          tables, indexes, triggers, views
  seed.py             builds inventory.db with 120 days of realistic data
  app.py              Flask REST API (all analytics are SQL queries)
  templates/index.html
  static/style.css
  static/app.js
  requirements.txt
```

## Key API endpoints

`GET /api/kpis` · `/api/sales-trend` · `/api/reorder-suggestions` · `/api/abc-analysis` ·
`/api/dead-stock` · `/api/turnover` · `/api/forecast` · `/api/products` (CRUD) ·
`/api/movements` · `/api/alerts` · `/api/suppliers` · `POST /api/sql`

## How the intelligence works

* **Reorder suggestion** = max(reorder qty, 30-day sales velocity x (supplier lead time + 30 days) - current stock).
  Priority is CRITICAL if out of stock, HIGH if stock will run out before a new order could arrive.
* **ABC analysis**: products ranked by 90-day revenue; running share under 80% = A, under 95% = B, rest = C.
* **Dead stock**: stock on hand but no sale in 60 days.
* **Turnover** = (90-day COGS annualised) / current stock value.
* **Forecast** = 0.6 x 7-day average + 0.4 x 30-day average daily sales; stock-out date = today + stock / forecast.

## Ideas to extend

User login with roles, barcode scan, email alerts, switch to MySQL/PostgreSQL, CSV import/export.
