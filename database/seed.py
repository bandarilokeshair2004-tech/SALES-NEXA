from datetime import date, timedelta
from werkzeug.security import generate_password_hash
from app import create_app
from db import get_db, init_db, insert_id


def seed():
    app = create_app()
    with app.app_context():
        init_db()
        db = get_db()
        roles = ["SUPER ADMIN", "ADMIN", "MANAGER", "STAFF", "VIEWER"]
        for role in roles:
            db.execute("INSERT OR IGNORE INTO roles(name) VALUES (?)", (role,))
        accounts = [("Demo Admin", "admin@salesnexa.local", "ADMIN"), ("Demo Manager", "manager@salesnexa.local", "MANAGER"), ("Demo Staff", "staff@salesnexa.local", "STAFF"), ("Demo Viewer", "viewer@salesnexa.local", "VIEWER")]
        for name, email, role in accounts:
            role_id = db.execute("SELECT id FROM roles WHERE name = ?", (role,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role_id) VALUES(?,?,?,?)", (name, email, generate_password_hash("DemoPass123!"), role_id))
        categories = ["Electronics", "Office", "Accessories", "Home", "Software", "Services", "Mobile", "Audio", "Networking", "Security", "Wellness"]
        for name in categories:
            db.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
        for index in range(30):
            category_id = (index % len(categories)) + 1
            name = ["Wireless Headphones", "Smart Laptop", "USB Hub", "Ergonomic Chair", "Cloud Suite"][index % 5] + f" {index + 1}"
            db.execute("INSERT OR IGNORE INTO products(name,sku,category_id,description,selling_price,cost_price,reorder_level) VALUES(?,?,?,?,?,?,?)", (name, f"SNX-{index+1:04d}", category_id, "Demo catalog item", 120 + index * 17, 70 + index * 10, 8 + index % 8))
        for index in range(20):
            db.execute("INSERT OR IGNORE INTO customers(name,email,phone,location) VALUES(?,?,?,?)", (f"Demo Customer {index+1}", f"customer{index+1}@demo.local", f"90000000{index:02d}", ["Hyderabad", "Bengaluru", "Chennai", "Delhi"][index % 4]))
        for index in range(5):
            db.execute("INSERT OR IGNORE INTO suppliers(name,contact_person,email,phone,address) VALUES(?,?,?,?,?)", (f"Demo Supplier {index+1}", f"Contact {index+1}", f"supplier{index+1}@demo.local", "9111111111", "Demo address"))
        for product_id in range(1, 31):
            quantity = 4 if product_id % 7 == 0 else 45 + product_id
            db.execute("INSERT OR IGNORE INTO inventory(product_id,quantity) VALUES(?,?)", (product_id, quantity))
        existing_sales = db.execute("SELECT COUNT(*) count FROM sales").fetchone()["count"]
        admin_id = db.execute("SELECT id FROM users WHERE email = 'admin@salesnexa.local'").fetchone()[0]
        today_sale = db.execute("SELECT id FROM sales WHERE date(sale_date)=date('now') LIMIT 1").fetchone()
        if today_sale:
            db.commit()
            print("SalesNexa demo database already initialized")
            return
        if existing_sales:
            product_id = 1
            product = db.execute("SELECT selling_price,cost_price FROM products WHERE id=?", (product_id,)).fetchone()
            total = product[0] * 2
            sale_id = insert_id(db, "INSERT INTO sales(customer_id,user_id,subtotal,total,sale_date) VALUES(?,?,?,?,date('now'))", (1, admin_id, total, total))
            db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,cost_price) VALUES(?,?,?,?,?)", (sale_id, product_id, 2, product[0], product[1]))
            db.commit()
            print("SalesNexa demo database refreshed with today's demo sale")
            return
        for month_offset in range(6):
            for day in (5, 12, 20, 26):
                sale_day = date.today() - timedelta(days=month_offset * 30 + (30 - day))
                product_id = (month_offset * 4 + day) % 30 + 1
                quantity = 2 + (day % 4)
                product = db.execute("SELECT selling_price,cost_price FROM products WHERE id=?", (product_id,)).fetchone()
                total = product[0] * quantity
                sale_id = insert_id(db, "INSERT INTO sales(customer_id,user_id,subtotal,total,sale_date) VALUES(?,?,?,?,?)", ((day % 20) + 1, admin_id, total, total, sale_day.isoformat()))
                db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,cost_price) VALUES(?,?,?,?,?)", (sale_id, product_id, quantity, product[0], product[1]))
        product = db.execute("SELECT selling_price,cost_price FROM products WHERE id=1").fetchone()
        total = product[0] * 2
        sale_id = insert_id(db, "INSERT INTO sales(customer_id,user_id,subtotal,total,sale_date) VALUES(?,?,?,?,date('now'))", (1, admin_id, total, total))
        db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,cost_price) VALUES(?,?,?,?,?)", (sale_id, 1, 2, product[0], product[1]))
        db.execute("INSERT INTO sales_targets(period,target) VALUES('monthly', 100000) ON CONFLICT(period) DO UPDATE SET target=excluded.target")
        db.commit()
        print("SalesNexa demo database initialized")


if __name__ == "__main__":
    seed()
