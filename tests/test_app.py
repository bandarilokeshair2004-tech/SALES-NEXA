import os
import tempfile
import pytest
from app import create_app
from database.seed import seed

@pytest.fixture
def client(monkeypatch):
    path = os.path.join(tempfile.gettempdir(), "salesnexa-test.db")
    if os.path.exists(path): os.remove(path)
    monkeypatch.setenv("DATABASE_PATH", path)
    seed()
    app = create_app({"TESTING": True, "DATABASE": path})
    return app.test_client()

def login(client, email="admin@salesnexa.local"):
    return client.post("/login", data={"email": email, "password": "DemoPass123!"})

def test_auth_and_dashboard(client):
    response = login(client)
    assert response.status_code == 302
    assert client.get("/dashboard").status_code == 200

def test_database_initialization_creates_demo_accounts(monkeypatch):
    path = os.path.join(tempfile.gettempdir(), "salesnexa-init-test.db")
    if os.path.exists(path): os.remove(path)
    monkeypatch.setenv("DATABASE_PATH", path)
    app = create_app({"TESTING": True, "DATABASE": path})
    response = app.test_client().post("/login", data={"email": "admin@salesnexa.local", "password": "DemoPass123!"})
    assert response.status_code == 302

def test_staff_cannot_read_admin_only_placeholder(client):
    assert login(client, "staff@salesnexa.local").status_code == 302
    assert client.get("/api/analytics").status_code == 403

def test_sale_reduces_inventory_and_returns_server_total(client):
    login(client)
    response = client.post("/api/sales", json={"product_id": 1, "quantity": 2, "discount": 5})
    assert response.status_code == 200
    assert response.json["total"] == 235.0
    assert response.json["remaining_stock"] >= 0

def test_chatbot_is_grounded(client):
    login(client)
    response = client.post("/api/chat", json={"message": "Which product sold the most?"})
    assert response.status_code == 200
    assert response.json["grounded"] is True

def test_chatbot_handles_supported_and_unsupported_questions(client):
    login(client)
    today = client.post("/api/chat", json={"message": "What are today's sales?"})
    assert today.status_code == 200
    assert "sales are" in today.json["answer"].lower() or "enough data" in today.json["answer"].lower()
    unsupported = client.post("/api/chat", json={"message": "Tell me a joke"})
    assert unsupported.json["answer"] == "I can only answer questions using the business data and analytics available in SalesNexa."

def test_language_selection_persists_in_session(client):
    response = client.post("/api/language", json={"language": "hi"})
    assert response.status_code == 200
    assert response.json["language"] == "hi"
    assert client.get("/dashboard").status_code == 302

def test_chatbot_uses_configured_ai_response(client, monkeypatch):
    login(client)
    monkeypatch.setattr("app.answer_with_ai", lambda *args: "आपकी बिक्री अच्छी है।")
    response = client.post("/api/chat", json={"message": "How is business?", "language": "hi"})
    assert response.status_code == 200
    assert response.json["provider"] == "database"
    assert "revenue" in response.json["answer"].lower()

def test_chatbot_reads_product_stock_from_database(client):
    login(client)
    with client.application.app_context():
        from db import get_db
        db = get_db()
        existing = db.execute("SELECT id FROM products WHERE lower(replace(name,' ',''))='usbhub13'").fetchone()
        if existing:
            product_id = existing["id"]
            db.execute("UPDATE inventory SET quantity=25 WHERE product_id=?", (product_id,))
        else:
            db.execute("INSERT INTO products(name,sku,category_id,description,selling_price,cost_price,reorder_level) VALUES(?,?,?,?,?,?,?)", ("USB HUB 13", "USB-13", 1, "Test product", 50, 25, 10))
            product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO inventory(product_id,quantity) VALUES(?,?)", (product_id, 25))
        db.commit()
    for question in ("How many USB HUB 13 are there?", "what is the stock of usb hub13?", "USB HUB 13 எத்தனை கையிருப்பில் உள்ளன?"):
        response = client.post("/api/chat", json={"message": question})
        assert response.status_code == 200
        assert "usb hub 13" in response.json["answer"].lower()
        assert "25" in response.json["answer"]

def test_chatbot_handles_ambiguous_and_unknown_products(client):
    login(client)
    with client.application.app_context():
        from db import get_db
        db = get_db()
        for suffix in ("10", "11"):
            db.execute("INSERT INTO products(name,sku,category_id,selling_price,cost_price,reorder_level) VALUES(?,?,?,?,?,?)", (f"USB HUB {suffix}", f"AMB-{suffix}", 1, 50, 25, 10))
            product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO inventory(product_id,quantity) VALUES(?,?)", (product_id, 5))
        db.commit()
    ambiguous = client.post("/api/chat", json={"message": "What is the stock of USB HUB?"})
    assert "multiple" in ambiguous.json["answer"].lower()
    unknown = client.post("/api/chat", json={"message": "What is the stock of imaginary product 99?"})
    assert "couldn't find" in unknown.json["answer"].lower()

def test_chatbot_follow_up_and_history_can_be_cleared(client):
    login(client)
    with client.application.app_context():
        from db import get_db
        db = get_db()
        db.execute("INSERT INTO products(name,sku,category_id,selling_price,cost_price,reorder_level) VALUES(?,?,?,?,?,?)", ("Follow Product", "FOLLOW-1", 1, 50, 25, 10))
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO inventory(product_id,quantity) VALUES(?,?)", (product_id, 5))
        db.commit()
    first = client.post("/api/chat", json={"message": "What is the stock of Follow Product?"})
    follow_up = client.post("/api/chat", json={"message": "Is that low?"})
    assert "low" in follow_up.json["answer"].lower()
    assert client.get("/api/chat/history").json["messages"]
    assert client.post("/api/chat/clear").json["cleared"] is True
    assert client.get("/api/chat/history").json["messages"] == []

def test_feature_routes_are_real_pages(client):
    login(client, "manager@salesnexa.local")
    for path in ("/products", "/sales", "/inventory", "/analytics", "/forecasting", "/insights", "/customers", "/suppliers", "/anomalies"):
        assert client.get(path).status_code == 200

def test_staff_is_view_only_but_can_notify_managers(client):
    assert login(client, "staff@salesnexa.local").status_code == 302
    assert client.post("/api/sales", json={"product_id": 1, "quantity": 1}).status_code == 200
    assert client.post("/api/products", json={"name": "No Write", "sku": "NO-WRITE", "category_id": 1, "selling_price": 1, "cost_price": 1}).status_code == 403
    update = client.post("/api/manager-updates", json={"message": "Sales need review."})
    assert update.status_code == 200
    assert update.json["sent"] is True

def test_admin_can_update_and_delete_product(client):
    login(client)
    created = client.post("/api/products", json={"name": "Managed Product", "sku": "MANAGED-1", "category_id": 1, "selling_price": 10, "cost_price": 5})
    assert created.status_code == 201
    product_id = created.json["id"]
    assert client.put(f"/api/products/{product_id}", json={"selling_price": 12}).status_code == 200
    assert client.delete(f"/api/products/{product_id}").status_code == 200

def test_admin_can_send_update_to_staff(client):
    login(client)
    response = client.post("/api/staff-updates", json={"message": "Please review today's stock."})
    assert response.status_code == 200
    assert response.json["sent"] is True

def test_manager_sale_quantity_edit_recalculates_total_and_inventory(client):
    login(client, "manager@salesnexa.local")
    with client.application.app_context():
        from db import get_db
        db = get_db()
        before = db.execute("SELECT quantity FROM inventory WHERE product_id=1").fetchone()["quantity"]
        price = db.execute("SELECT selling_price FROM products WHERE id=1").fetchone()["selling_price"]
    created = client.post("/api/sales", json={"product_id": 1, "quantity": 2, "discount": 5, "tax": 10})
    assert created.status_code == 200
    sale_id = created.json["sale_id"]
    edited = client.put(f"/api/sales/{sale_id}", json={"quantity": 4})
    assert edited.status_code == 200
    assert edited.json["total"] == round(price * 4 - 5 + 10, 2)
    with client.application.app_context():
        from db import get_db
        db = get_db()
        after = db.execute("SELECT quantity FROM inventory WHERE product_id=1").fetchone()["quantity"]
    assert after == before - 4
