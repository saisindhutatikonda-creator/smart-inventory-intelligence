"""
Creates inventory.db from schema.sql and fills it with ~120 days of
realistic stock movements (purchases, sales, restocks) so that every
analytics screen has meaningful data.

Run:  python seed.py
"""
import os
import random
import sqlite3
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "inventory.db")
DAYS = 120

random.seed(42)

CATEGORIES = ["Electronics", "Groceries", "Stationery", "Home & Kitchen",
              "Personal Care", "Sports", "Toys", "Furniture"]

SUPPLIERS = [  # name, email, phone, lead time
    ("TechWorld Distributors", "sales@techworld.example", "+91 90000 11111", 6),
    ("FreshMart Wholesale",    "orders@freshmart.example", "+91 90000 22222", 2),
    ("PaperPlus Supplies",     "hello@paperplus.example",  "+91 90000 33333", 4),
    ("HomeNest Traders",       "care@homenest.example",    "+91 90000 44444", 7),
    ("ActiveLife Sports",      "b2b@activelife.example",   "+91 90000 55555", 8),
    ("PlayTime Imports",       "trade@playtime.example",   "+91 90000 66666", 10),
]

# name, category, supplier idx, cost, price, avg daily demand
# flags: "dead" -> stops selling ~70 days ago, "short" -> stops restocking (goes low/out)
PRODUCTS = [
    ("Wireless Mouse",          "Electronics", 0, 350, 599, 4.0, ""),
    ("USB-C Cable 1m",          "Electronics", 0, 90, 199, 7.0, ""),
    ("Bluetooth Earbuds",       "Electronics", 0, 900, 1799, 2.5, "short"),
    ("Power Bank 10000mAh",     "Electronics", 0, 800, 1399, 2.0, ""),
    ("Phone Stand",             "Electronics", 0, 120, 299, 1.5, "dead"),
    ("HDMI Cable 2m",           "Electronics", 0, 150, 349, 1.2, ""),
    ("Basmati Rice 5kg",        "Groceries", 1, 420, 560, 6.0, ""),
    ("Sunflower Oil 1L",        "Groceries", 1, 110, 145, 9.0, ""),
    ("Whole Wheat Flour 5kg",   "Groceries", 1, 190, 250, 5.0, ""),
    ("Green Tea 100 bags",      "Groceries", 1, 160, 240, 2.0, "short"),
    ("Almonds 500g",            "Groceries", 1, 380, 520, 2.2, ""),
    ("Instant Noodles Pack",    "Groceries", 1, 55, 80, 8.0, ""),
    ("A4 Notebook 200 pages",   "Stationery", 2, 45, 90, 10.0, ""),
    ("Gel Pen Pack of 10",      "Stationery", 2, 40, 85, 8.0, ""),
    ("Sticky Notes Set",        "Stationery", 2, 30, 70, 3.0, ""),
    ("Desk Organizer",          "Stationery", 2, 180, 399, 0.8, "dead"),
    ("Highlighter Set",         "Stationery", 2, 60, 130, 2.5, ""),
    ("Non-stick Frying Pan",    "Home & Kitchen", 3, 450, 899, 1.5, ""),
    ("Steel Water Bottle 1L",   "Home & Kitchen", 3, 220, 449, 3.0, ""),
    ("Electric Kettle 1.5L",    "Home & Kitchen", 3, 650, 1199, 1.2, "short"),
    ("Knife Set 6pc",           "Home & Kitchen", 3, 380, 799, 0.9, ""),
    ("Lunch Box Set",           "Home & Kitchen", 3, 140, 299, 2.8, ""),
    ("Bath Towel Cotton",       "Home & Kitchen", 3, 160, 349, 1.6, ""),
    ("Herbal Shampoo 340ml",    "Personal Care", 1, 150, 275, 3.5, ""),
    ("Face Wash 100ml",         "Personal Care", 1, 85, 160, 4.2, ""),
    ("Toothpaste 200g",         "Personal Care", 1, 70, 110, 6.5, ""),
    ("Sunscreen SPF50",         "Personal Care", 1, 210, 399, 1.4, "dead"),
    ("Yoga Mat 6mm",            "Sports", 4, 320, 699, 1.8, ""),
    ("Dumbbell Set 10kg",       "Sports", 4, 900, 1699, 0.7, ""),
    ("Football Size 5",         "Sports", 4, 280, 549, 1.0, ""),
    ("Skipping Rope",           "Sports", 4, 70, 179, 1.3, ""),
    ("Badminton Racket Pair",   "Sports", 4, 450, 899, 0.9, "dead"),
    ("Building Blocks 500pc",   "Toys", 5, 520, 999, 1.1, ""),
    ("Remote Control Car",      "Toys", 5, 700, 1399, 0.8, "short"),
    ("Jigsaw Puzzle 1000pc",    "Toys", 5, 260, 549, 0.6, ""),
    ("Board Game Family",       "Toys", 5, 400, 799, 0.7, "dead"),
    ("Office Chair Ergonomic",  "Furniture", 3, 3200, 5999, 0.35, ""),
    ("Study Table Compact",     "Furniture", 3, 2400, 4499, 0.3, ""),
    ("Bookshelf 5-tier",        "Furniture", 3, 2100, 3999, 0.25, "dead"),
    ("LED Desk Lamp",           "Furniture", 0, 380, 799, 1.5, ""),
]


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.executemany("INSERT INTO categories(name) VALUES (?)", [(c,) for c in CATEGORIES])
    conn.executemany(
        "INSERT INTO suppliers(name, contact_email, phone, lead_time_days) VALUES (?,?,?,?)",
        SUPPLIERS)
    cat_id = {n: i + 1 for i, n in enumerate(CATEGORIES)}

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=DAYS)

    state = []   # per-product simulation state
    for i, (name, cat, sup, cost, price, demand, flag) in enumerate(PRODUCTS, start=1):
        lead = SUPPLIERS[sup][3]
        reorder_level = max(5, int(demand * (lead + 3)))
        reorder_qty = max(20, int(demand * 30))
        sku = f"SKU-{i:04d}"
        conn.execute(
            """INSERT INTO products(sku,name,category_id,supplier_id,unit_cost,unit_price,
                                    stock_qty,reorder_level,reorder_qty,created_at)
               VALUES (?,?,?,?,?,?,0,?,?,?)""",
            (sku, name, cat_id[cat], sup + 1, cost, price, reorder_level, reorder_qty,
             start.strftime("%Y-%m-%d 09:00:00")))
        state.append(dict(pid=i, cost=cost, price=price, demand=demand, flag=flag,
                          lead=lead, rl=reorder_level, rq=reorder_qty,
                          stock=0, pending=None))
        # opening stock
        opening = reorder_qty * 2 if flag != "dead" else reorder_qty * 3
        conn.execute(
            """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note,created_at)
               VALUES (?,?,?,?,?,?)""",
            (i, "IN", opening, cost, "Opening stock", start.strftime("%Y-%m-%d 09:00:00")))
        state[-1]["stock"] = opening

    for d in range(DAYS):
        day = start + timedelta(days=d + 1)
        days_left = DAYS - d - 1
        weekend = day.weekday() >= 5
        # seasonality: little growth trend + weekend lift
        trend = 1 + 0.15 * (d / DAYS)
        lift = 1.25 if weekend else 1.0

        for s in state:
            # --- arrivals of earlier purchase orders
            if s["pending"] and s["pending"][0] <= d:
                qty = s["pending"][1]
                conn.execute(
                    """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (s["pid"], "IN", qty, s["cost"], "Purchase order received",
                     day.strftime("%Y-%m-%d 10:00:00")))
                s["stock"] += qty
                s["pending"] = None

            # --- sales
            selling = not (s["flag"] == "dead" and days_left < 70)
            if selling:
                mean = s["demand"] * trend * lift
                # simple noisy demand: sum of a few small draws around the mean
                demand = max(0, int(round(random.gauss(mean, mean * 0.45))))
                demand = min(demand, s["stock"])
                if demand > 0:
                    # sales spread across 1-3 transactions per day
                    parts = random.randint(1, min(3, demand))
                    remaining = demand
                    for k in range(parts):
                        q = remaining if k == parts - 1 else random.randint(1, remaining - (parts - k - 1))
                        remaining -= q
                        # keep today's sales in the past (not later than "now")
                        max_hh = min(20, max(10, datetime.now().hour - 1)) if days_left == 0 else 20
                        hh = random.randint(10, max_hh)
                        mm = random.randint(0, 59)
                        # occasional promotional discount
                        unit_price = s["price"] * (0.9 if random.random() < 0.08 else 1.0)
                        conn.execute(
                            """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note,created_at)
                               VALUES (?,?,?,?,?,?)""",
                            (s["pid"], "OUT", q, round(unit_price, 2), "Sale",
                             day.strftime(f"%Y-%m-%d {hh:02d}:{mm:02d}:00")))
                        s["stock"] -= q

            # --- reordering policy (stops for "short" items in last 18 days => shortages)
            can_reorder = not (s["flag"] == "short" and days_left < 18) and s["flag"] != "dead"
            if can_reorder and s["pending"] is None and s["stock"] <= s["rl"]:
                s["pending"] = (d + s["lead"], s["rq"])

    # a few manual adjustments (damaged goods) so ADJUST rows exist
    for pid in (2, 8, 13, 24):
        conn.execute(
            """INSERT INTO stock_movements(product_id,movement_type,quantity,unit_price,note,created_at)
               VALUES (?,?,?,?,?,?)""",
            (pid, "ADJUST", -random.randint(1, 3), 0, "Damaged goods write-off",
             (today - timedelta(days=random.randint(3, 40))).strftime("%Y-%m-%d 17:30:00")))

    # The seeding loop generated alerts stamped with "now"; rebuild a clean set
    conn.execute("DELETE FROM alerts")
    conn.execute(
        """INSERT INTO alerts(product_id, alert_type, message, created_at)
           SELECT product_id,
                  CASE WHEN stock_qty = 0 THEN 'OUT_OF_STOCK' ELSE 'LOW_STOCK' END,
                  name || ' has ' || stock_qty || ' units left (reorder level ' || reorder_level || ')',
                  datetime('now')
             FROM products WHERE stock_qty <= reorder_level""")
    conn.commit()

    n_prod = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    n_mov = conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
    n_alert = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    print(f"Database ready: {DB_PATH}")
    print(f"  products={n_prod}  movements={n_mov}  open alerts={n_alert}")
    conn.close()


if __name__ == "__main__":
    main()
