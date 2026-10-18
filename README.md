# Smart Campus Energy Saver

Empty classrooms, labs and hostel rooms keep fans, lights and ACs running. This system notices
(camera + AI), warns the caretaker on Telegram, and switches the load off with a relay, then
restores power when someone walks back in.

```
ESP32 + current sensor + relay --watts--> FastAPI <--people count-- YOLOv8 (camera)
                                  |  Isolation Forest flags unusual usage
                                  +--> Dashboard (live meter, ₹ saved) + Telegram alerts
```

## 1. Run it with no hardware (do this first, 5 minutes)

```bash
pip install -r requirements.txt
cd ai && python train_anomaly.py          # trains the anomaly model (once)
cd ../backend && uvicorn main:app --host 0.0.0.0 --port 8000
# new terminal:
cd simulator && python simulate.py
```
Open http://localhost:8000. Within about 45 seconds you will see Classroom 204 and Hostel H-12 get
a warning, a countdown, and an automatic switch-off, and the ₹ saved counter start rising.
Classroom 204 gets power back when "people" return. (`POST /api/reset` clears the demo data.)

## 2. Add the real parts

| Part | Job | Approx. cost |
|---|---|---|
| ESP32 DevKit | brain + WiFi | ₹450 |
| ACS712 (5A or 20A) | measures current | ₹150 |
| 1-channel relay module | switches the load | ₹80 |
| 10k + 20k resistors | divider, ACS712 output to 3.3 V | ₹5 |
| Laptop webcam (or ESP32-CAM) | people counting | ₹0 / ₹700 |

1. Open `esp32/energy_node/energy_node.ino`, set WiFi, your laptop's IP and the room ID, upload it.
2. Stop the simulator. Run the camera script with the same room ID:
   `cd ai && python occupancy_counter.py --room LAB-101 --name "Lab 101" --show`
3. Optional Telegram alerts: create a bot with @BotFather, then set
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` before starting uvicorn.

**Safety:** keep mains wiring enclosed and get it checked by a lab technician. For the demo use one bulb.

## 3. Settings (environment variables)

`IDLE_SECONDS` (default 20, use 600 for real rooms), `GRACE_SECONDS` (10), `LOAD_THRESHOLD_W` (15),
`TARIFF_INR_PER_KWH` (8). Safety rule built in: if the camera stops reporting for 30 s, the system
never cuts power.

## 4. 60-second demo script

1. Show the dashboard: person in front of the camera, load on, status "Occupied".
2. Person leaves. Status goes to "Empty, equipment on", Telegram warning arrives.
3. Countdown bar fills, relay clicks off, status "Switched off to save power", ₹ saved rises.
4. Person returns, power is restored automatically.
5. End on the savings calculator: rooms × watts × idle hours × tariff = yearly campus savings.

## 5. What to say about the AI

- **Computer vision:** YOLOv8 person counting. Only a number leaves the camera; no video is stored.
- **Anomaly detection:** Isolation Forest learns normal usage by hour, weekday, load and occupancy,
  and flags cases like "250 W at 2 AM in an empty room". Retrain it on real logs from `/api/history`.
- **Impact:** idle-load energy cut and rupees saved, measured live.

## Next phase ideas
On-device people counting (ESP32-CAM), PZEM-004T for exact power, MQTT for many rooms,
timetable integration so rooms booked for a class never get cut.
