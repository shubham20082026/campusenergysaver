"""
Smart Campus Energy Saver - backend
-----------------------------------
ESP32 (power sensor + relay)  --POST /api/telemetry-->  this server
Camera / YOLO script          --POST /api/occupancy-->  this server
Dashboard                     <--GET  /api/rooms etc.--  this server

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000   (from the backend/ folder)
"""
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent.parent
DB_PATH = Path(__file__).resolve().parent / "energy.db"
FRONTEND = BASE / "frontend" / "index.html"
MODEL_PATH = BASE / "ai" / "anomaly_model.joblib"

# ---- Settings (override with environment variables) -----------------------
IDLE_SECONDS = int(os.getenv("IDLE_SECONDS", 20))        # empty this long with load on -> warn (use 600 in real life)
GRACE_SECONDS = int(os.getenv("GRACE_SECONDS", 10))      # after the warning, wait this long, then cut power
LOAD_THRESHOLD_W = float(os.getenv("LOAD_THRESHOLD_W", 15))   # below this the room counts as "nothing running"
OCC_STALE_SECONDS = int(os.getenv("OCC_STALE_SECONDS", 30))   # camera silent this long -> never auto-cut
TARIFF = float(os.getenv("TARIFF_INR_PER_KWH", 8))
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

app = FastAPI(title="Smart Campus Energy Saver")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

lock = threading.RLock()
rooms: dict = {}

# ---- Optional ML anomaly model (trained by ai/train_anomaly.py) -------------
_anomaly_model = None
try:
    import joblib
    if MODEL_PATH.exists():
        _anomaly_model = joblib.load(MODEL_PATH)
        print("[ai] anomaly model loaded")
except Exception as e:  # model is optional
    print("[ai] anomaly model not loaded:", e)


def is_anomalous(watts: float, people: Optional[int]) -> bool:
    """True if this (time, load, occupancy) combination is unusual for a campus room."""
    if watts < LOAD_THRESHOLD_W:
        return False
    now = datetime.now()
    occupied = 1 if (people or 0) > 0 else 0
    if _anomaly_model is not None:
        x = [[now.hour + now.minute / 60, now.weekday(), watts, occupied]]
        return int(_anomaly_model.predict(x)[0]) == -1
    # fallback rule if no model: load running at night with nobody inside
    return (now.hour >= 22 or now.hour < 5) and not occupied


# ---- Database --------------------------------------------------------------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS events (ts REAL, room_id TEXT, kind TEXT, message TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS samples (ts REAL, room_id TEXT, watts REAL, people INTEGER)")
db.commit()


def log_event(room_id: str, kind: str, message: str, notify: bool = False):
    with lock:
        db.execute("INSERT INTO events VALUES (?,?,?,?)", (time.time(), room_id, kind, message))
        db.commit()
    print(f"[{kind}] {room_id}: {message}")
    if notify:
        threading.Thread(target=send_telegram, args=(f"{room_id}: {message}",), daemon=True).start()


def send_telegram(text: str):
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": "⚡ " + text}).encode()
        urllib.request.urlopen(url, data, timeout=5)
    except Exception as e:
        print("[telegram] failed:", e)


# ---- Room state ------------------------------------------------------------
def get_room(room_id: str, name: Optional[str] = None) -> dict:
    with lock:
        if room_id not in rooms:
            now = time.time()
            rooms[room_id] = dict(
                id=room_id, name=name or room_id, watts=0.0, people=None,
                last_occ_ts=0.0, last_person_ts=now, last_tick=now, last_sample=0.0,
                relay_on=True, auto_cut=False, manual_hold=False, baseline_w=0.0,
                warned=False, anomaly=False, anomaly_logged=False,
                total_wh=0.0, wasted_wh=0.0, saved_wh=0.0,
            )
        if name:
            rooms[room_id]["name"] = name
        return rooms[room_id]


def camera_alive(r: dict, now: float) -> bool:
    return r["people"] is not None and (now - r["last_occ_ts"]) < OCC_STALE_SECONDS


def tick_room(r: dict, now: float):
    dt = min(now - r["last_tick"], 10)
    r["last_tick"] = now
    wh = r["watts"] * dt / 3600
    r["total_wh"] += wh
    alive = camera_alive(r, now)
    occupied = alive and r["people"] > 0
    if occupied:
        r["last_person_ts"] = now
        r["warned"] = False
        r["manual_hold"] = False      # manual "keep on" lasts until the room is used again
        if not r["relay_on"] and r["auto_cut"]:
            r["relay_on"], r["auto_cut"] = True, False
            log_event(r["id"], "restored", f"{r['name']}: someone came back, power restored")
    load_on = r["relay_on"] and r["watts"] >= LOAD_THRESHOLD_W

    if alive and not occupied and load_on and not r["manual_hold"]:
        r["wasted_wh"] += wh
        empty_for = now - r["last_person_ts"]
        if empty_for >= IDLE_SECONDS and not r["warned"]:
            r["warned"] = True
            log_event(r["id"], "warning",
                      f"{r['name']} is empty but drawing {r['watts']:.0f} W. Cutting power in {GRACE_SECONDS}s.",
                      notify=True)
        if empty_for >= IDLE_SECONDS + GRACE_SECONDS:
            r["baseline_w"] = r["watts"]
            r["relay_on"], r["auto_cut"] = False, True
            log_event(r["id"], "cut",
                      f"{r['name']}: power switched off automatically (was {r['watts']:.0f} W).", notify=True)
    if not r["relay_on"] and r["auto_cut"] and alive and not occupied:
        r["saved_wh"] += r["baseline_w"] * dt / 3600   # energy we avoided burning

    if now - r["last_sample"] >= 5:
        r["last_sample"] = now
        with lock:
            db.execute("INSERT INTO samples VALUES (?,?,?,?)",
                       (now, r["id"], r["watts"], r["people"] if r["people"] is not None else -1))
            db.commit()


def ticker():
    while True:
        time.sleep(1)
        now = time.time()
        with lock:
            for r in rooms.values():
                tick_room(r, now)


threading.Thread(target=ticker, daemon=True).start()


def public(r: dict) -> dict:
    now = time.time()
    alive = camera_alive(r, now)
    occupied = alive and r["people"] > 0
    if not r["relay_on"]:
        state = "cut" if r["auto_cut"] else "off"
    elif not alive:
        state = "no-camera"
    elif occupied:
        state = "occupied"
    elif r["watts"] >= LOAD_THRESHOLD_W:
        # room is empty but equipment is running: first "watching", then "countdown" after the warning
        state = "countdown" if now - r["last_person_ts"] >= IDLE_SECONDS else "watching"
    else:
        state = "empty"
    countdown = None
    if state == "countdown":
        countdown = max(0, round(IDLE_SECONDS + GRACE_SECONDS - (now - r["last_person_ts"])))
    return dict(
        id=r["id"], name=r["name"], state=state, watts=round(r["watts"], 1), people=r["people"],
        relay_on=r["relay_on"], countdown=countdown, idle_limit=IDLE_SECONDS + GRACE_SECONDS,
        anomaly=r["anomaly"], total_kwh=round(r["total_wh"] / 1000, 4),
        wasted_kwh=round(r["wasted_wh"] / 1000, 4), saved_kwh=round(r["saved_wh"] / 1000, 4),
        saved_inr=round(r["saved_wh"] / 1000 * TARIFF, 2),
    )


# ---- API -------------------------------------------------------------------
class Telemetry(BaseModel):
    room_id: str
    watts: float
    name: Optional[str] = None
    people: Optional[int] = None   # optional: ESP32-CAM can send occupancy too


class Occupancy(BaseModel):
    room_id: str
    people: int
    name: Optional[str] = None


class RelayCmd(BaseModel):
    on: bool


@app.post("/api/telemetry")
def telemetry(t: Telemetry):
    """ESP32 posts power use; the reply tells it what the relay should do."""
    with lock:
        r = get_room(t.room_id, t.name)
        r["watts"] = max(0.0, t.watts)
        if t.people is not None:
            r["people"], r["last_occ_ts"] = t.people, time.time()
            if t.people > 0:
                r["last_person_ts"] = time.time()
        r["anomaly"] = is_anomalous(r["watts"], r["people"])
        if r["anomaly"] and not r["anomaly_logged"]:
            r["anomaly_logged"] = True
            log_event(r["id"], "anomaly",
                      f"{r['name']}: unusual usage pattern ({r['watts']:.0f} W at this time).", notify=True)
        if not r["anomaly"]:
            r["anomaly_logged"] = False
        return {"relay": r["relay_on"]}


@app.post("/api/occupancy")
def occupancy(o: Occupancy):
    """Camera script posts how many people it sees."""
    with lock:
        r = get_room(o.room_id, o.name)
        r["people"], r["last_occ_ts"] = o.people, time.time()
        if o.people > 0:
            r["last_person_ts"] = time.time()
        return {"ok": True}


@app.post("/api/rooms/{room_id}/relay")
def manual_relay(room_id: str, cmd: RelayCmd):
    """Manual override from the dashboard."""
    with lock:
        if room_id not in rooms:
            raise HTTPException(404, "unknown room")
        r = rooms[room_id]
        r["relay_on"], r["auto_cut"] = cmd.on, False
        r["manual_hold"] = cmd.on          # manual ON stops auto-cut until the room is used again
        if cmd.on:
            r["last_person_ts"] = time.time()
        r["warned"] = False
        log_event(room_id, "manual", f"{r['name']}: power turned {'on' if cmd.on else 'off'} from dashboard")
        return {"relay": r["relay_on"]}


@app.get("/api/rooms")
def list_rooms():
    with lock:
        return [public(r) for r in rooms.values()]


@app.get("/api/summary")
def summary():
    with lock:
        rs = list(rooms.values())
        saved = sum(r["saved_wh"] for r in rs) / 1000
        wasted = sum(r["wasted_wh"] for r in rs) / 1000
        total = sum(r["total_wh"] for r in rs) / 1000
        wasting_now = sum(r["watts"] for r in rs
                          if camera_alive(r, time.time()) and r["people"] == 0
                          and r["relay_on"] and r["watts"] >= LOAD_THRESHOLD_W)
        return dict(rooms=len(rs), total_kwh=round(total, 3), wasted_kwh=round(wasted, 3),
                    saved_kwh=round(saved, 3), saved_inr=round(saved * TARIFF, 2),
                    wasting_now_w=round(wasting_now), tariff=TARIFF)


@app.get("/api/events")
def events(limit: int = 30):
    with lock:
        rows = db.execute("SELECT ts,room_id,kind,message FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(ts=a, room_id=b, kind=c, message=d) for a, b, c, d in rows]


@app.get("/api/history/{room_id}")
def history(room_id: str, limit: int = 60):
    with lock:
        rows = db.execute("SELECT ts,watts,people FROM samples WHERE room_id=? ORDER BY ts DESC LIMIT ?",
                          (room_id, limit)).fetchall()
    return [dict(ts=a, watts=b, people=c) for a, b, c in reversed(rows)]


@app.post("/api/reset")
def reset():
    """Wipe everything - handy between demo runs."""
    with lock:
        rooms.clear()
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM samples")
        db.commit()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(FRONTEND)
