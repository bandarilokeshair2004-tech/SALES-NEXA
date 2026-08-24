from datetime import date
from difflib import SequenceMatcher
from db import query


def _normalise(value):
    return "".join(value.casefold().split()).replace("-", "")


def find_products(product_name, limit=10):
    """Resolve product names without loading the complete catalog."""
    cleaned = " ".join(product_name.split()).strip()
    if not cleaned:
        return []
    normalised = _normalise(cleaned)
    exact = query("SELECT p.id,p.name,p.sku,p.description,p.selling_price,p.cost_price,p.reorder_level,c.name category,COALESCE(i.quantity,0) quantity FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 AND lower(replace(replace(p.name,' ',''),'-',''))=? LIMIT ?", (normalised, limit))
    if exact:
        if all(_normalise(row["name"]) == normalised for row in exact):
            return exact[:1]
        return exact
    pattern = f"%{normalised}%"
    matches = query("SELECT p.id,p.name,p.sku,p.description,p.selling_price,p.cost_price,p.reorder_level,c.name category,COALESCE(i.quantity,0) quantity FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 AND lower(replace(replace(p.name,' ',''),'-','')) LIKE ? ORDER BY p.name LIMIT ?", (pattern, limit))
    if matches:
        return matches
    tokens = [token for token in cleaned.casefold().split() if len(token) > 1]
    if not tokens:
        return []
    clauses = " OR ".join("lower(p.name) LIKE ?" for _ in tokens)
    candidates = query(f"SELECT p.id,p.name,p.sku,p.description,p.selling_price,p.cost_price,p.reorder_level,c.name category,COALESCE(i.quantity,0) quantity FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN inventory i ON i.product_id=p.id WHERE p.active=1 AND ({clauses}) ORDER BY p.name LIMIT ?", tuple(f"%{token}%" for token in tokens) + (limit,))
    return [row for row in candidates if SequenceMatcher(None, normalised, _normalise(row["name"])).ratio() >= .45]


def get_product_stock(product_name):
    return find_products(product_name)


def get_product_details(product_name):
    return find_products(product_name)


def get_product_sales(product_name):
    products = find_products(product_name)
    if len(products) != 1:
        return products
    return query("SELECT p.name,COALESCE(SUM(si.quantity),0) units FROM sale_items si JOIN products p ON p.id=si.product_id WHERE p.id=? GROUP BY p.id,p.name", (products[0]["id"],), one=True)


def get_product_revenue(product_name):
    products = find_products(product_name)
    if len(products) != 1:
        return products
    return query("SELECT p.name,COALESCE(SUM(si.quantity*si.unit_price),0) revenue FROM sale_items si JOIN products p ON p.id=si.product_id WHERE p.id=? GROUP BY p.id,p.name", (products[0]["id"],), one=True)


def get_product_profit(product_name):
    products = find_products(product_name)
    if len(products) != 1:
        return products
    return query("SELECT p.name,COALESCE(SUM(si.quantity*(si.unit_price-si.cost_price)),0) profit FROM sale_items si JOIN products p ON p.id=si.product_id WHERE p.id=? GROUP BY p.id,p.name", (products[0]["id"],), one=True)

def get_total_sales():
    return query("SELECT COALESCE(SUM(total),0) value, COUNT(*) orders FROM sales", one=True)

def get_sales_for_date(target=None):
    target = target or date.today().isoformat()
    return query("SELECT COALESCE(SUM(total),0) value, COUNT(*) orders FROM sales WHERE date(sale_date)=date(?)", (target,), one=True)

def get_sales_for_period(start, end):
    return query("SELECT COALESCE(SUM(total),0) value, COUNT(*) orders FROM sales WHERE date(sale_date)>=date(?) AND date(sale_date)<date(?)", (start, end), one=True)

def get_total_quantity_sold():
    return query("SELECT COALESCE(SUM(quantity),0) quantity FROM sale_items", one=True)


def get_total_transactions():
    return query("SELECT COUNT(*) transactions FROM sales", one=True)

def get_top_products():
    return query("SELECT p.name, SUM(si.quantity) units FROM sale_items si JOIN products p ON p.id=si.product_id GROUP BY p.id ORDER BY units DESC LIMIT 5")


def get_top_categories():
    return query("SELECT c.name,ROUND(SUM(si.quantity*si.unit_price),2) revenue FROM sale_items si JOIN products p ON p.id=si.product_id JOIN categories c ON c.id=p.category_id GROUP BY c.id ORDER BY revenue DESC LIMIT 5")

def get_low_stock_products():
    return query("SELECT p.name, i.quantity, p.reorder_level FROM products p JOIN inventory i ON i.product_id=p.id WHERE i.quantity<=p.reorder_level ORDER BY i.quantity")


def get_out_of_stock_products():
    return query("SELECT p.name,i.quantity FROM products p JOIN inventory i ON i.product_id=p.id WHERE i.quantity=0 ORDER BY p.name")

def get_inventory_summary():
    return query("SELECT COUNT(*) products, COALESCE(SUM(quantity),0) units, COALESCE(SUM(quantity * selling_price),0) value FROM inventory JOIN products ON products.id=inventory.product_id", one=True)

def get_profit_summary():
    return query("SELECT COALESCE(SUM(si.quantity * (si.unit_price-si.cost_price)),0) profit, COALESCE(SUM(s.total),0) revenue FROM sale_items si JOIN sales s ON s.id=si.sale_id", one=True)


def get_product_price(product_name):
    products = find_products(product_name)
    return products


def get_customer_details(customer_name):
    return query("SELECT id,name,email,phone,location FROM customers WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 10", (f"%{customer_name.strip()}%",))


def get_customer_purchase_history(customer_name):
    return query("SELECT c.name,s.id sale_id,s.sale_date,s.total,p.name product,si.quantity FROM customers c JOIN sales s ON s.customer_id=c.id JOIN sale_items si ON si.sale_id=s.id JOIN products p ON p.id=si.product_id WHERE lower(c.name) LIKE lower(?) ORDER BY s.sale_date DESC LIMIT 50", (f"%{customer_name.strip()}%",))


def get_customer_summary():
    return query("SELECT COUNT(*) customers FROM customers", one=True)


def get_sales_target(period="monthly"):
    return query("SELECT period,target FROM sales_targets WHERE period=?", (period,), one=True)

def get_category_performance():
    return query("SELECT c.name, ROUND(SUM(si.quantity*si.unit_price),2) revenue FROM sale_items si JOIN products p ON p.id=si.product_id JOIN categories c ON c.id=p.category_id GROUP BY c.id ORDER BY revenue DESC")

def get_recent_sales(limit=10):
    return query("SELECT s.id, s.sale_date, s.total, p.name product, si.quantity FROM sales s JOIN sale_items si ON si.sale_id=s.id JOIN products p ON p.id=si.product_id ORDER BY s.sale_date DESC LIMIT ?", (limit,))

def get_sales_trend():
    return query("SELECT date(sale_date) period, ROUND(SUM(total),2) revenue, COUNT(*) orders FROM sales GROUP BY date(sale_date) ORDER BY period")

def get_business_summary():
    return {"sales": dict(get_total_sales()), "inventory": dict(get_inventory_summary()), "profit": dict(get_profit_summary()), "low_stock": [dict(row) for row in get_low_stock_products()]}
