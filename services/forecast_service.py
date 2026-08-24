from db import query
from ml.forecasting import forecast

def revenue_forecast(horizon=3):
    rows = query("SELECT substr(sale_date,1,7) period, SUM(total) value FROM sales GROUP BY period ORDER BY period")
    result = forecast([row["value"] for row in rows], horizon)
    result["historical"] = [dict(row) for row in rows]
    return result
