"""
Counts people in a room with YOLOv8 and reports the number to the backend.
No video is stored or sent - only the integer count.

Examples:
  python occupancy_counter.py --room LAB-101 --name "Lab 101"                 # laptop webcam
  python occupancy_counter.py --room LAB-101 --source http://192.168.1.50:81/stream   # ESP32-CAM
  python occupancy_counter.py --room LAB-101 --show                           # preview window
"""
import argparse
import json
import time
import urllib.request
from collections import deque

import cv2
from ultralytics import YOLO


def post(server: str, room: str, name: str, people: int):
    body = json.dumps({"room_id": room, "people": people, "name": name}).encode()
    req = urllib.request.Request(f"{server}/api/occupancy", body, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        print("post failed:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="LAB-101")
    ap.add_argument("--name", default=None)
    ap.add_argument("--source", default="0", help="webcam index or stream URL")
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between reports")
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    model = YOLO("yolov8n.pt")                       # downloads the small model on first run
    src = int(a.source) if a.source.isdigit() else a.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit("Could not open camera/stream: " + a.source)

    # A person can be missed in a single frame; take the max of the last 5 readings so
    # one bad frame never makes an occupied room look empty.
    recent = deque(maxlen=5)
    last = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.2)
            continue
        if time.time() - last < a.interval:
            continue
        last = time.time()
        res = model(frame, classes=[0], conf=a.conf, verbose=False)[0]   # class 0 = person
        recent.append(len(res.boxes))
        people = max(recent)
        post(a.server, a.room, a.name or a.room, people)
        print(f"{a.room}: {people} people")
        if a.show:
            img = res.plot()
            cv2.putText(img, f"{people} people", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 0), 2)
            cv2.imshow("occupancy", img)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break


if __name__ == "__main__":
    main()
