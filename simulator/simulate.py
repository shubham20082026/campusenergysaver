"""
Hardware-free simulator: pretends to be 3 rooms (ESP32 power sensor + camera).
Lets you test the backend and dashboard, and record a demo video, before the hardware is ready.

Run (backend must be running):  python simulate.py
Uses only the Python standard library.

Each room loops through a 120 s script of (start_s, end_s, people):
  LAB-101   always occupied                    -> stays on
  CLS-204   occupied 0-15 s, empty 15-85 s     -> warning at ~35 s, power cut at ~45 s, restored at 85 s
  HOS-H12   2 people 0-10 s, then empty        -> warning at ~30 s, cut at ~40 s, stays off (no one returns)
"""
import json
import random
import sys
import time
import urllib.request

SERVER = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
CYCLE = 120

ROOMS = {
    "LAB-101": dict(name="Lab 101", load=420, script=[(0, 120, 12)]),
    "CLS-204": dict(name="Classroom 204", load=260, script=[(0, 15, 28), (85, 120, 25)]),
    "HOS-H12": dict(name="Hostel H-12", load=110, script=[(0, 10, 2)]),
}
relay = {k: True for k in ROOMS}


def people_at(room, t):
    for s, e, n in ROOMS[room]["script"]:
        if s <= t < e:
            return n
    return 0


def post(path, payload):
    req = urllib.request.Request(SERVER + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=3).read())


print("Simulating 3 rooms. Ctrl+C to stop.")
start = time.time()
while True:
    t = (time.time() - start) % CYCLE
    for rid, cfg in ROOMS.items():
        watts = cfg["load"] * random.uniform(0.95, 1.05) if relay[rid] else random.uniform(0.2, 1.0)
        try:
            post("/api/occupancy", dict(room_id=rid, name=cfg["name"], people=people_at(rid, t)))
            reply = post("/api/telemetry", dict(room_id=rid, name=cfg["name"], watts=watts))
            relay[rid] = reply["relay"]
        except Exception as e:
            print("backend not reachable:", e)
    time.sleep(2)
