from db import query
from ml.anomaly_detection import detect

def sales_anomalies():
    rows = query("SELECT id, sale_date, total FROM sales ORDER BY sale_date")
    return [{**item, "sale_id": rows[item["index"]]["id"], "date": rows[item["index"]]["sale_date"]} for item in detect([row["total"] for row in rows])]
