import sqlite3
from pathlib import Path
from flask import current_app, g


class Row(dict):
    def __init__(self, values, keys):
        super().__init__(zip(keys, values))
        self.values = values

    def __getitem__(self, key):
        return self.values[key] if isinstance(key, int) else super().__getitem__(key)


class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def lastrowid(self):
        return getattr(self.cursor, "lastrowid", None)

    def _row(self, value):
        if value is None or isinstance(value, sqlite3.Row):
            return value
        return Row(tuple(value), [column[0] for column in self.cursor.description or ()])

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(value) for value in self.cursor.fetchall()]

    def close(self):
        self.cursor.close()


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s").replace("date('now')", "CURRENT_DATE")
        sql = sql.replace("date(sale_date)", "sale_date::date")
        sql = sql.replace("date(?)", "(%s)::date")
        sql = sql.replace("substr(sale_date,1,7)", "TO_CHAR(sale_date, 'YYYY-MM')")
        ignore_insert = "INSERT OR IGNORE" in sql.upper()
        sql = sql.replace("INSERT OR IGNORE", "INSERT")
        if ignore_insert:
            sql += " ON CONFLICT DO NOTHING"
        return CursorAdapter(self.connection.execute(sql, params))

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def using_postgres():
    return bool(current_app.config.get("DATABASE_URL"))


def get_db():
    if "db" not in g:
        if using_postgres():
            import psycopg
            g.db = PostgresConnection(psycopg.connect(current_app.config["DATABASE_URL"]))
        else:
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
    if using_postgres():
        schema_path = Path(current_app.root_path) / "database" / "schema_postgres.sql"
        for statement in schema_path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                db.execute(statement)
        for table, columns in {"products": ("selling_price", "cost_price"), "sales": ("subtotal", "discount", "tax", "total"), "sale_items": ("unit_price", "cost_price"), "forecasts": ("predicted_revenue",), "anomalies": ("actual", "expected_low", "expected_high"), "sales_targets": ("target",)}.items():
            for column in columns:
                db.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC USING {column}::numeric")
        columns = {row["column_name"] for row in db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='chat_messages'").fetchall()}
    else:
        schema_path = Path(current_app.root_path) / "database" / "schema.sql"
        db.executescript(schema_path.read_text(encoding="utf-8"))
        columns = {row["name"] for row in db.execute("PRAGMA table_info(chat_messages)").fetchall()}
    for role in ("SUPER ADMIN", "ADMIN", "MANAGER", "STAFF", "VIEWER"):
        db.execute("INSERT INTO roles(name) VALUES (?) ON CONFLICT DO NOTHING", (role,))
    if "language" not in columns:
        db.execute("ALTER TABLE chat_messages ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
    if "intent" not in columns:
        db.execute("ALTER TABLE chat_messages ADD COLUMN intent TEXT")
    db.commit()


def query(sql, params=(), one=False):
    cursor = get_db().execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return (rows[0] if rows else None) if one else rows


def insert_id(db, sql, params=()):
    if using_postgres():
        cursor = db.execute(sql + " RETURNING id", params)
        return cursor.fetchone()[0]
    db.execute(sql, params)
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]
