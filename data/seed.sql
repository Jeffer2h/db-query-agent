-- E-commerce demo schema for db-query-agent.
-- All data is fictional. Dates are spread across 2025 so time-based
-- questions (last month, Q3, etc.) produce non-trivial results.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    country     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL  -- ISO-8601 date
);

CREATE TABLE categories (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    price        REAL    NOT NULL,
    stock        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_date   TEXT    NOT NULL,  -- ISO-8601 date
    status       TEXT    NOT NULL CHECK (status IN ('pending','paid','shipped','delivered','cancelled'))
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL    NOT NULL  -- price at the time of order
);

CREATE TABLE payments (
    id        INTEGER PRIMARY KEY,
    order_id  INTEGER NOT NULL REFERENCES orders(id),
    amount    REAL    NOT NULL,
    method    TEXT    NOT NULL CHECK (method IN ('credit_card','debit_card','paypal','bank_transfer')),
    paid_at   TEXT    NOT NULL,
    status    TEXT    NOT NULL CHECK (status IN ('completed','failed','refunded'))
);

-- ----------------------------------------------------------------
-- Categories
-- ----------------------------------------------------------------
INSERT INTO categories (id, name, description) VALUES
 (1, 'electronics', 'Consumer electronics, phones, laptops and accessories'),
 (2, 'books',       'Physical and digital books across all genres'),
 (3, 'clothing',    'Apparel for men, women and kids'),
 (4, 'home',        'Furniture, kitchenware and home decor'),
 (5, 'sports',      'Sports equipment and outdoor gear'),
 (6, 'toys',        'Toys, board games and puzzles');

-- ----------------------------------------------------------------
-- Products  (30 items, 5 per category)
-- ----------------------------------------------------------------
INSERT INTO products (id, name, category_id, price, stock) VALUES
 (1,  'Laptop Pro 14"',           1,  1499.00,  25),
 (2,  'Wireless Headphones',      1,   199.00,  80),
 (3,  'Smartphone X',              1,   899.00,  40),
 (4,  'USB-C Hub',                 1,    49.00, 120),
 (5,  '4K Monitor 27"',            1,   429.00,  15),
 (6,  'The Pragmatic Programmer', 2,    39.00, 200),
 (7,  'Clean Code',                2,    35.00, 180),
 (8,  'Designing Data-Intensive Apps', 2, 49.00, 90),
 (9,  'Atomic Habits',             2,    19.00, 300),
 (10, 'Sapiens',                   2,    22.00, 150),
 (11, 'Cotton T-Shirt',            3,    19.00, 400),
 (12, 'Denim Jeans',               3,    59.00, 220),
 (13, 'Running Sneakers',          3,    89.00, 130),
 (14, 'Wool Sweater',              3,    79.00,  70),
 (15, 'Rain Jacket',               3,   119.00,  50),
 (16, 'Espresso Machine',          4,   349.00,  20),
 (17, 'Cookware Set 10pc',         4,   199.00,  35),
 (18, 'Memory Foam Pillow',        4,    49.00, 160),
 (19, 'Floor Lamp',                4,    89.00,  40),
 (20, 'Dining Table',              4,   599.00,   8),
 (21, 'Yoga Mat',                  5,    35.00, 200),
 (22, 'Mountain Bike',             5,   799.00,  12),
 (23, 'Tennis Racket',             5,   129.00,  45),
 (24, 'Dumbbell Set 20kg',         5,    99.00,  30),
 (25, 'Camping Tent 4-person',     5,   249.00,  18),
 (26, 'LEGO City Set',             6,    79.00,  60),
 (27, 'Wooden Puzzle 1000pc',      6,    24.00, 110),
 (28, 'Board Game: Catan',         6,    49.00,  55),
 (29, 'RC Car',                    6,    69.00,  40),
 (30, 'Plush Bear',                6,    19.00, 250);

-- ----------------------------------------------------------------
-- Customers  (12 customers, varied countries)
-- ----------------------------------------------------------------
INSERT INTO customers (id, name, email, country, created_at) VALUES
 (1,  'Ana López',         'ana.lopez@example.com',     'Colombia',     '2024-08-12'),
 (2,  'Carlos Ruiz',       'carlos.ruiz@example.com',   'Mexico',       '2024-09-03'),
 (3,  'Mariana Silva',     'mariana.silva@example.com', 'Brazil',       '2024-10-21'),
 (4,  'John Smith',        'john.smith@example.com',    'USA',          '2024-11-15'),
 (5,  'Emily Johnson',     'emily.j@example.com',       'USA',          '2024-12-02'),
 (6,  'Lucas Müller',      'lucas.muller@example.com',  'Germany',      '2025-01-08'),
 (7,  'Sophie Dubois',     'sophie.d@example.com',      'France',       '2025-01-19'),
 (8,  'Diego Fernández',   'diego.f@example.com',       'Argentina',    '2025-02-14'),
 (9,  'Yuki Tanaka',       'yuki.tanaka@example.com',   'Japan',        '2025-03-07'),
 (10, 'Olivia Brown',      'olivia.brown@example.com',  'UK',           '2025-04-22'),
 (11, 'Pablo García',      'pablo.garcia@example.com',  'Spain',        '2025-06-11'),
 (12, 'Isabella Rossi',    'isabella.r@example.com',    'Italy',        '2025-09-30');

-- ----------------------------------------------------------------
-- Orders  (60 orders spread across 2025; mixed statuses)
-- ----------------------------------------------------------------
INSERT INTO orders (id, customer_id, order_date, status) VALUES
 (1,  1,  '2025-01-05', 'delivered'),
 (2,  4,  '2025-01-09', 'delivered'),
 (3,  2,  '2025-01-14', 'delivered'),
 (4,  6,  '2025-01-22', 'delivered'),
 (5,  3,  '2025-01-28', 'cancelled'),
 (6,  5,  '2025-02-02', 'delivered'),
 (7,  7,  '2025-02-09', 'delivered'),
 (8,  1,  '2025-02-15', 'delivered'),
 (9,  8,  '2025-02-20', 'delivered'),
 (10, 4,  '2025-02-27', 'delivered'),
 (11, 9,  '2025-03-04', 'delivered'),
 (12, 2,  '2025-03-08', 'delivered'),
 (13, 5,  '2025-03-14', 'delivered'),
 (14, 6,  '2025-03-19', 'cancelled'),
 (15, 10, '2025-03-25', 'delivered'),
 (16, 3,  '2025-03-30', 'delivered'),
 (17, 1,  '2025-04-04', 'delivered'),
 (18, 7,  '2025-04-09', 'delivered'),
 (19, 4,  '2025-04-15', 'delivered'),
 (20, 8,  '2025-04-21', 'delivered'),
 (21, 11, '2025-04-26', 'delivered'),
 (22, 2,  '2025-05-02', 'delivered'),
 (23, 5,  '2025-05-07', 'delivered'),
 (24, 9,  '2025-05-12', 'delivered'),
 (25, 6,  '2025-05-18', 'delivered'),
 (26, 1,  '2025-05-24', 'delivered'),
 (27, 10, '2025-05-29', 'delivered'),
 (28, 3,  '2025-06-03', 'delivered'),
 (29, 7,  '2025-06-08', 'delivered'),
 (30, 4,  '2025-06-14', 'delivered'),
 (31, 8,  '2025-06-19', 'delivered'),
 (32, 11, '2025-06-25', 'delivered'),
 (33, 2,  '2025-07-01', 'delivered'),
 (34, 5,  '2025-07-06', 'cancelled'),
 (35, 9,  '2025-07-12', 'delivered'),
 (36, 1,  '2025-07-18', 'delivered'),
 (37, 6,  '2025-07-23', 'delivered'),
 (38, 10, '2025-07-29', 'delivered'),
 (39, 3,  '2025-08-04', 'delivered'),
 (40, 7,  '2025-08-09', 'delivered'),
 (41, 4,  '2025-08-15', 'delivered'),
 (42, 8,  '2025-08-21', 'delivered'),
 (43, 11, '2025-08-27', 'delivered'),
 (44, 2,  '2025-09-02', 'delivered'),
 (45, 5,  '2025-09-08', 'delivered'),
 (46, 9,  '2025-09-13', 'delivered'),
 (47, 1,  '2025-09-19', 'delivered'),
 (48, 6,  '2025-09-25', 'delivered'),
 (49, 10, '2025-10-01', 'delivered'),
 (50, 3,  '2025-10-07', 'delivered'),
 (51, 12, '2025-10-12', 'delivered'),
 (52, 7,  '2025-10-18', 'delivered'),
 (53, 4,  '2025-10-24', 'shipped'),
 (54, 8,  '2025-10-30', 'shipped'),
 (55, 11, '2025-11-05', 'shipped'),
 (56, 2,  '2025-11-11', 'paid'),
 (57, 5,  '2025-11-17', 'paid'),
 (58, 12, '2025-11-23', 'paid'),
 (59, 9,  '2025-11-29', 'pending'),
 (60, 1,  '2025-12-04', 'pending');

-- ----------------------------------------------------------------
-- Order items (1-4 per order; unit_price snapshots product price)
-- ----------------------------------------------------------------
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
 (1,  1,  1, 1499.00),
 (1,  4,  2,   49.00),
 (2,  6,  1,   39.00),
 (2,  9,  2,   19.00),
 (2,  10, 1,   22.00),
 (3,  11, 3,   19.00),
 (3,  12, 1,   59.00),
 (4,  16, 1,  349.00),
 (4,  18, 2,   49.00),
 (5,  22, 1,  799.00),
 (6,  3,  1,  899.00),
 (6,  2,  1,  199.00),
 (7,  26, 2,   79.00),
 (7,  28, 1,   49.00),
 (8,  5,  1,  429.00),
 (9,  13, 1,   89.00),
 (9,  21, 1,   35.00),
 (10, 8,  1,   49.00),
 (10, 7,  1,   35.00),
 (11, 17, 1,  199.00),
 (11, 19, 1,   89.00),
 (12, 14, 2,   79.00),
 (12, 15, 1,  119.00),
 (13, 23, 1,  129.00),
 (13, 24, 1,   99.00),
 (14, 1,  1, 1499.00),
 (15, 27, 2,   24.00),
 (15, 30, 3,   19.00),
 (16, 6,  1,   39.00),
 (16, 8,  1,   49.00),
 (16, 9,  1,   19.00),
 (17, 2,  2,  199.00),
 (18, 25, 1,  249.00),
 (19, 11, 5,   19.00),
 (19, 12, 2,   59.00),
 (20, 16, 1,  349.00),
 (21, 20, 1,  599.00),
 (22, 4,  3,   49.00),
 (23, 21, 2,   35.00),
 (23, 24, 1,   99.00),
 (24, 26, 1,   79.00),
 (24, 29, 1,   69.00),
 (25, 3,  1,  899.00),
 (26, 7,  2,   35.00),
 (27, 13, 1,   89.00),
 (28, 17, 1,  199.00),
 (29, 22, 1,  799.00),
 (30, 5,  1,  429.00),
 (30, 4,  1,   49.00),
 (31, 14, 1,   79.00),
 (32, 28, 2,   49.00),
 (33, 9,  3,   19.00),
 (34, 20, 1,  599.00),
 (35, 18, 2,   49.00),
 (36, 1,  1, 1499.00),
 (37, 23, 1,  129.00),
 (37, 21, 1,   35.00),
 (38, 11, 4,   19.00),
 (39, 6,  1,   39.00),
 (39, 10, 2,   22.00),
 (40, 25, 1,  249.00),
 (41, 2,  1,  199.00),
 (42, 27, 3,   24.00),
 (43, 16, 1,  349.00),
 (44, 12, 1,   59.00),
 (44, 13, 1,   89.00),
 (45, 8,  2,   49.00),
 (46, 30, 4,   19.00),
 (47, 19, 1,   89.00),
 (48, 22, 1,  799.00),
 (49, 7,  1,   35.00),
 (50, 5,  1,  429.00),
 (51, 26, 1,   79.00),
 (51, 28, 1,   49.00),
 (52, 15, 1,  119.00),
 (53, 3,  1,  899.00),
 (54, 17, 1,  199.00),
 (55, 24, 1,   99.00),
 (56, 4,  2,   49.00),
 (56, 9,  3,   19.00),
 (57, 14, 1,   79.00),
 (58, 29, 2,   69.00),
 (59, 1,  1, 1499.00),
 (60, 11, 2,   19.00),
 (60, 21, 1,   35.00);

-- ----------------------------------------------------------------
-- Payments  (1 per non-pending order; cancelled = refunded)
-- ----------------------------------------------------------------
INSERT INTO payments (order_id, amount, method, paid_at, status) VALUES
 (1,  1597.00, 'credit_card',   '2025-01-05', 'completed'),
 (2,    99.00, 'paypal',        '2025-01-09', 'completed'),
 (3,   116.00, 'debit_card',    '2025-01-14', 'completed'),
 (4,   447.00, 'credit_card',   '2025-01-22', 'completed'),
 (5,   799.00, 'credit_card',   '2025-01-28', 'refunded'),
 (6,  1098.00, 'credit_card',   '2025-02-02', 'completed'),
 (7,   207.00, 'paypal',        '2025-02-09', 'completed'),
 (8,   429.00, 'debit_card',    '2025-02-15', 'completed'),
 (9,   124.00, 'credit_card',   '2025-02-20', 'completed'),
 (10,   84.00, 'paypal',        '2025-02-27', 'completed'),
 (11,  288.00, 'credit_card',   '2025-03-04', 'completed'),
 (12,  277.00, 'bank_transfer', '2025-03-08', 'completed'),
 (13,  228.00, 'credit_card',   '2025-03-14', 'completed'),
 (14, 1499.00, 'credit_card',   '2025-03-19', 'refunded'),
 (15,  105.00, 'paypal',        '2025-03-25', 'completed'),
 (16,  107.00, 'debit_card',    '2025-03-30', 'completed'),
 (17,  398.00, 'credit_card',   '2025-04-04', 'completed'),
 (18,  249.00, 'paypal',        '2025-04-09', 'completed'),
 (19,  213.00, 'credit_card',   '2025-04-15', 'completed'),
 (20,  349.00, 'bank_transfer', '2025-04-21', 'completed'),
 (21,  599.00, 'credit_card',   '2025-04-26', 'completed'),
 (22,  147.00, 'paypal',        '2025-05-02', 'completed'),
 (23,  169.00, 'credit_card',   '2025-05-07', 'completed'),
 (24,  148.00, 'debit_card',    '2025-05-12', 'completed'),
 (25,  899.00, 'credit_card',   '2025-05-18', 'completed'),
 (26,   70.00, 'paypal',        '2025-05-24', 'completed'),
 (27,   89.00, 'credit_card',   '2025-05-29', 'completed'),
 (28,  199.00, 'bank_transfer', '2025-06-03', 'completed'),
 (29,  799.00, 'credit_card',   '2025-06-08', 'completed'),
 (30,  478.00, 'credit_card',   '2025-06-14', 'completed'),
 (31,   79.00, 'debit_card',    '2025-06-19', 'completed'),
 (32,   98.00, 'paypal',        '2025-06-25', 'completed'),
 (33,   57.00, 'credit_card',   '2025-07-01', 'completed'),
 (34,  599.00, 'credit_card',   '2025-07-06', 'refunded'),
 (35,   98.00, 'paypal',        '2025-07-12', 'completed'),
 (36, 1499.00, 'credit_card',   '2025-07-18', 'completed'),
 (37,  164.00, 'debit_card',    '2025-07-23', 'completed'),
 (38,   76.00, 'paypal',        '2025-07-29', 'completed'),
 (39,   83.00, 'credit_card',   '2025-08-04', 'completed'),
 (40,  249.00, 'bank_transfer', '2025-08-09', 'completed'),
 (41,  199.00, 'credit_card',   '2025-08-15', 'completed'),
 (42,   72.00, 'paypal',        '2025-08-21', 'completed'),
 (43,  349.00, 'credit_card',   '2025-08-27', 'completed'),
 (44,  148.00, 'debit_card',    '2025-09-02', 'completed'),
 (45,   98.00, 'paypal',        '2025-09-08', 'completed'),
 (46,   76.00, 'credit_card',   '2025-09-13', 'completed'),
 (47,   89.00, 'credit_card',   '2025-09-19', 'completed'),
 (48,  799.00, 'bank_transfer', '2025-09-25', 'completed'),
 (49,   35.00, 'paypal',        '2025-10-01', 'completed'),
 (50,  429.00, 'credit_card',   '2025-10-07', 'completed'),
 (51,  128.00, 'debit_card',    '2025-10-12', 'completed'),
 (52,  119.00, 'credit_card',   '2025-10-18', 'completed'),
 (53,  899.00, 'credit_card',   '2025-10-24', 'completed'),
 (54,  199.00, 'paypal',        '2025-10-30', 'completed'),
 (55,   99.00, 'credit_card',   '2025-11-05', 'completed'),
 (56,  155.00, 'debit_card',    '2025-11-11', 'completed'),
 (57,   79.00, 'credit_card',   '2025-11-17', 'completed'),
 (58,  138.00, 'paypal',        '2025-11-23', 'completed');
-- Orders 59 and 60 are still 'pending' → no payment row yet.
