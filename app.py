"""
Smart Inventory Intelligence - Flask backend.

All analytics are computed by SQL (CTEs, window functions, views, aggregates);
Python only routes requests and shapes JSON.

Run:  python app.py      ->  http://127.0.0.1:5000
"""
import os
import re
import sqlite3

from flask import Flask, g, jsonify, render_template, request

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "inventory.db")

app = Flask(__name__)


# ---------------------------------------------------------------- DB helpers
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def rows(sql, params=()):
    return [dict(r) for r in get_db().execute(sql, params).fetchall()]


def one(sql, params=()):
    r = get_db().execute(sql, params).fetchone()
    return dict(r) if r else None


def error(msg, code=400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------- Pages
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- KPIs
@app.route("/api/kpis")
def kpis():
    data = one("""
        WITH inv AS (
            SELECT COUNT(*)                          AS products,
                   COALESCE(SUM(stock_qty*unit_cost),0)  AS cost_value,
                   COALESCE(SUM(stock_qty*unit_price),0) AS retail_value,
                   SUM(stock_qty <= reorder_level AND stock_qty > 0) AS low_stock,
                   SUM(stock_qty = 0)                AS out_of_stock
              FROM products WHERE is_active = 1
        ),
        sales30 AS (
            SELECT COALESCE(SUM(revenue),0) AS revenue,
                   COALESCE(SUM(profit),0)  AS profit,
                   COALESCE(SUM(qty),0)     AS units
              FROM v_sales_lines WHERE sale_date >= date('now','-30 day')
        ),
        sales_prev AS (
            SELECT COALESCE(SUM(revenue),0) AS revenue
              FROM v_sales_lines
             WHERE sale_date <  date('now','-30 day')
               AND sale_date >= date('now','-60 day')
        ),
        dead AS (
            SELECT COUNT(*) AS n, COALESCE(SUM(p.stock_qty*p.unit_cost),0) AS value
              FROM products p
             WHERE p.is_active = 1 AND p.stock_qty > 0
               AND NOT EXISTS (SELECT 1 FROM v_sales_lines s
                                WHERE s.product_id = p.product_id
                                  AND s.sale_date >= date('now','-60 day'))
        )
        SELECT inv.*, sales30.revenue AS revenue_30d, sales30.profit AS profit_30d,
               sales30.units AS units_30d, sales_prev.revenue AS revenue_prev_30d,
               dead.n AS dead_items, dead.value AS dead_value
          FROM inv, sales30, sales_prev, dead
    """)
    prev = data["revenue_prev_30d"]
    data["revenue_growth_pct"] = round((data["revenue_30d"] - prev) * 100 / prev, 1) if prev else None
    data["margin_pct"] = round(data["profit_30d"] * 100 / data["revenue_30d"], 1) if data["revenue_30d"] else 0
    return jsonify(data)


# ---------------------------------------------------------------- Trends
@app.route("/api/sales-trend")
def sales_trend():
    days = min(int(request.args.get("days", 60)), 180)
    return jsonify(rows("""
        WITH RECURSIVE cal(d) AS (
            SELECT date('now', ? )
            UNION ALL SELECT date(d,'+1 day') FROM cal WHERE d < date('now')
        ),
        daily AS (
            SELECT sale_date, SUM(revenue) AS revenue, SUM(profit) AS profit, SUM(qty) AS units
              FROM v_sales_lines GROUP BY sale_date
        )
        SELECT cal.d AS day,
               ROUND(COALESCE(revenue,0),2) AS revenue,
               ROUND(COALESCE(profit,0),2)  AS profit,
               COALESCE(units,0)            AS units,
               ROUND(AVG(COALESCE(revenue,0)) OVER (ORDER BY cal.d
                     ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),2) AS moving_avg_7d
          FROM cal LEFT JOIN daily ON daily.sale_date = cal.d
         ORDER BY cal.d
    """, (f"-{days - 1} day",)))


@app.route("/api/category-summary")
def category_summary():
    return jsonify(rows("""
        SELECT c.name AS category,
               COUNT(DISTINCT p.product_id)                 AS products,
               SUM(p.stock_qty)                             AS units_in_stock,
               ROUND(SUM(p.stock_qty*p.unit_cost),2)        AS stock_value,
               ROUND(COALESCE(MAX(r.revenue),0),2)          AS revenue_90d,
               ROUND(COALESCE(MAX(r.profit),0),2)           AS profit_90d
          FROM categories c
          JOIN products p ON p.category_id = c.category_id AND p.is_active = 1
          LEFT JOIN (
                SELECT p2.category_id, SUM(s.revenue) AS revenue, SUM(s.profit) AS profit
                  FROM v_sales_lines s JOIN products p2 ON p2.product_id = s.product_id
                 WHERE s.sale_date >= date('now','-90 day')
                 GROUP BY p2.category_id) r ON r.category_id = c.category_id
         GROUP BY c.category_id
         ORDER BY revenue_90d DESC
    """))


# ---------------------------------------------------------------- Intelligence
@app.route("/api/reorder-suggestions")
def reorder_suggestions():
    """Items at/below reorder level plus items that will run out before a
    new order could arrive (stock cover < supplier lead time)."""
    return jsonify(rows("""
        WITH velocity AS (
            SELECT product_id, SUM(qty) * 1.0 / 30 AS avg_daily
              FROM v_sales_lines
             WHERE sale_date >= date('now','-30 day')
             GROUP BY product_id
        )
        SELECT v.product_id, v.sku, v.name, v.category, v.supplier, v.lead_time_days,
               v.stock_qty, v.reorder_level, v.reorder_qty, v.status,
               ROUND(COALESCE(ve.avg_daily,0),2) AS avg_daily_sales,
               CASE WHEN COALESCE(ve.avg_daily,0) > 0
                    THEN ROUND(v.stock_qty / ve.avg_daily, 1) END AS days_of_cover,
               -- order enough for lead time + 30 days of selling, minus what we have
               MAX(v.reorder_qty,
                   CAST(ROUND(COALESCE(ve.avg_daily,0) * (v.lead_time_days + 30)) AS INTEGER) - v.stock_qty
               ) AS suggested_order_qty,
               ROUND(MAX(v.reorder_qty,
                   CAST(ROUND(COALESCE(ve.avg_daily,0) * (v.lead_time_days + 30)) AS INTEGER) - v.stock_qty
               ) * v.unit_cost, 2) AS estimated_cost,
               CASE WHEN v.status = 'OUT' THEN 'CRITICAL'
                    WHEN ve.avg_daily > 0 AND v.stock_qty / ve.avg_daily < v.lead_time_days THEN 'HIGH'
                    ELSE 'MEDIUM' END AS priority
          FROM v_product_status v
          LEFT JOIN velocity ve ON ve.product_id = v.product_id
         WHERE v.status IN ('OUT','LOW')
            OR (ve.avg_daily > 0 AND v.stock_qty / ve.avg_daily < v.lead_time_days + 3)
         ORDER BY CASE priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,
                  days_of_cover
    """))


@app.route("/api/abc-analysis")
def abc_analysis():
    """ABC classification by revenue (Pareto): A = first 80% of revenue,
    B = next 15%, C = last 5%.  Uses CTE + window functions."""
    return jsonify(rows("""
        WITH rev AS (
            SELECT p.product_id, p.sku, p.name, c.name AS category,
                   SUM(s.revenue) AS revenue, SUM(s.qty) AS units
              FROM v_sales_lines s
              JOIN products p   ON p.product_id = s.product_id
              JOIN categories c ON c.category_id = p.category_id
             WHERE s.sale_date >= date('now','-90 day')
             GROUP BY p.product_id
        ),
        ranked AS (
            SELECT *,
                   SUM(revenue) OVER (ORDER BY revenue DESC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running,
                   SUM(revenue) OVER () AS total,
                   RANK() OVER (ORDER BY revenue DESC) AS rnk
              FROM rev
        )
        SELECT rnk AS rank, sku, name, category, units,
               ROUND(revenue,2) AS revenue,
               ROUND(revenue*100.0/total,2) AS share_pct,
               ROUND(running*100.0/total,2) AS cumulative_pct,
               CASE WHEN (running - revenue)*1.0/total < 0.80 THEN 'A'
                    WHEN (running - revenue)*1.0/total < 0.95 THEN 'B'
                    ELSE 'C' END AS abc_class
          FROM ranked
         ORDER BY rnk
    """))


@app.route("/api/dead-stock")
def dead_stock():
    """Products holding stock but with no sale in the last 60 days."""
    return jsonify(rows("""
        SELECT v.sku, v.name, v.category, v.stock_qty, v.stock_value,
               MAX(s.sale_date) AS last_sale,
               CAST(julianday('now') - julianday(MAX(s.sale_date)) AS INTEGER) AS days_since_sale
          FROM v_product_status v
          LEFT JOIN v_sales_lines s ON s.product_id = v.product_id
         WHERE v.stock_qty > 0
         GROUP BY v.product_id
        HAVING MAX(s.sale_date) IS NULL OR MAX(s.sale_date) < date('now','-60 day')
         ORDER BY v.stock_value DESC
    """))


@app.route("/api/turnover")
def turnover():
    """Inventory turnover = COGS(90d) annualised / current inventory value.
    Also shows how many days it takes to sell the current stock."""
    return jsonify(rows("""
        WITH cogs AS (
            SELECT product_id, SUM(cogs) AS cogs_90d, SUM(qty) AS units_90d
              FROM v_sales_lines WHERE sale_date >= date('now','-90 day')
             GROUP BY product_id
        )
        SELECT v.sku, v.name, v.category, v.stock_qty,
               ROUND(v.stock_value,2) AS stock_value,
               COALESCE(c.units_90d,0) AS units_sold_90d,
               CASE WHEN v.stock_value > 0
                    THEN ROUND(COALESCE(c.cogs_90d,0)*(365.0/90)/v.stock_value, 2) END AS turnover_ratio,
               CASE WHEN COALESCE(c.units_90d,0) > 0
                    THEN ROUND(v.stock_qty / (c.units_90d/90.0), 0) END AS days_to_sell_out,
               NTILE(4) OVER (ORDER BY COALESCE(c.cogs_90d,0)*1.0/NULLIF(v.stock_value,0) DESC) AS speed_quartile
          FROM v_product_status v
          LEFT JOIN cogs c ON c.product_id = v.product_id
         ORDER BY turnover_ratio DESC
    """))


@app.route("/api/forecast")
def forecast():
    """Simple demand forecast: blend of 7-day and 30-day average daily sales,
    then projected stock-out date."""
    return jsonify(rows("""
        WITH d7 AS (
            SELECT product_id, SUM(qty)/7.0 AS a7 FROM v_sales_lines
             WHERE sale_date >= date('now','-7 day') GROUP BY product_id),
        d30 AS (
            SELECT product_id, SUM(qty)/30.0 AS a30 FROM v_sales_lines
             WHERE sale_date >= date('now','-30 day') GROUP BY product_id),
        f AS (
            SELECT v.product_id, v.sku, v.name, v.stock_qty,
                   ROUND(0.6*COALESCE(d7.a7,0) + 0.4*COALESCE(d30.a30,0), 2) AS forecast_daily
              FROM v_product_status v
              LEFT JOIN d7  ON d7.product_id  = v.product_id
              LEFT JOIN d30 ON d30.product_id = v.product_id)
        SELECT sku, name, stock_qty, forecast_daily,
               ROUND(forecast_daily*30,0) AS forecast_next_30d,
               CASE WHEN forecast_daily > 0
                    THEN date('now', '+' || CAST(stock_qty/forecast_daily AS INTEGER) || ' day') END AS stockout_date
          FROM f WHERE forecast_daily > 0
         ORDER BY stock_qty/forecast_daily
         LIMIT 15
    """))


@app.route("/api/top-products")
def top_products():
    return jsonify(rows("""
        SELECT p.name, ROUND(SUM(s.revenue),2) AS revenue, SUM(s.qty) AS units,
               ROUND(SUM(s.profit),2) AS profit
          FROM v_sales_lines s JOIN products p ON p.product_id = s.product_id
         WHERE s.sale_date >= date('now','-30 day')
         GROUP BY p.product_id ORDER BY revenue DESC LIMIT 8
    """))


# ---------------------------------------------------------------- Products CRUD
@app.route("/api/products")
def list_products():
    q = f"%{request.args.get('q', '').strip()}%"
    status = request.args.get("status", "").upper()
    category = request.args.get("category", "")
    sql = "SELECT * FROM v_product_status WHERE (name LIKE ? OR sku LIKE ?)"
    params = [q, q]
    if status in ("OK", "LOW", "OUT"):
        sql += " AND status = ?"
        params.append(status)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY name"
    return jsonify(rows(sql, params))


@app.route("/api/lookups")
def lookups():
    return jsonify({
        "categories": rows("SELECT category_id AS id, name FROM categories ORDER BY name"),
        "suppliers": rows("SELECT supplier_id AS id, name, lead_time_days FROM suppliers ORDER BY name"),
    })


def _validate_product(d):
    try:
        name = str(d.get("name", "")).strip()
        cost = float(d["unit_cost"])
        price = float(d["unit_price"])
        rl = int(d.get("reorder_level", 10))
        rq = int(d.get("reorder_qty", 50))
        cat = int(d["category_id"])
        sup = int(d["supplier_id"])
    except (KeyError, ValueError, TypeError):
        return None, "Please fill all fields with valid values."
    if not name:
        return None, "Name is required."
    if cost < 0 or price < 0 or rl < 0 or rq <= 0:
        return None, "Cost, price and reorder values must be positive."
    return dict(name=name, unit_cost=cost, unit_price=price, reorder_level=rl,
                reorder_qty=rq, category_id=cat, supplier_id=sup), None


@app.route("/api/products", methods=["POST"])
def add_product():
    d = request.get_json(force=True, silent=True) or {}
    v, err = _validate_product(d)
    if err:
        return error(err)
    db = get_db()
    next_no = (one("SELECT COALESCE(MAX(product_id),0)+1 AS n FROM products") or {"n": 1})["n"]
    sku = (d.get("sku") or f"SKU-{next_no:04d}").strip()
    try:
        cur = db.execute(
            """INSERT INTO products(sku,name,category_id,supplier_id,unit_cost,unit_price,
                                    reorder_level,reorder_qty)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sku, v["name"], v["category_id"], v["supplier_id"], v["unit_cost"],
             v["unit_price"], v["reorder_level"], v["reorder_qty"]))
        opening = int(d.get("opening_stock") or 0)
        if opening > 0:
            db.execute(
                """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note)
                   VALUES (?,?,?,?,?)""",
                (cur.lastrowid, "IN", opening, v["unit_cost"], "Opening stock"))
        db.commit()
    except sqlite3.IntegrityError as e:
        db.rollback()
        return error("Could not save product: " + str(e))
    return jsonify({"product_id": cur.lastrowid, "sku": sku}), 201


@app.route("/api/products/<int:pid>", methods=["PUT"])
def update_product(pid):
    d = request.get_json(force=True, silent=True) or {}
    v, err = _validate_product(d)
    if err:
        return error(err)
    db = get_db()
    try:
        cur = db.execute(
            """UPDATE products SET name=?, category_id=?, supplier_id=?, unit_cost=?,
                      unit_price=?, reorder_level=?, reorder_qty=? WHERE product_id=?""",
            (v["name"], v["category_id"], v["supplier_id"], v["unit_cost"],
             v["unit_price"], v["reorder_level"], v["reorder_qty"], pid))
        db.commit()
    except sqlite3.IntegrityError as e:
        db.rollback()
        return error(str(e))
    if cur.rowcount == 0:
        return error("Product not found", 404)
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    """Soft delete - history in stock_movements is preserved."""
    db = get_db()
    cur = db.execute("UPDATE products SET is_active = 0 WHERE product_id = ?", (pid,))
    db.commit()
    if cur.rowcount == 0:
        return error("Product not found", 404)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- Movements
@app.route("/api/movements")
def list_movements():
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify(rows("""
        SELECT m.movement_id, m.created_at, p.sku, p.name, m.movement_type,
               m.quantity, m.unit_price, m.note
          FROM stock_movements m JOIN products p ON p.product_id = m.product_id
         ORDER BY m.created_at DESC, m.movement_id DESC LIMIT ?
    """, (limit,)))


@app.route("/api/movements", methods=["POST"])
def add_movement():
    d = request.get_json(force=True, silent=True) or {}
    try:
        pid = int(d["product_id"])
        mtype = str(d["movement_type"]).upper()
        qty = int(d["quantity"])
    except (KeyError, ValueError, TypeError):
        return error("Product, type and quantity are required.")
    if mtype not in ("IN", "OUT", "ADJUST") or qty == 0:
        return error("Invalid movement type or quantity.")
    if mtype in ("IN", "OUT") and qty < 0:
        return error("Quantity must be positive for IN/OUT.")
    db = get_db()
    prod = one("SELECT unit_cost, unit_price FROM products WHERE product_id=? AND is_active=1", (pid,))
    if not prod:
        return error("Product not found", 404)
    price = d.get("unit_price")
    if price in (None, ""):
        price = prod["unit_price"] if mtype == "OUT" else prod["unit_cost"] if mtype == "IN" else 0
    try:
        db.execute(
            """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note)
               VALUES (?,?,?,?,?)""",
            (pid, mtype, qty, float(price), (d.get("note") or "").strip() or None))
        db.commit()
    except sqlite3.DatabaseError as e:
        db.rollback()
        # message comes from the trigger: "Insufficient stock for this movement"
        return error(str(e), 409)
    return jsonify(one("SELECT stock_qty FROM products WHERE product_id=?", (pid,))), 201


# ---------------------------------------------------------------- Alerts / suppliers
@app.route("/api/alerts")
def alerts():
    return jsonify(rows("""
        SELECT a.alert_id, a.alert_type, a.message, a.created_at, p.sku
          FROM alerts a JOIN products p ON p.product_id = a.product_id
         WHERE a.is_resolved = 0
         ORDER BY CASE a.alert_type WHEN 'OUT_OF_STOCK' THEN 0 ELSE 1 END, a.created_at DESC
    """))


@app.route("/api/suppliers")
def suppliers():
    return jsonify(rows("""
        SELECT s.supplier_id, s.name, s.contact_email, s.phone, s.lead_time_days,
               COUNT(p.product_id) AS products,
               COALESCE(SUM(p.stock_qty*p.unit_cost),0) AS stock_value,
               COALESCE(SUM(p.stock_qty <= p.reorder_level),0) AS items_to_reorder
          FROM suppliers s LEFT JOIN products p ON p.supplier_id = s.supplier_id AND p.is_active=1
         GROUP BY s.supplier_id ORDER BY stock_value DESC
    """))


# ---------------------------------------------------------------- SQL explorer
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex)\b", re.I)

SAMPLE_QUERIES = [
    {"title": "Top 5 products by profit (90 days)",
     "sql": "SELECT p.name, ROUND(SUM(profit),2) AS profit\nFROM v_sales_lines s\nJOIN products p USING (product_id)\nWHERE sale_date >= date('now','-90 day')\nGROUP BY p.product_id\nORDER BY profit DESC\nLIMIT 5;"},
    {"title": "Stock value by category",
     "sql": "SELECT category, COUNT(*) AS items, ROUND(SUM(stock_value),2) AS value\nFROM v_product_status\nGROUP BY category\nORDER BY value DESC;"},
    {"title": "Month-over-month revenue (window fn)",
     "sql": "WITH m AS (\n  SELECT strftime('%Y-%m', sale_date) AS month, SUM(revenue) AS revenue\n  FROM v_sales_lines GROUP BY month)\nSELECT month, ROUND(revenue,2) AS revenue,\n       ROUND((revenue - LAG(revenue) OVER (ORDER BY month))*100.0\n             / LAG(revenue) OVER (ORDER BY month),1) AS growth_pct\nFROM m;"},
    {"title": "Best-selling weekday",
     "sql": "SELECT CASE strftime('%w', sale_date)\n  WHEN '0' THEN 'Sun' WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue'\n  WHEN '3' THEN 'Wed' WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri' ELSE 'Sat' END AS weekday,\n  ROUND(SUM(revenue),2) AS revenue\nFROM v_sales_lines GROUP BY strftime('%w', sale_date)\nORDER BY revenue DESC;"},
    {"title": "Supplier dependency (HAVING)",
     "sql": "SELECT s.name, COUNT(*) AS products\nFROM products p JOIN suppliers s USING (supplier_id)\nGROUP BY s.supplier_id\nHAVING COUNT(*) >= 5;"},
    {"title": "Which triggers exist?",
     "sql": "SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger';"},
]


@app.route("/api/sql-samples")
def sql_samples():
    return jsonify(SAMPLE_QUERIES)


@app.route("/api/sql", methods=["POST"])
def run_sql():
    """Read-only SQL playground. Opens a separate read-only connection and
    only accepts a single SELECT / WITH statement."""
    sql = ((request.get_json(force=True, silent=True) or {}).get("sql") or "").strip().rstrip(";").strip()
    if not sql:
        return error("Write a query first.")
    if ";" in sql:
        return error("Only one statement at a time.")
    if not re.match(r"^(select|with)\b", sql, re.I) or FORBIDDEN.search(sql):
        return error("Only read-only SELECT queries are allowed.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        data = cur.fetchmany(500)
        cols = [c[0] for c in cur.description] if cur.description else []
        return jsonify({"columns": cols, "rows": [list(r) for r in data],
                        "truncated": len(data) == 500})
    except sqlite3.Error as e:
        return error(str(e))
    finally:
        conn.close()


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        import seed
        seed.main()
    app.run(debug=True)
