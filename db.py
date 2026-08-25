import sqlite3
from pathlib import Path
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    if "db" not in g:
        Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema_path = Path(current_app.root_path) / "database" / "schema.sql"
    db.executescript(schema_path.read_text(encoding="utf-8"))
    columns = {row["name"] for row in db.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "language" not in columns:
        db.execute("ALTER TABLE chat_messages ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
    if "intent" not in columns:
        db.execute("ALTER TABLE chat_messages ADD COLUMN intent TEXT")
    for role in ("SUPER ADMIN", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
        db.execute("INSERT OR IGNORE INTO roles(name) VALUES (?)", (role,))
    accounts = (("Demo Admin", "admin@salesnexa.local", "ADMIN"), ("Demo Manager", "manager@salesnexa.local", "MANAGER"), ("Demo Staff", "staff@salesnexa.local", "STAFF"), ("Demo Viewer", "viewer@salesnexa.local", "VIEWER"))
    for name, email, role in accounts:
        role_id = db.execute("SELECT id FROM roles WHERE name=?", (role,)).fetchone()[0]
        db.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role_id) VALUES(?,?,?,?)", (name, email, generate_password_hash("DemoPass123!"), role_id))
    db.commit()


def query(sql, params=(), one=False):
    cursor = get_db().execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return (rows[0] if rows else None) if one else rows
