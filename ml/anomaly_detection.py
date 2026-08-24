import numpy as np

def detect(values, threshold=2.5):
    numbers = np.asarray([float(value) for value in values])
    if len(numbers) < 4:
        return []
    mean, std = numbers.mean(), numbers.std()
    if std == 0:
        return []
    return [{"index": index, "actual": round(float(value), 2), "expected_low": round(float(mean - 2 * std), 2), "expected_high": round(float(mean + 2 * std), 2), "deviation": round(float((value - mean) / std), 2)} for index, value in enumerate(numbers) if abs(value - mean) / std >= threshold]
