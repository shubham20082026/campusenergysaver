# Smart Campus Energy Saver

An AI + IoT system that stops campus electricity from being wasted in empty rooms.
A camera counts the people in a room, a sensor measures how much power the room is using, and
when nobody is there but fans, lights or ACs are still running, the system warns the caretaker
and switches the load off with a relay. When someone walks back in, power is restored.

## How it works

```
ESP32 + current sensor + relay ──── watts ────►  FastAPI backend  ◄──── people count ──── YOLOv8 camera script
        ▲                                              │
        └────────── relay on/off reply ◄───────────────┤
                                                       ├──► Isolation Forest flags unusual usage
                                                       ├──► Telegram alerts (optional)
                                                       └──► Live dashboard (browser)
```

1. The ESP32 measures current, converts it to watts, and posts it to the server every 2 seconds.
2. The camera script counts people with YOLOv8 and posts only the number. No video is stored or sent.
3. The server tracks each room. If a room is empty but still drawing power:
   - after `IDLE_SECONDS` it sends a warning,
   - after `GRACE_SECONDS` more it sets the relay to OFF.
4. The ESP32 receives the relay state in the reply to each post and switches the relay.
5. When people are detected again, power is restored automatically.
6. An Isolation Forest model learns normal usage (by hour, weekday, load, occupancy) and flags
   unusual patterns, such as 250 W at 2 AM in an empty room.

## Features

- Live dashboard: power wasted right now, rupees and kWh saved, per-room status with countdown
- Automatic switch-off and automatic restore
- Manual override per room (Switch on / Switch off buttons)
- Anomaly detection with a trained ML model
- Telegram alerts for warnings, switch-offs and anomalies
- Safety rule: if the camera stops reporting for 30 seconds, power is never cut
- Hardware-free simulator for testing and demo recording
- Campus-wide yearly savings estimate calculator

## Project structure

```
campus-energy-saver/
├── backend/main.py                     FastAPI server, room logic, alerts, database
├── ai/train_anomaly.py                 trains the anomaly model (run once)
├── ai/occupancy_counter.py             YOLOv8 people counter, posts to the server
├── esp32/energy_node/energy_node.ino   ESP32 firmware
├── frontend/index.html                 dashboard (served by the backend)
├── simulator/simulate.py               fake rooms for testing without hardware
└── requirements.txt
```

## Requirements

- Python 3.10 to 3.12 recommended (the YOLO packages may not install on very new versions such as 3.14)
- A laptop and a browser
- For the full hardware demo: ESP32, ACS712 current sensor, relay module, a webcam

## Setup (Windows)

Use a virtual environment so everything installs once and is reused:

```bash
cd campus-energy-saver
py -3.12 -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

Run `venv\Scripts\activate` in every new terminal before running anything below.
Always call pip as `python -m pip`, which avoids broken `pip.exe` launcher errors.

To test the dashboard first, you only need the light packages:

```bash
python -m pip install fastapi uvicorn scikit-learn joblib numpy
```

Install `ultralytics` and `opencv-python` later, when you connect the camera.

## Run the demo without hardware

Terminal 1, train the anomaly model once, then start the backend:

```bash
cd ai
python train_anomaly.py
cd ../backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Terminal 2, start the simulator:

```bash
cd simulator
python simulate.py
```

Open **http://localhost:8000** in your browser. Do not use `0.0.0.0` in the browser, it is only
the address the server listens on.

What you will see in the first two minutes:

| Time | Room | Event |
|---|---|---|
| 0 s | Lab 101 | stays occupied, power on throughout |
| ~35 s | Classroom 204 | warning, countdown starts |
| ~45 s | Classroom 204 | power switched off, rupees saved start rising |
| ~85 s | Classroom 204 | people return, power restored |
| ~30 s | Hostel H-12 | warning |
| ~40 s | Hostel H-12 | power switched off, stays off |

## Run with real hardware

### Parts

| Part | Purpose |
|---|---|
| ESP32 DevKit | microcontroller with WiFi |
| ACS712 (5A or 20A) | measures current |
| 1-channel relay module | switches the load |
| 10 kΩ and 20 kΩ resistors | voltage divider for the ACS712 output |
| Webcam (or ESP32-CAM) | counts people |

### Wiring

| From | To |
|---|---|
| ACS712 VCC | ESP32 VIN (5 V) |
| ACS712 GND | ESP32 GND |
| ACS712 OUT | 10 kΩ resistor, then GPIO34 |
| GPIO34 | 20 kΩ resistor to GND (this forms the divider) |
| Relay VCC / GND | 5 V / GND |
| Relay IN | GPIO26 |
| Load (bulb or fan) | in series through the ACS712 and the relay COM / NO terminals |

The divider is required because the ACS712 outputs up to 5 V and the ESP32 pin tolerates 3.3 V.

**Safety:** mains voltage can kill. Keep all mains wiring enclosed and insulated, use a single bulb
for the demo, and have a lab technician check it before powering on.

### Steps

1. Open `esp32/energy_node/energy_node.ino` in Arduino IDE (ESP32 board package installed).
2. Edit the settings at the top: WiFi name and password, `SERVER_URL` (your laptop's IPv4
   address, from `ipconfig`), `ROOM_ID` and `ROOM_NAME`. If your relay switches ON when the pin is
   HIGH, set `RELAY_ACTIVE_LOW` to `false`. Set `SENSITIVITY` to match your ACS712 (20A: 0.100,
   5A: 0.185, 30A: 0.066).
3. Upload the sketch. Open the Serial Monitor at 115200 baud to see current and watts.
4. Stop the simulator. Start the camera counter with the same room ID:

```bash
cd ai
python occupancy_counter.py --room LAB-101 --name "Lab 101" --show
```

The first run downloads the `yolov8n.pt` model into the folder you run it from, so always run it
from the `ai` folder. Press `q` in the preview window to quit. For an ESP32-CAM use
`--source http://<camera-ip>:81/stream`.

The ESP32 and the laptop must be on the same WiFi network. If the ESP32 cannot connect, allow
Python through Windows Firewall on port 8000.

## Telegram alerts (optional)

1. In Telegram, message @BotFather, create a bot, and copy the token.
2. Send any message to your bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat` `id` number.
3. Set the variables in the terminal before starting uvicorn.

Command Prompt:
```bash
set TELEGRAM_BOT_TOKEN=your_token
set TELEGRAM_CHAT_ID=your_chat_id
```
PowerShell:
```bash
$env:TELEGRAM_BOT_TOKEN="your_token"
$env:TELEGRAM_CHAT_ID="your_chat_id"
```

## Settings

Set these as environment variables before starting the backend.

| Variable | Default | Meaning |
|---|---|---|
| `IDLE_SECONDS` | 20 | empty this long with load on, then warn (use about 600 in real rooms) |
| `GRACE_SECONDS` | 10 | wait this long after the warning, then cut power |
| `LOAD_THRESHOLD_W` | 15 | below this the room counts as "nothing running" |
| `OCC_STALE_SECONDS` | 30 | camera silent this long, never auto-cut |
| `TARIFF_INR_PER_KWH` | 8 | electricity price used for rupees saved |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | enable Telegram alerts |

## Manual control

Each room row has a button.

- **Switch off** cuts power immediately and keeps it off until you press Switch on.
- **Switch on** restores power and stops auto-cut for that room until someone is detected in it again.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/telemetry` | ESP32 sends `{room_id, watts, name?, people?}`, gets `{relay: true/false}` |
| POST | `/api/occupancy` | camera script sends `{room_id, people, name?}` |
| POST | `/api/rooms/{id}/relay` | manual override, body `{on: true/false}` |
| GET | `/api/rooms` | current state of all rooms |
| GET | `/api/summary` | totals: kWh saved, rupees saved, watts wasted now |
| GET | `/api/events?limit=30` | recent warnings, switch-offs, anomalies |
| GET | `/api/history/{id}?limit=60` | recent power readings for a room |
| POST | `/api/reset` | clear all rooms and history (use between demos) |

Interactive API docs are at http://localhost:8000/docs.

## The AI in this project

- **Computer vision:** YOLOv8 (nano) detects the person class in each frame. The script takes the
  highest count of the last 5 readings so one missed frame never makes an occupied room look empty.
  Only the count leaves the camera script.
- **Anomaly detection:** an Isolation Forest is trained on normal usage with features
  `[hour, weekday, watts, occupied]`. In the supplied version it is trained on synthetic data so you
  can start immediately. To improve it, log real readings from `/api/history` for a few days and
  retrain on them.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Fatal error in launcher` when running pip | use `python -m pip install ...` instead of `pip install ...` |
| `ultralytics` or `opencv` will not install | use Python 3.11 or 3.12 in a virtual environment |
| Browser shows `ERR_ADDRESS_INVALID` | open `http://localhost:8000`, not `0.0.0.0` |
| Dashboard says it cannot reach the server | start uvicorn from inside the `backend` folder |
| Dashboard empty | start the simulator, or power the ESP32 and camera script |
| ESP32 cannot reach the server | check the laptop IP in the sketch, same WiFi, firewall port 8000 |
| Room shows "Camera offline" | the camera script is not running or stopped reporting |
| Relay behaves backwards | flip `RELAY_ACTIVE_LOW` in the sketch |
| Watts read 0 or look wrong | check the divider, and `SENSITIVITY` for your ACS712 version |
| YOLO model downloads every time | run the camera script from the same folder each time |

## Demo walkthrough (~1 minute)

> Start the app, open the dashboard, and point the camera at the room.
> Demo mode uses shortened delays; real deployments use the defaults in `config`.

1. **Occupied:** A person is in frame. The dashboard shows *Occupied* and the load is on.
2. **Empty, equipment on:** The person leaves. Status changes to *Empty, equipment on* and a Telegram warning is sent.
3. **Auto switch-off:** The countdown bar fills, the relay clicks off, and the status reads *Switched off to save power*. The rupees-saved counter starts rising.
4. **Auto restore:** The person returns and power is restored automatically.
5. **Savings estimate:** The calculator projects yearly savings:
   `rooms × watts × idle hours × tariff`

## Limitations and next steps

- Power is estimated from current with a fixed voltage and power factor. A PZEM-004T module gives exact watts.
- Occupancy comes from one camera per room, so people outside its view are not counted.
- Ideas for the next phase: on-device counting with ESP32-CAM, MQTT for many rooms, timetable
  integration so booked rooms are never cut, a mobile app for caretakers, and a model trained on real campus data.
