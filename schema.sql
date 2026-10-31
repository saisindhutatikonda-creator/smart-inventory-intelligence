-- =====================================================================
--  Smart Inventory Intelligence  |  Database schema (SQLite)
--  Concepts used: normalisation (3NF), PK/FK, CHECK constraints,
--  indexes, triggers, views
-- =====================================================================

PRAGMA foreign_keys = ON;

DROP VIEW    IF EXISTS v_product_status;
DROP VIEW    IF EXISTS v_sales_lines;
DROP TRIGGER IF EXISTS trg_block_negative_stock;
DROP TRIGGER IF EXISTS trg_apply_movement;
DROP TRIGGER IF EXISTS trg_low_stock_alert;
DROP TRIGGER IF EXISTS trg_resolve_alert;
DROP TABLE   IF EXISTS alerts;
DROP TABLE   IF EXISTS stock_movements;
DROP TABLE   IF EXISTS products;
DROP TABLE   IF EXISTS suppliers;
DROP TABLE   IF EXISTS categories;

-- ---------- Master tables ---------------------------------------------
CREATE TABLE categories (
    category_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE
);

CREATE TABLE suppliers (
    supplier_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    contact_email TEXT,
    phone        TEXT,
    lead_time_days INTEGER NOT NULL DEFAULT 5 CHECK (lead_time_days >= 0)
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    category_id   INTEGER NOT NULL REFERENCES categories(category_id),
    supplier_id   INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    unit_cost     REAL NOT NULL CHECK (unit_cost  >= 0),
    unit_price    REAL NOT NULL CHECK (unit_price >= 0),
    stock_qty     INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    reorder_qty   INTEGER NOT NULL DEFAULT 50 CHECK (reorder_qty > 0),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Transaction table (every stock change is a row) -----------
--  IN     = purchase / restock         (+qty)
--  OUT    = sale                       (-qty)
--  ADJUST = manual correction          (signed qty)
CREATE TABLE stock_movements (
    movement_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    movement_type TEXT NOT NULL CHECK (movement_type IN ('IN','OUT','ADJUST')),
    quantity      INTEGER NOT NULL CHECK (quantity <> 0),
    unit_price    REAL NOT NULL DEFAULT 0,      -- selling price (OUT) or buying cost (IN)
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ( (movement_type IN ('IN','OUT') AND quantity > 0) OR movement_type = 'ADJUST' )
);

CREATE TABLE alerts (
    alert_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    alert_type  TEXT NOT NULL CHECK (alert_type IN ('LOW_STOCK','OUT_OF_STOCK')),
    message     TEXT NOT NULL,
    is_resolved INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Indexes (performance optimisation) ------------------------
CREATE INDEX idx_mov_product_date ON stock_movements(product_id, created_at);
CREATE INDEX idx_mov_type_date    ON stock_movements(movement_type, created_at);
CREATE INDEX idx_products_cat     ON products(category_id);
CREATE INDEX idx_alerts_open      ON alerts(is_resolved, product_id);

-- ---------- Triggers (business rules inside the database) -------------
-- 1) Refuse a sale / negative adjustment that would make stock < 0
CREATE TRIGGER trg_block_negative_stock
BEFORE INSERT ON stock_movements
WHEN (NEW.movement_type = 'OUT'
      AND NEW.quantity > (SELECT stock_qty FROM products WHERE product_id = NEW.product_id))
  OR (NEW.movement_type = 'ADJUST'
      AND NEW.quantity < 0
      AND -NEW.quantity > (SELECT stock_qty FROM products WHERE product_id = NEW.product_id))
BEGIN
    SELECT RAISE(ABORT, 'Insufficient stock for this movement');
END;

-- 2) Keep products.stock_qty in sync automatically
CREATE TRIGGER trg_apply_movement
AFTER INSERT ON stock_movements
BEGIN
    UPDATE products
       SET stock_qty = stock_qty +
           CASE NEW.movement_type
                WHEN 'IN'     THEN  NEW.quantity
                WHEN 'OUT'    THEN -NEW.quantity
                ELSE                NEW.quantity
           END
     WHERE product_id = NEW.product_id;
END;

-- 3) Raise an alert when stock drops to / below the reorder level
CREATE TRIGGER trg_low_stock_alert
AFTER UPDATE OF stock_qty ON products
WHEN NEW.stock_qty <= NEW.reorder_level
 AND NOT EXISTS (SELECT 1 FROM alerts
                  WHERE product_id = NEW.product_id AND is_resolved = 0)
BEGIN
    INSERT INTO alerts (product_id, alert_type, message, created_at)
    VALUES (NEW.product_id,
            CASE WHEN NEW.stock_qty = 0 THEN 'OUT_OF_STOCK' ELSE 'LOW_STOCK' END,
            NEW.name || ' has ' || NEW.stock_qty || ' units left (reorder level '
                     || NEW.reorder_level || ')',
            datetime('now'));
END;

-- 4) Auto-resolve alerts once stock is replenished above the reorder level
CREATE TRIGGER trg_resolve_alert
AFTER UPDATE OF stock_qty ON products
WHEN NEW.stock_qty > NEW.reorder_level
BEGIN
    UPDATE alerts SET is_resolved = 1
     WHERE product_id = NEW.product_id AND is_resolved = 0;
END;

-- ---------- Views (reusable query building blocks) --------------------
CREATE VIEW v_sales_lines AS
SELECT m.movement_id,
       m.product_id,
       date(m.created_at)                 AS sale_date,
       m.quantity                         AS qty,
       m.quantity * m.unit_price          AS revenue,
       m.quantity * p.unit_cost           AS cogs,
       m.quantity * (m.unit_price - p.unit_cost) AS profit
  FROM stock_movements m
  JOIN products p ON p.product_id = m.product_id
 WHERE m.movement_type = 'OUT';

CREATE VIEW v_product_status AS
SELECT p.product_id, p.sku, p.name,
       c.name AS category, s.name AS supplier, s.lead_time_days,
       p.unit_cost, p.unit_price, p.stock_qty, p.reorder_level, p.reorder_qty,
       p.stock_qty * p.unit_cost AS stock_value,
       CASE WHEN p.stock_qty = 0                THEN 'OUT'
            WHEN p.stock_qty <= p.reorder_level THEN 'LOW'
            ELSE 'OK' END AS status
  FROM products p
  JOIN categories c ON c.category_id = p.category_id
  JOIN suppliers  s ON s.supplier_id = p.supplier_id
 WHERE p.is_active = 1;
