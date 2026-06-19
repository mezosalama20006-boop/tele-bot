import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_path="store.db"):
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()

        # Users
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            balance REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Categories (e.g. متابعين, لايكات, مشاهدات)
        c.execute('''CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📁',
            position INTEGER DEFAULT 0
        )''')

        # Apps inside categories (e.g. Instagram, Facebook, TikTok)
        c.execute('''CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📱',
            position INTEGER DEFAULT 0,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        )''')

        # Products — now linked to app (and indirectly to category)
        c.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            requires_input INTEGER DEFAULT 0,
            input_prompt TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (app_id) REFERENCES apps(id)
        )''')

        # Items (the actual deliverable content)
        c.execute('''CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_sold INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )''')

        # Orders
        c.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            price REAL NOT NULL,
            user_input TEXT,
            date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )''')

        # Deposits
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            photo_file_id TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            approved_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Transactions
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            date TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Migrate existing DB schema if needed
        existing_products_columns = [row['name'] for row in c.execute("PRAGMA table_info(products)").fetchall()]
        if 'requires_input' not in existing_products_columns:
            c.execute("ALTER TABLE products ADD COLUMN requires_input INTEGER DEFAULT 0")
        if 'input_prompt' not in existing_products_columns:
            c.execute("ALTER TABLE products ADD COLUMN input_prompt TEXT DEFAULT ''")
        if 'infinite_stock' not in existing_products_columns:
            c.execute("ALTER TABLE products ADD COLUMN infinite_stock INTEGER DEFAULT 0")

        existing_orders_columns = [row['name'] for row in c.execute("PRAGMA table_info(orders)").fetchall()]
        if 'user_input' not in existing_orders_columns:
            c.execute("ALTER TABLE orders ADD COLUMN user_input TEXT")
        if 'status' not in existing_orders_columns:
            c.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'pending'")
        # ensure purchases table exists for grouping orders into one purchase
        c.execute('''CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total_price REAL NOT NULL,
            user_input TEXT,
            status TEXT DEFAULT 'pending',
            date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )''')
        # add purchase_id to orders if missing
        if 'purchase_id' not in existing_orders_columns:
            c.execute("ALTER TABLE orders ADD COLUMN purchase_id INTEGER")

        conn.commit()
        conn.close()

    # ── USERS ──────────────────────────────────────────────

    def add_user(self, user_id, username, name):
        conn = self.get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, name) VALUES (?,?,?)",
            (user_id, username, name)
        )
        conn.commit()
        conn.close()

    def get_balance(self, user_id):
        conn = self.get_conn()
        row = conn.execute("SELECT balance FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        return row['balance'] if row else 0

    def get_all_users(self):
        conn = self.get_conn()
        rows = conn.execute("SELECT * FROM users ORDER BY balance DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_user(self, user_id):
        conn = self.get_conn()
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_user_balance(self, user_id, balance):
        conn = self.get_conn()
        conn.execute("UPDATE users SET balance=? WHERE id=?", (balance, user_id))
        conn.commit()
        conn.close()

    def delete_user(self, user_id):
        conn = self.get_conn()
        conn.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM deposits WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM orders WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM purchases WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        conn.close()

    def get_transactions(self, user_id, limit=10):
        conn = self.get_conn()
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── CATEGORIES ─────────────────────────────────────────

    def add_category(self, name, emoji="📁"):
        conn = self.get_conn()
        c = conn.cursor()
        pos = (c.execute("SELECT COUNT(*) FROM categories").fetchone()[0])
        c.execute("INSERT INTO categories (name, emoji, position) VALUES (?,?,?)", (name, emoji, pos))
        cat_id = c.lastrowid
        conn.commit()
        conn.close()
        return cat_id

    def get_all_categories(self):
        conn = self.get_conn()
        rows = conn.execute("SELECT * FROM categories ORDER BY position").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_category(self, cat_id):
        conn = self.get_conn()
        row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_category(self, cat_id):
        conn = self.get_conn()
        # cascade: delete apps → products → items
        app_ids = [r[0] for r in conn.execute("SELECT id FROM apps WHERE category_id=?", (cat_id,)).fetchall()]
        for app_id in app_ids:
            prod_ids = [r[0] for r in conn.execute("SELECT id FROM products WHERE app_id=?", (app_id,)).fetchall()]
            for pid in prod_ids:
                conn.execute("DELETE FROM items WHERE product_id=?", (pid,))
            conn.execute("DELETE FROM products WHERE app_id=?", (app_id,))
        conn.execute("DELETE FROM apps WHERE category_id=?", (cat_id,))
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        conn.commit()
        conn.close()

    # ── APPS ───────────────────────────────────────────────

    def add_app(self, category_id, name, emoji="📱"):
        conn = self.get_conn()
        c = conn.cursor()
        pos = (c.execute("SELECT COUNT(*) FROM apps WHERE category_id=?", (category_id,)).fetchone()[0])
        c.execute("INSERT INTO apps (category_id, name, emoji, position) VALUES (?,?,?,?)", (category_id, name, emoji, pos))
        app_id = c.lastrowid
        conn.commit()
        conn.close()
        return app_id

    def get_apps_by_category(self, category_id):
        conn = self.get_conn()
        rows = conn.execute(
            "SELECT * FROM apps WHERE category_id=? ORDER BY position", (category_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_app(self, app_id):
        conn = self.get_conn()
        row = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_app(self, app_id):
        conn = self.get_conn()
        prod_ids = [r[0] for r in conn.execute("SELECT id FROM products WHERE app_id=?", (app_id,)).fetchall()]
        for pid in prod_ids:
            conn.execute("DELETE FROM items WHERE product_id=?", (pid,))
        conn.execute("DELETE FROM products WHERE app_id=?", (app_id,))
        conn.execute("DELETE FROM apps WHERE id=?", (app_id,))
        conn.commit()
        conn.close()

    # ── PRODUCTS ───────────────────────────────────────────

    def add_product(self, name, description, price, app_id=None, requires_input=0, input_prompt="", infinite_stock=0):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO products (name, description, price, app_id, requires_input, input_prompt, infinite_stock) VALUES (?,?,?,?,?,?,?)",
            (name, description, price, app_id, requires_input, input_prompt, infinite_stock)
        )
        pid = c.lastrowid
        conn.commit()
        conn.close()
        return pid

    def get_all_products(self):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT p.*, COALESCE(COUNT(i.id),0) as stock
            FROM products p
            LEFT JOIN items i ON i.product_id = p.id AND i.is_sold=0
            GROUP BY p.id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_products_by_app(self, app_id):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT p.*, 
                CASE WHEN p.infinite_stock=1 OR p.requires_input=1 THEN -1 ELSE COALESCE(COUNT(i.id),0) END as stock
            FROM products p
            LEFT JOIN items i ON i.product_id = p.id AND i.is_sold=0
            WHERE p.app_id=?
            GROUP BY p.id
        """, (app_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_product(self, product_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT p.*, 
                CASE WHEN p.infinite_stock=1 OR p.requires_input=1 THEN -1 ELSE COALESCE(COUNT(i.id),0) END as stock
            FROM products p
            LEFT JOIN items i ON i.product_id = p.id AND i.is_sold=0
            WHERE p.id=?
            GROUP BY p.id
        """, (product_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_product(self, product_id):
        conn = self.get_conn()
        conn.execute("DELETE FROM items WHERE product_id=?", (product_id,))
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
        conn.close()


    # ── ITEMS ──────────────────────────────────────────────

    def add_item_to_product(self, product_id, content):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO items (product_id, content) VALUES (?,?)", (product_id, content))
        item_id = c.lastrowid
        conn.commit()
        conn.close()
        return item_id

    def get_product_items(self, product_id):
        conn = self.get_conn()
        rows = conn.execute(
            "SELECT * FROM items WHERE product_id=? AND is_sold=0", (product_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_item(self, item_id):
        conn = self.get_conn()
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
        conn.close()

    # ── PURCHASE ───────────────────────────────────────────

    def purchase_product(self, user_id, product_id, quantity=1, user_input=None):
        if quantity <= 0:
            return False, "Invalid quantity"

        conn = self.get_conn()
        try:
            product = conn.execute("""
                SELECT p.*, 
                    CASE WHEN p.infinite_stock=1 OR p.requires_input=1 THEN -1 ELSE COALESCE(COUNT(i.id),0) END as stock
                FROM products p
                LEFT JOIN items i ON i.product_id=p.id AND i.is_sold=0
                WHERE p.id=?
                GROUP BY p.id
            """, (product_id,)).fetchone()

            if not product:
                return False, "Product not found"
            if product['stock'] >= 0 and product['stock'] < quantity:
                return False, "Not enough stock"

            balance_row = conn.execute("SELECT balance FROM users WHERE id=?", (user_id,)).fetchone()
            balance = balance_row['balance'] if balance_row else 0
            total_price = product['price'] * quantity

            if balance < total_price:
                return False, "Insufficient balance"

            items = []
            if product['stock'] >= 0:
                items = conn.execute(
                    "SELECT * FROM items WHERE product_id=? AND is_sold=0 LIMIT ?", (product_id, quantity)
                ).fetchall()
                if len(items) < quantity:
                    return False, "Not enough stock"
            else:
                c = conn.cursor()
                for _ in range(quantity):
                    placeholder = "أرسل الرابط" if product['requires_input'] == 1 else "(خدمة بدون مخزون)"
                    c.execute(
                        "INSERT INTO items (product_id, content, is_sold) VALUES (?,?,1)",
                        (product_id, placeholder,)
                    )
                    item_id = c.lastrowid
                    items.append({'id': item_id, 'content': placeholder})

            c = conn.cursor()
            c.execute(
                "INSERT INTO purchases (user_id, product_id, quantity, total_price, user_input) VALUES (?,?,?,?,?)",
                (user_id, product_id, quantity, total_price, user_input)
            )
            purchase_id = c.lastrowid

            if product['stock'] >= 0:
                item_ids = [item['id'] for item in items]
                conn.execute(
                    f"UPDATE items SET is_sold=1 WHERE id IN ({','.join(['?']*len(item_ids))})",
                    item_ids
                )
            conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (total_price, user_id))
            for item in items:
                conn.execute(
                    "INSERT INTO orders (user_id, product_id, item_id, price, user_input, purchase_id) VALUES (?,?,?,?,?,?)",
                    (user_id, product_id, item['id'], product['price'], user_input, purchase_id)
                )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
                (user_id, -total_price, 'purchase', f"Bought {quantity}x {product['name']}")
            )
            conn.commit()
            new_balance = balance - total_price
            contents = "\n\n".join(item['content'] for item in items)
            return True, {
                'purchase_id': purchase_id,
                'product_name': product['name'],
                'content': contents,
                'new_balance': new_balance,
                'quantity': quantity,
                'total_price': total_price
            }
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ── ORDERS ─────────────────────────────────────────────

    def get_user_orders(self, user_id):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT o.*, p.name as product_name, i.content
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN items i ON o.item_id = i.id
            WHERE o.user_id=?
            ORDER BY o.date DESC
        """, (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_order_user_input(self, order_id, user_input):
        conn = self.get_conn()
        conn.execute("UPDATE orders SET user_input=? WHERE id=?", (user_input, order_id))
        conn.commit()
        conn.close()

    def set_purchase_user_input(self, purchase_id, user_input):
        conn = self.get_conn()
        conn.execute("UPDATE purchases SET user_input=? WHERE id=?", (user_input, purchase_id))
        conn.execute("UPDATE orders SET user_input=? WHERE purchase_id=?", (user_input, purchase_id))
        conn.commit()
        conn.close()

    def get_purchases(self, limit=100, offset=0):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT p.*, u.username, u.name as user_name, prod.name as product_name, 
                   app.name as app_name, cat.name as category_name
            FROM purchases p
            JOIN users u ON p.user_id = u.id
            JOIN products prod ON p.product_id = prod.id
            JOIN apps app ON prod.app_id = app.id
            JOIN categories cat ON app.category_id = cat.id
            ORDER BY p.date DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_purchase(self, purchase_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT p.*, u.username, u.name as user_name, prod.name as product_name,
                   app.name as app_name, cat.name as category_name
            FROM purchases p
            JOIN users u ON p.user_id = u.id
            JOIN products prod ON p.product_id = prod.id
            JOIN apps app ON prod.app_id = app.id
            JOIN categories cat ON app.category_id = cat.id
            WHERE p.id=?
        """, (purchase_id,)).fetchone()
        if not row:
            conn.close()
            return None
        # fetch linked items
        items = conn.execute("SELECT i.* FROM orders o JOIN items i ON o.item_id = i.id WHERE o.purchase_id=?", (purchase_id,)).fetchall()
        conn.close()
        result = dict(row)
        result['items'] = [dict(i) for i in items]
        return result

    def set_purchase_status(self, purchase_id, status):
        conn = self.get_conn()
        conn.execute("UPDATE purchases SET status=? WHERE id=?", (status, purchase_id))
        conn.commit()
        conn.close()

    def refund_purchase(self, purchase_id):
        conn = self.get_conn()
        try:
            purchase = conn.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,)).fetchone()
            if not purchase:
                conn.close()
                return False, "Purchase not found"
            user_id = purchase['user_id']
            total_price = purchase['total_price']
            # return items to stock
            item_rows = conn.execute("SELECT item_id FROM orders WHERE purchase_id=?", (purchase_id,)).fetchall()
            item_ids = [r['item_id'] for r in item_rows]
            if item_ids:
                conn.execute(f"UPDATE items SET is_sold=0 WHERE id IN ({','.join(['?']*len(item_ids))})", item_ids)
            # refund money
            conn.execute("UPDATE users SET balance = balance + ? WHERE id=?", (total_price, user_id))
            conn.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
                         (user_id, total_price, 'refund', f"Refund purchase #{purchase_id}"))
            conn.execute("UPDATE purchases SET status='rejected' WHERE id=?", (purchase_id,))
            conn.commit()
            conn.close()
            return True, None
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, str(e)

    def set_orders_status_by_purchase(self, purchase_id, status):
        conn = self.get_conn()
        conn.execute("UPDATE orders SET status=? WHERE purchase_id=?", (status, purchase_id))
        conn.commit()
        conn.close()

    def get_all_orders(self, limit=100, offset=0):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT o.*, p.name as product_name, i.content, u.username, u.name as user_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN items i ON o.item_id = i.id
            JOIN users u ON o.user_id = u.id
            ORDER BY o.date DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_order(self, order_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT o.*, p.name as product_name, i.content, u.username, u.name as user_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN items i ON o.item_id = i.id
            JOIN users u ON o.user_id = u.id
            WHERE o.id=?
        """, (order_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_order_status(self, order_id, status):
        conn = self.get_conn()
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        conn.commit()
        conn.close()

    # ── DEPOSITS ───────────────────────────────────────────

    def create_deposit_request(self, user_id, photo_file_id, amount):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO deposits (user_id, photo_file_id, amount) VALUES (?,?,?)",
            (user_id, photo_file_id, amount)
        )
        dep_id = c.lastrowid
        conn.commit()
        conn.close()
        return dep_id

    def get_pending_deposits(self):
        conn = self.get_conn()
        rows = conn.execute("""
            SELECT d.*, u.username, u.name
            FROM deposits d JOIN users u ON d.user_id=u.id
            WHERE d.status='pending'
            ORDER BY d.created_at
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_deposit(self, deposit_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT d.*, u.username, u.name
            FROM deposits d JOIN users u ON d.user_id=u.id
            WHERE d.id=?
        """, (deposit_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def approve_deposit(self, deposit_id, amount, admin_id):
        conn = self.get_conn()
        dep = conn.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
        if not dep:
            conn.close()
            return
        conn.execute(
            "UPDATE deposits SET status='approved', approved_by=? WHERE id=?",
            (admin_id, deposit_id)
        )
        conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, dep['user_id']))
        conn.execute(
            "INSERT INTO transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
            (dep['user_id'], amount, 'deposit', f"Deposit approved #{deposit_id}")
        )
        conn.commit()
        conn.close()

    def reject_deposit(self, deposit_id, admin_id):
        conn = self.get_conn()
        conn.execute(
            "UPDATE deposits SET status='rejected', approved_by=? WHERE id=?",
            (admin_id, deposit_id)
        )
        conn.commit()
        conn.close()

    # ── STATS ──────────────────────────────────────────────

    def get_stats(self):
        conn = self.get_conn()
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        apps = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
        total_items = conn.execute("SELECT COUNT(*) FROM items WHERE is_sold=0").fetchone()[0]
        orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        revenue = conn.execute("SELECT COALESCE(SUM(price),0) FROM orders").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
        conn.close()
        return {
            'users': users,
            'products': products,
            'categories': categories,
            'apps': apps,
            'total_items': total_items,
            'orders': orders,
            'revenue': revenue,
            'pending_deposits': pending
        }
