import numpy as np
from sklearn.linear_model import LinearRegression

def forecast(values, horizon=3):
    values = [float(value) for value in values]
    if len(values) < 3:
        return {"available": False, "message": "Insufficient historical data for reliable forecasting."}
    x = np.arange(len(values)).reshape(-1, 1)
    model = LinearRegression().fit(x, values)
    future_x = np.arange(len(values), len(values) + horizon).reshape(-1, 1)
    predictions = [round(max(0, float(value)), 2) for value in model.predict(future_x)]
    residuals = values - model.predict(x)
    mae = round(float(np.mean(np.abs(residuals))), 2)
    rmse = round(float(np.sqrt(np.mean(residuals ** 2))), 2)
    return {"available": True, "model": "linear_regression", "forecast": predictions, "mae": mae, "rmse": rmse, "mape": round(float(np.mean(np.abs(residuals / np.maximum(values, 1))) * 100), 2)}
