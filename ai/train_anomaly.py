"""
Trains an Isolation Forest on what NORMAL room usage looks like, then saves it.
Features: [hour of day (0-24), weekday (0=Mon), watts, occupied (0/1)]

The data here is synthetic so you can start immediately. For a stronger submission,
log a few days of real readings from /api/history and retrain on those.

Run:  python train_anomaly.py
"""
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

rng = np.random.default_rng(42)
rows = []

for _ in range(6000):
    weekday = int(rng.integers(0, 7))
    kind = rng.choice(["class", "evening", "idle_ok"], p=[0.6, 0.25, 0.15])
    if weekday < 5 and kind == "class":            # teaching hours: people + equipment on
        hour = rng.uniform(8.5, 17.5)
        rows.append([hour, weekday, rng.normal(240, 60), 1])
    elif kind == "evening":                         # labs / hostels in the evening, occupied
        hour = rng.uniform(17.5, 22.0)
        rows.append([hour, weekday, rng.normal(150, 50), 1])
    else:                                           # equipment off when empty (tiny standby)
        hour = rng.uniform(0, 24)
        rows.append([hour, weekday, abs(rng.normal(3, 2)), 0])

X = np.array(rows)
model = IsolationForest(n_estimators=200, contamination=0.01, random_state=42).fit(X)

out = Path(__file__).resolve().parent / "anomaly_model.joblib"
joblib.dump(model, out)
print("saved", out)

tests = {
    "Tue 11:00, 250 W, occupied   (normal)": [11, 1, 250, 1],
    "Tue 14:00, 230 W, occupied   (normal)": [14, 1, 230, 1],
    "Wed 02:00, 250 W, EMPTY      (anomaly)": [2, 2, 250, 0],
    "Sun 23:30, 300 W, EMPTY      (anomaly)": [23.5, 6, 300, 0],
}
for name, x in tests.items():
    label = "anomaly" if model.predict([x])[0] == -1 else "normal"
    print(f"{name:42s} -> {label}")
