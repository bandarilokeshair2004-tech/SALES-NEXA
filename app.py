import sqlite3
import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from config import Config
from db import close_db, get_db, init_db, query
from services.forecast_service import revenue_forecast
from services.anomaly_service import sales_anomalies
from chatbot import tools
from chatbot.engine import answer_question
from services.ai_service import answer_with_ai
from services.translation_service import language_name, language_options, load_language


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["DATABASE"] = os.getenv("DATABASE_PATH", app.config["DATABASE"])
    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Initialized database.")

    def current_user():
        if "user_id" not in session:
            return None
        return query("SELECT u.*, r.name role FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?", (session["user_id"],), one=True)

    @app.context_processor
    def inject_globals():
        dashboard_language = session.get("dashboard_language", "en")
        chatbot_language = session.get("chatbot_language", "en")
        return {"current_user": current_user(), "unread_count": (query("SELECT COUNT(*) count FROM notifications WHERE is_read=0 AND (user_id IS NULL OR user_id=?)", (session.get("user_id", 0),), one=True)["count"] if session.get("user_id") else 0), "language": dashboard_language, "dashboard_language": dashboard_language, "chatbot_language": chatbot_language, "login_message": session.get("login_message", ""), "language_options": language_options(), "translations": load_language(dashboard_language), "chat_translations": load_language(chatbot_language)}

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def roles_required(*roles):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                user = current_user()
                if not user:
                    return redirect(url_for("login", next=request.path))
                if user["role"] not in roles and user["role"] != "SUPER ADMIN":
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    @app.route("/")
    def landing():
        return render_template("landing.html")

    @app.route("/login", methods=["GET", "POST"])
    @app.route("/admin/login", methods=["GET", "POST"], endpoint="admin_login")
    @app.route("/user/login", methods=["GET", "POST"], endpoint="user_login")
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = query("SELECT u.*, r.name role FROM users u JOIN roles r ON r.id=u.role_id WHERE lower(email)=? AND active=1", (email,), one=True)
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear(); session["user_id"] = user["id"]
                session["login_message"] = "ADMIN SUCCESSFULLY LOGIN" if user["role"] in ("ADMIN", "MANAGER", "SUPER ADMIN") else "USER LOGIN SUCCESSFULL"
                get_db().execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
                get_db().execute("INSERT INTO audit_logs(user_id,action,entity,details) VALUES(?,?,?,?)", (user["id"], "Login", "users", email)); get_db().commit()
                destination = "admin_dashboard" if user["role"] in ("ADMIN", "SUPER ADMIN", "MANAGER") else "staff_dashboard" if user["role"] == "STAFF" else "dashboard"
                return redirect(url_for(destination))
            flash("Invalid credentials or inactive account.", "error")
        return render_template("auth/login.html")

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            requested_role = request.form.get("role", "STAFF").strip().upper()
            admin_code = request.form.get("admin_code", "")
            errors = []
            if not name:
                errors.append("Enter your name.")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                errors.append("Enter a valid email address.")
            if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password) or not re.search(r"[^A-Za-z0-9]", password):
                errors.append("Password must be at least 8 characters and include a letter, number, and special character.")
            if password != confirm_password:
                errors.append("Passwords do not match.")
            if requested_role not in ("ADMIN", "STAFF", "VIEWER"):
                errors.append("Choose a valid account type.")
            if requested_role == "ADMIN" and (not app.config.get("ADMIN_SIGNUP_CODE") or admin_code != app.config["ADMIN_SIGNUP_CODE"]):
                errors.append("Admin signup requires an administrator authorization code.")
            if query("SELECT id FROM users WHERE lower(email)=?", (email,), one=True):
                errors.append("That email is already registered. Use another email address.")
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("auth/signup.html")
            role_id = query("SELECT id FROM roles WHERE name=?", (requested_role,), one=True)["id"]
            db = get_db()
            db.execute("INSERT INTO users(name,email,password_hash,role_id) VALUES(?,?,?,?)", (name, email, generate_password_hash(password), role_id))
            db.commit()
            flash("Account created. Sign in to open your SalesNexa workspace.", "success")
            return redirect(url_for("login"))
        return render_template("auth/signup.html")

    @app.route("/logout")
    def logout():
        session.clear(); return redirect(url_for("landing"))

    @app.route("/api/login-message")
    @login_required
    def login_message():
        return jsonify(message=session.pop("login_message", ""))

    @app.route("/api/language", methods=["GET", "POST"])
    def set_language():
        scope = request.args.get("scope", "dashboard")
        session_key = "chatbot_language" if scope == "chatbot" else "dashboard_language"
        if request.method == "GET":
            return jsonify(language=session.get(session_key, "en"), scope=scope)
        code = (request.get_json(silent=True) or {}).get("language", "en")
        if code not in [item["code"] for item in language_options()]:
            return jsonify(error="Unsupported language."), 400
        session[session_key] = code
        return jsonify(language=code, name=language_name(code), scope=scope)

    @app.route("/dashboard")
    @app.route("/admin/dashboard", endpoint="admin_dashboard")
    @app.route("/staff/dashboard", endpoint="staff_dashboard")
    @login_required
    def dashboard():
        db = get_db()
        user = current_user()
        if user["role"] == "STAFF":
            sales = db.execute("SELECT COALESCE(SUM(total),0) value,COUNT(*) transactions FROM sales WHERE user_id=? AND date(sale_date)=date('now')", (user["id"],)).fetchone()
            products_sold = db.execute("SELECT COALESCE(SUM(si.quantity),0) units FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.user_id=? AND date(s.sale_date)=date('now')", (user["id"],)).fetchone()["units"]
            trend = [dict(row) for row in db.execute("SELECT date(sale_date) period,ROUND(SUM(total),2) revenue,COUNT(*) transactions FROM sales WHERE user_id=? GROUP BY date(sale_date) ORDER BY period DESC LIMIT 30", (user["id"],)).fetchall()]
            products = [dict(row) for row in db.execute("SELECT p.name,SUM(si.quantity) units,ROUND(SUM(si.quantity*si.unit_price),2) revenue FROM sale_items si JOIN sales s ON s.id=si.sale_id JOIN products p ON p.id=si.product_id WHERE s.user_id=? GROUP BY p.id ORDER BY units DESC LIMIT 5", (user["id"],)).fetchall()]
            return render_template("staff_dashboard.html", metrics={"sales": sales["value"], "transactions": sales["transactions"], "products_sold": products_sold, "low_stock": len(tools.get_low_stock_products())}, trend=trend, products=products)
        if user["role"] in ("ADMIN", "SUPER ADMIN"):
            totals = db.execute("SELECT COALESCE(SUM(s.total),0) revenue,COALESCE(SUM(si.quantity*(si.unit_price-si.cost_price)),0) profit,COUNT(DISTINCT s.id) transactions FROM sales s LEFT JOIN sale_items si ON si.sale_id=s.id").fetchone()
            metrics = {"revenue": totals["revenue"], "profit": totals["profit"], "transactions": totals["transactions"], "customers": db.execute("SELECT COUNT(*) value FROM customers").fetchone()["value"], "low_stock": len(tools.get_low_stock_products()), "inventory_value": db.execute("SELECT COALESCE(SUM(i.quantity*p.selling_price),0) value FROM inventory i JOIN products p ON p.id=i.product_id").fetchone()["value"]}
            trend = [dict(row) for row in db.execute("SELECT substr(sale_date,1,7) period,ROUND(SUM(total),2) revenue,ROUND(SUM(si.quantity*(si.unit_price-si.cost_price)),2) profit FROM sales s JOIN sale_items si ON si.sale_id=s.id GROUP BY period ORDER BY period").fetchall()]
            product_matrix = [dict(row) for row in db.execute("SELECT p.name,COALESCE(c.name,'Uncategorized') category,SUM(si.quantity) quantity,ROUND(SUM(si.quantity*si.unit_price),2) revenue,ROUND(SUM(si.quantity*(si.unit_price-si.cost_price)),2) profit FROM sale_items si JOIN products p ON p.id=si.product_id LEFT JOIN categories c ON c.id=p.category_id GROUP BY p.id ORDER BY revenue DESC LIMIT 30").fetchall()]
            inventory_health = [dict(row) for row in db.execute("SELECT CASE WHEN i.quantity=0 THEN 'Out of stock' WHEN i.quantity<=p.reorder_level/2 THEN 'Critical' WHEN i.quantity<=p.reorder_level THEN 'Low stock' ELSE 'Healthy' END status,COUNT(*) count FROM inventory i JOIN products p ON p.id=i.product_id GROUP BY status").fetchall()]
            return render_template("admin_dashboard.html", metrics=metrics, trend=trend, product_matrix=product_matrix, inventory_health=inventory_health, forecast=revenue_forecast(3))
        kpis = db.execute("SELECT COALESCE(SUM(total),0) revenue, COUNT(*) orders FROM sales").fetchone()
        products = db.execute("SELECT COUNT(*) count FROM products WHERE active=1").fetchone()["count"]
        inventory = db.execute("SELECT COALESCE(SUM(i.quantity*p.selling_price),0) value, SUM(CASE WHEN i.quantity<=p.reorder_level THEN 1 ELSE 0 END) low FROM inventory i JOIN products p ON p.id=i.product_id").fetchone()
        trend = [dict(row) for row in db.execute("SELECT substr(sale_date,1,7) period, ROUND(SUM(total),2) revenue FROM sales GROUP BY period ORDER BY period").fetchall()]
        top_products = db.execute("SELECT p.name, SUM(si.quantity) units FROM sale_items si JOIN products p ON p.id=si.product_id GROUP BY p.id ORDER BY units DESC LIMIT 5").fetchall()
        return render_template("dashboard.html", kpis=kpis, products=products, inventory=inventory, trend=trend, top_products=top_products)

    @app.route("/products")
    @roles_required("ADMIN", "MANAGER", "STAFF")
    def products_page():
        rows = query("SELECT p.id,p.name,p.sku,p.selling_price,p.cost_price,p.reorder_level,c.name category,COALESCE(i.quantity,0) stock FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 ORDER BY p.name")
        return render_template("feature.html", title="Product Catalog", eyebrow="MANAGE / PRODUCTS", description="Searchable catalog with stock, pricing, and reorder context.", rows=rows, columns=[("name", "Product"), ("sku", "SKU"), ("category", "Category"), ("selling_price", "Sell price"), ("stock", "Stock"), ("reorder_level", "Reorder level")], feature="products")

    @app.route("/sales")
    @roles_required("ADMIN", "MANAGER", "STAFF")
    def sales_page():
        rows = query("SELECT s.id,s.sale_date,COALESCE(c.name,'Walk-in') customer,p.name product,si.quantity,ROUND(s.total,2) total,'COMPLETED' status FROM sales s JOIN sale_items si ON si.sale_id=s.id JOIN products p ON p.id=si.product_id LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.sale_date DESC LIMIT 100")
        return render_template("feature.html", title="Sales Ledger", eyebrow="MANAGE / SALES", description="Recent transactions recorded by authorized SalesNexa users.", rows=rows, columns=[("id", "Sale ID"), ("sale_date", "Date"), ("customer", "Customer"), ("product", "Product"), ("quantity", "Quantity"), ("total", "Total"), ("status", "Status")], feature="sales")

    @app.route("/sales/new")
    @roles_required("ADMIN", "MANAGER", "STAFF")
    def new_sale_page():
        rows = query("SELECT p.id,p.name,p.selling_price,COALESCE(i.quantity,0) stock FROM products p LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 ORDER BY p.name")
        customers = query("SELECT id,name FROM customers ORDER BY name LIMIT 500")
        return render_template("new_sale.html", products=rows, customers=customers)

    @app.route("/inventory")
    @login_required
    def inventory_page():
        rows = query("SELECT p.name product,i.quantity,p.reorder_level,ROUND(i.quantity*p.selling_price,2) stock_value,CASE WHEN i.quantity=0 THEN 'OUT OF STOCK' WHEN i.quantity<=p.reorder_level/2 THEN 'CRITICAL' WHEN i.quantity<=p.reorder_level THEN 'LOW' ELSE 'HEALTHY' END status FROM inventory i JOIN products p ON p.id=i.product_id ORDER BY i.quantity")
        return render_template("feature.html", title="Inventory Pulse", eyebrow="MANAGE / INVENTORY", description="Stock health calculated from current inventory and reorder levels.", rows=rows, columns=[("product", "Product"), ("quantity", "Current stock"), ("reorder_level", "Reorder level"), ("stock_value", "Stock value"), ("status", "Status")], feature="inventory")

    @app.route("/analytics")
    @roles_required("ADMIN", "MANAGER")
    def analytics_page():
        rows = tools.get_category_performance()
        return render_template("feature.html", title="Analytics Center", eyebrow="ANALYZE / PERFORMANCE", description="Revenue and profit aggregation from recorded transactions.", rows=rows, columns=[("name", "Category"), ("revenue", "Revenue")], feature="analytics")

    @app.route("/forecasting")
    @roles_required("ADMIN", "MANAGER")
    def forecasting_page():
        return render_template("feature.html", title="Forecast Lab", eyebrow="PREDICT / FORECAST", description="Regression forecast based on grouped historical revenue.", forecast=revenue_forecast(3), rows=[], columns=[], feature="forecast")

    @app.route("/insights")
    @roles_required("ADMIN", "MANAGER")
    def insights_page():
        category = tools.get_category_performance()
        low = tools.get_low_stock_products()
        insights = []
        if category: insights.append(f"{category[0]['name']} is currently the strongest category by recorded revenue.")
        insights.append(f"{len(low)} product(s) are at or below their reorder level.")
        return render_template("feature.html", title="AI Business Insights", eyebrow="DETECT / UNDERSTAND", description="Short explanations generated from current SalesNexa data.", insights=insights, rows=[], columns=[], feature="insights")

    @app.route("/customers")
    @login_required
    def customers_page():
        rows = query("SELECT c.name,c.email,c.location,COUNT(s.id) orders,ROUND(COALESCE(SUM(s.total),0),2) spending FROM customers c LEFT JOIN sales s ON s.customer_id=c.id GROUP BY c.id ORDER BY spending DESC")
        return render_template("feature.html", title="Customer Directory", eyebrow="MANAGE / CUSTOMERS", description="Customer records with calculated order and spending history.", rows=rows, columns=[("name", "Customer"), ("email", "Email"), ("location", "Location"), ("orders", "Orders"), ("spending", "Spending")], feature="customers")

    @app.route("/suppliers")
    @roles_required("ADMIN", "MANAGER")
    def suppliers_page():
        rows = query("SELECT s.name,s.contact_person,s.email,COUNT(p.id) products FROM suppliers s LEFT JOIN products p ON p.supplier_id=s.id GROUP BY s.id ORDER BY s.name")
        return render_template("feature.html", title="Supplier Network", eyebrow="MANAGE / SUPPLIERS", description="Supplier contacts and catalog relationships.", rows=rows, columns=[("name", "Supplier"), ("contact_person", "Contact"), ("email", "Email"), ("products", "Products")], feature="suppliers")

    @app.route("/anomalies")
    @roles_required("ADMIN", "MANAGER")
    def anomalies_page():
        return render_template("feature.html", title="Anomaly Watch", eyebrow="DETECT / ANOMALIES", description="Statistical deviations are reported as signals, never as fraud claims.", anomalies=sales_anomalies(), rows=[], columns=[], feature="anomalies")

    @app.route("/api/sales", methods=["GET", "POST"])
    @roles_required("ADMIN", "MANAGER", "STAFF")
    def create_sale():
        if request.method == "GET":
            return jsonify(sales=[dict(row) for row in tools.get_recent_sales(100)])
        data = request.get_json(silent=True) or request.form
        try:
            product_id, quantity = int(data["product_id"]), int(data["quantity"])
            discount, tax = max(0, float(data.get("discount", 0))), max(0, float(data.get("tax", 0)))
            if quantity <= 0: raise ValueError
            db = get_db(); product = db.execute("SELECT p.*, i.quantity FROM products p JOIN inventory i ON i.product_id=p.id WHERE p.id=? AND p.active=1", (product_id,)).fetchone()
            if not product or product["quantity"] < quantity: return jsonify(error="Product unavailable or insufficient stock."), 400
            subtotal = round(product["selling_price"] * quantity, 2); total = round(subtotal - discount + tax, 2)
            db.execute("INSERT INTO sales(customer_id,user_id,subtotal,discount,tax,total) VALUES(?,?,?,?,?,?)", (data.get("customer_id") or None, session["user_id"], subtotal, discount, tax, total))
            sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,cost_price) VALUES(?,?,?,?,?)", (sale_id, product_id, quantity, product["selling_price"], product["cost_price"]))
            remaining = product["quantity"] - quantity; db.execute("UPDATE inventory SET quantity=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=?", (remaining, product_id))
            db.execute("INSERT INTO inventory_movements(product_id,user_id,change_quantity,reason) VALUES(?,?,?,?)", (product_id, session["user_id"], -quantity, "Sale"))
            if remaining <= product["reorder_level"]: db.execute("INSERT INTO notifications(user_id,type,message) VALUES(?,?,?)", (session["user_id"], "LOW_STOCK", f"{product['name']} is low in stock ({remaining} remaining)."))
            db.execute("INSERT INTO audit_logs(user_id,action,entity,details) VALUES(?,?,?,?)", (session["user_id"], "Sale created", "sales", str(sale_id))); db.commit()
            return jsonify(sale_id=sale_id, total=total, remaining_stock=remaining)
        except (KeyError, ValueError, TypeError): return jsonify(error="Invalid sale details."), 400

    @app.route("/api/summary")
    @login_required
    def summary():
        return jsonify(revenue=query("SELECT COALESCE(SUM(total),0) value FROM sales", one=True)["value"], low_stock=[dict(x) for x in query("SELECT p.name,i.quantity,p.reorder_level FROM products p JOIN inventory i ON i.product_id=p.id WHERE i.quantity<=p.reorder_level ORDER BY i.quantity")])

    @app.route("/api/products", methods=["GET", "POST"])
    @roles_required("ADMIN", "MANAGER", "STAFF")
    def products_api():
        db = get_db()
        if request.method == "POST":
            if current_user()["role"] not in ("ADMIN", "MANAGER"):
                return jsonify(error="Staff accounts have view-only access."), 403
            data = request.get_json(silent=True) or request.form
            try:
                values = (data["name"].strip(), data["sku"].strip().upper(), int(data["category_id"]), float(data["selling_price"]), float(data["cost_price"]), int(data.get("reorder_level", 10)))
                db.execute("INSERT INTO products(name,sku,category_id,selling_price,cost_price,reorder_level) VALUES(?,?,?,?,?,?)", values)
                product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.execute("INSERT INTO inventory(product_id,quantity) VALUES(?,?)", (product_id, int(data.get("stock_quantity", 0)))); db.commit()
                return jsonify(id=product_id), 201
            except (KeyError, ValueError, sqlite3.IntegrityError):
                return jsonify(error="Product data is invalid or SKU already exists."), 400
        return jsonify(products=[dict(row) for row in db.execute("SELECT p.*, c.name category, i.quantity stock FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 ORDER BY p.name")])

    @app.route("/api/products/<int:product_id>", methods=["PUT", "DELETE"])
    @roles_required("ADMIN", "MANAGER")
    def manage_product(product_id):
        db = get_db()
        if request.method == "DELETE":
            db.execute("UPDATE products SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (product_id,))
            db.commit()
            return jsonify(deleted=True)
        data = request.get_json(silent=True) or {}
        fields = {key: data[key] for key in ("name", "description", "selling_price", "cost_price", "reorder_level") if key in data}
        if not fields:
            return jsonify(error="No update fields supplied."), 400
        assignments = ",".join(f"{key}=?" for key in fields)
        db.execute(f"UPDATE products SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=? AND active=1", tuple(fields.values()) + (product_id,))
        if "stock" in data:
            db.execute("UPDATE inventory SET quantity=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=?", (max(0, int(data["stock"])), product_id))
        db.commit()
        return jsonify(updated=True)

    @app.route("/api/sales/<int:sale_id>", methods=["PUT", "DELETE"])
    @roles_required("ADMIN", "MANAGER")
    def manage_sale(sale_id):
        db = get_db()
        sale = db.execute("SELECT id,discount,tax FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            return jsonify(error="Sale not found."), 404
        if request.method == "PUT":
            data = request.get_json(silent=True) or {}
            item = db.execute("SELECT id,product_id,quantity,unit_price FROM sale_items WHERE sale_id=?", (sale_id,)).fetchone()
            if not item:
                return jsonify(error="Sale items not found."), 409
            if "quantity" in data:
                new_quantity = int(data["quantity"])
                if new_quantity <= 0:
                    return jsonify(error="Quantity must be greater than zero."), 400
                delta = new_quantity - item["quantity"]
                stock = db.execute("SELECT quantity FROM inventory WHERE product_id=?", (item["product_id"],)).fetchone()
                if delta > 0 and (not stock or stock["quantity"] < delta):
                    return jsonify(error="Insufficient stock for this quantity."), 400
                db.execute("UPDATE inventory SET quantity=quantity-?,updated_at=CURRENT_TIMESTAMP WHERE product_id=?", (delta, item["product_id"]))
                db.execute("UPDATE sale_items SET quantity=? WHERE id=?", (new_quantity, item["id"]))
                item = dict(item); item["quantity"] = new_quantity
            if "discount" in data:
                sale = dict(sale); sale["discount"] = max(0, float(data["discount"]))
            if "tax" in data:
                sale = dict(sale); sale["tax"] = max(0, float(data["tax"]))
            total = round(item["quantity"] * item["unit_price"] - sale["discount"] + sale["tax"], 2)
            db.execute("UPDATE sales SET discount=?,tax=?,total=? WHERE id=?", (sale["discount"], sale["tax"], total, sale_id))
            db.commit()
            return jsonify(updated=True, total=total, quantity=item["quantity"])
        items = db.execute("SELECT product_id,quantity FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
        for item in items:
            db.execute("UPDATE inventory SET quantity=quantity+? WHERE product_id=?", (item["quantity"], item["product_id"]))
        db.execute("DELETE FROM sales WHERE id=?", (sale_id,))
        db.commit()
        return jsonify(deleted=True)

    @app.route("/api/manager-updates", methods=["POST"])
    @roles_required("STAFF")
    def manager_update():
        message = (request.get_json(silent=True) or {}).get("message", "").strip()
        if not message:
            return jsonify(error="Update message is required."), 400
        managers = query("SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id WHERE r.name IN ('ADMIN','MANAGER') AND u.active=1")
        db = get_db()
        for manager in managers:
            db.execute("INSERT INTO notifications(user_id,type,message) VALUES(?,?,?)", (manager["id"], "STAFF_UPDATE", f"Update from {current_user()['name']}: {message}"))
        db.commit()
        return jsonify(sent=True, recipients=len(managers))

    @app.route("/api/staff-updates", methods=["POST"])
    @roles_required("ADMIN", "MANAGER")
    def staff_update():
        message = (request.get_json(silent=True) or {}).get("message", "").strip()
        if not message:
            return jsonify(error="Update message is required."), 400
        staff = query("SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id WHERE r.name='STAFF' AND u.active=1")
        db = get_db()
        for member in staff:
            db.execute("INSERT INTO notifications(user_id,type,message) VALUES(?,?,?)", (member["id"], "ADMIN_UPDATE", f"Update from {current_user()['name']}: {message}"))
        db.commit()
        return jsonify(sent=True, recipients=len(staff))

    @app.route("/api/analytics")
    @roles_required("ADMIN", "MANAGER")
    def analytics_api():
        return jsonify(category_performance=[dict(row) for row in tools.get_category_performance()], profit=dict(tools.get_profit_summary()), top_products=[dict(row) for row in tools.get_top_products()])

    @app.route("/api/forecast")
    @roles_required("ADMIN", "MANAGER")
    def forecast_api():
        return jsonify(revenue_forecast(max(1, min(12, int(request.args.get("horizon", 3))))))

    @app.route("/api/anomalies")
    @roles_required("ADMIN", "MANAGER")
    def anomalies_api():
        return jsonify(anomalies=sales_anomalies())

    @app.route("/api/chat", methods=["POST"])
    @login_required
    def chat_api():
        data = request.get_json(silent=True) or {}
        original_question = data.get("message", "").strip()
        question = original_question.lower()
        language = data.get("language") or session.get("chatbot_language", "en")
        if not question:
            return jsonify(answer="Please ask NexaBot a business question.", grounded=True)
        previous_product = session.get("chat_product")
        answer, details, elapsed_ms, resolved_product = answer_question(original_question, language, previous_product)
        session["chat_product"] = resolved_product
        db = get_db()
        chat_session_id = session.get("chat_session_id")
        if not chat_session_id:
            cursor = db.execute("INSERT INTO chat_sessions(user_id) VALUES(?)", (session["user_id"],))
            chat_session_id = cursor.lastrowid
            session["chat_session_id"] = chat_session_id
        db.execute("INSERT INTO chat_messages(session_id,role,content,language,intent) VALUES(?,?,?,?,?)", (chat_session_id, "user", original_question, language, details["intent"]))
        db.execute("INSERT INTO chat_messages(session_id,role,content,language,intent) VALUES(?,?,?,?,?)", (chat_session_id, "assistant", answer, language, details["intent"]))
        db.commit()
        app.logger.info("chat intent=%s tool=database elapsed_ms=%.2f success=true", details["intent"], elapsed_ms)
        return jsonify(answer=answer, grounded=True, provider="database", intent=details["intent"], language=language)

    @app.route("/api/chat/history")
    @login_required
    def chat_history():
        chat_session_id = session.get("chat_session_id")
        if not chat_session_id:
            return jsonify(messages=[])
        rows = query("SELECT role,content,language,intent,created_at FROM chat_messages WHERE session_id=? ORDER BY id LIMIT 100", (chat_session_id,))
        return jsonify(messages=[dict(row) for row in rows])

    @app.route("/api/chat/clear", methods=["POST"])
    @login_required
    def clear_chat():
        chat_session_id = session.pop("chat_session_id", None)
        session.pop("chat_product", None)
        if chat_session_id:
            get_db().execute("DELETE FROM chat_sessions WHERE id=? AND user_id=?", (chat_session_id, session["user_id"]))
            get_db().commit()
        return jsonify(cleared=True)
        if any(word in question for word in ("low stock", "out of stock", "reorder", "तुल", "स्टॉक", "తక్కువ స్టాక్", "తక్కువ", "कम स्टॉक", "குறைந்த", "சரக்கு", "ಕಡಿಮೆ", "ದಾಸ್ತಾನು")):
            rows = [dict(row) for row in tools.get_low_stock_products()]
            answer = "Low-stock products: " + (", ".join(f"{row['name']} ({row['quantity']} units)" for row in rows) if rows else "No low-stock products currently detected.")
        elif any(word in question for word in ("top", "most", "best", "highest", "sold the most", "ఉత్పత్తి", "ఉత్పత్తులు", "उत्पाद", "தயாரிப்பு", "ಉತ್ಪನ್ನ")):
            rows = list(tools.get_top_products()); answer = "Top products: " + (", ".join(f"{row['name']} ({row['units']} units)" for row in rows) if rows else "no sales data available.")
        elif any(word in question for word in ("forecast", "అంచనా", "पूर्वानुमान", "முன்னறிவிப்பு", "ಮುನ್ಸೂಚನೆ")):
            result = revenue_forecast(); answer = result.get("message") or f"The next forecast values are {', '.join('₹%.2f' % value for value in result['forecast'])}."
        elif any(word in question for word in ("anomal", "unusual", "unusual sales", "असामान्य", "అసాధారణ", "அசாதாரண", "ಅಸಾಮಾನ್ಯ")):
            rows = sales_anomalies(); answer = "Unusual sales activity detected: " + (", ".join(f"sale #{row['sale_id']} (₹{row['actual']:.2f})" for row in rows) if rows else "No unusual sales activity detected.")
        elif any(word in question for word in ("category", "కేటగిరీ", "श्रेणी", "வகை", "ವರ್ಗ")):
            rows = list(tools.get_category_performance()); answer = "Top category: " + (f"{rows[0]['name']} (₹{rows[0]['revenue']:.2f})." if rows else "No category sales data available.")
        elif any(word in question for word in ("profit", "లాభ", "लाभ", "இலாப", "ಲಾಭ")):
            result = tools.get_profit_summary(); answer = f"Recorded revenue is ₹{result['revenue']:.2f} and profit is ₹{result['profit']:.2f}."
        elif any(word in question for word in ("sales", "revenue", "అమ్మకాలు", "बिक्री", "விற்பனை", "ಮಾರಾಟ")):
            if any(word in question for word in ("today", "ఈరోజు", "आज", "இன்று", "ಇಂದು")):
                result = tools.get_sales_for_date(); period = "today"
            elif any(word in question for word in ("this month", "ఈ నెల", "इस महीने", "இந்த மாதம்", "ಈ ತಿಂಗಳು")):
                start = date.today().replace(day=1); next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
                result = tools.get_sales_for_period(start.isoformat(), next_month.isoformat()); period = "this month"
            elif any(word in question for word in ("last month", "గత నెల", "पिछले महीने", "கடந்த மாதம்", "ಕಳೆದ ತಿಂಗಳು")):
                current_month = date.today().replace(day=1); previous_month = (current_month - timedelta(days=1)).replace(day=1)
                result = tools.get_sales_for_period(previous_month.isoformat(), current_month.isoformat()); period = "last month"
            else:
                result = tools.get_total_sales(); period = "recorded"
            if result["orders"]:
                if any(word in question for word in ("ఈరోజు", "ఈ నెల", "గత నెల")): answer = f"SalesNexa డేటా ప్రకారం {period} అమ్మకాలు ₹{result['value']:.2f}, {result['orders']} ఆర్డర్లు."
                elif any(word in question for word in ("आज", "इस महीने", "पिछले महीने")): answer = f"SalesNexa डेटा के अनुसार {period} की बिक्री ₹{result['value']:.2f}, {result['orders']} ऑर्डर।"
                elif any(word in question for word in ("இன்று", "இந்த மாதம்", "கடந்த மாதம்")): answer = f"SalesNexa தரவின்படி {period} விற்பனை ₹{result['value']:.2f}, {result['orders']} ஆர்டர்கள்."
                elif any(word in question for word in ("ಇಂದು", "ಈ ತಿಂಗಳು", "ಕಳೆದ ತಿಂಗಳು")): answer = f"SalesNexa ಮಾಹಿತಿಯ ಪ್ರಕಾರ {period} ಮಾರಾಟ ₹{result['value']:.2f}, {result['orders']} ಆರ್ಡರ್‌ಗಳು."
                else: answer = f"{period.title()} sales are ₹{result['value']:.2f} across {result['orders']} orders."
            else: answer = "I don't have enough data in SalesNexa to answer that accurately."
        else:
            answer = "I can only answer questions using the business data and analytics available in SalesNexa."
        return jsonify(answer=answer, grounded=True)

    @app.route("/reports/sales.csv")
    @roles_required("ADMIN", "MANAGER")
    def sales_report():
        rows = query("SELECT s.id, s.sale_date, s.total, u.name staff, c.name customer FROM sales s JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.sale_date DESC")
        output = io.StringIO(); writer = csv.writer(output); writer.writerow(["sale_id", "date", "total", "staff", "customer"]); writer.writerows([tuple(row) for row in rows])
        return app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=sales-report.csv"})

    @app.route("/notifications")
    @login_required
    def notifications():
        rows = query("SELECT * FROM notifications WHERE user_id IS NULL OR user_id=? ORDER BY created_at DESC", (session["user_id"],)); get_db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],)); get_db().commit(); return render_template("notifications.html", notifications=rows)

    @app.errorhandler(403)
    def forbidden(_): return render_template("error.html", code=403, message="You do not have permission to access this area."), 403
    @app.errorhandler(404)
    def missing(_): return render_template("error.html", code=404, message="That page does not exist."), 404
    @app.errorhandler(500)
    def server_error(_): return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500
    return app

app = create_app()
if __name__ == "__main__": app.run(debug=True)
