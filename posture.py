# /// script
# dependencies = ["mediapipe"]
# ///
"""Posture check: watches you through the webcam and nags via notify-send.

Run: uv run posture.py
Keys (preview window must be focused): c = recalibrate, p = pause/resume, q = quit.
Log intervals still open at stop (bad posture, away, pause) end at the "stop" row.
"""
import csv
import json
import math
import os
import shutil
import signal
import statistics
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")  # mediapipe logs a warning per frame otherwise
CAMERA = 0
SLOUCH = 0.85    # head-to-shoulder distance below this fraction of your baseline = slouching
LEAN = 0.06      # head moved this far toward the screen, in frame widths = leaning in
GRACE = 20       # seconds of bad posture before the first nag
REPEAT = 120     # seconds between nags while it continues
AWAY_AFTER = 10  # seconds without a detected person = away
COUNTDOWN = 5    # calibration: seconds to sit straight before sampling starts
SAMPLE = 3       # calibration: seconds averaged into the profile
EVERY = 0.5      # seconds between pose detections
PROFILE = Path.home() / ".config/posture-check/profile.json"
LOG = Path.home() / ".local/share/posture-check/log.csv"
MODEL = Path(__file__).with_name("pose_landmarker_lite.task")
WIN = "posture-check"
PANEL = 165      # height in pixels of the stats strip under the video
GREEN, RED, YELLOW, WHITE, GREY = (90, 220, 90), (90, 90, 255), (0, 220, 255), (235, 235, 235), (170, 170, 170)  # BGR


def measure(lm, w, h):
    """Landmarks (.x/.y in 0-1) to three numbers; None if the shoulders collapse onto each other."""
    px = [(p.x * w, p.y * h) for p in lm]
    hx, hy = (sum(c) / 11 for c in zip(*px[:11]))  # face points averaged: a steadier head centre
    span = math.dist(px[11], px[12])
    if span < 20:
        return None
    return {
        "head_to_shoulder": ((px[11][1] + px[12][1]) / 2 - hy) / span,
        "head_x": hx / w,
        "facing": -1 if px[0][0] < (px[7][0] + px[8][0]) / 2 else 1,  # which way the nose points
    }


def typical(samples):
    """Median of each number over several measurements."""
    m = {k: statistics.median(s[k] for s in samples) for k in samples[0]}
    m["facing"] = -1 if m["facing"] < 0 else 1  # the median of +-1 can be 0
    return m


def scores(p, m):
    """(head-to-shoulder as a fraction of baseline, head shift toward the screen in frame widths)."""
    return m["head_to_shoulder"] / p["head_to_shoulder"], p["facing"] * (m["head_x"] - p["head_x"])


def judge(p, m):
    ratio, lean = scores(p, m)
    if ratio < SLOUCH:
        return "Slouching"
    if lean > LEAN:
        return "Leaning in"
    return None


def due(bad_since, last_nag, now):
    """First nag after GRACE seconds of bad posture, then one every REPEAT seconds."""
    if now - bad_since < GRACE:
        return False
    return last_nag is None or now - last_nag >= REPEAT


def log(event, detail=""):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "event", "detail"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), event, detail])


def set_problem(old, new):
    if old:
        log("bad_end", old)
    if new:
        log("bad_start", new)
    return new


def load_profile():
    try:
        p = json.loads(PROFILE.read_text())
        return p if {"head_to_shoulder", "head_x", "facing"} <= p.keys() else None
    except (OSError, ValueError, AttributeError):  # missing, unreadable or not a profile: calibrate again
        return None


def nag(problem):
    subprocess.run(["notify-send", "-a", "posture-check", "Posture", f"{problem}: sit up straight"], check=False)


def draw(frame, lm, status, color, stats):
    """The video with the skeleton on it, and a dark stats strip below. stats = (ratio, lean) or None."""
    import cv2
    h, w = frame.shape[:2]
    if lm:
        pts = [(int(p.x * w), int(p.y * h)) for p in lm]
        for p in pts[:13]:
            cv2.circle(frame, p, 4, GREEN, -1)
        cv2.line(frame, pts[11], pts[12], GREEN, 2)
    out = cv2.copyMakeBorder(frame, 0, PANEL, 0, 0, cv2.BORDER_CONSTANT, value=(35, 35, 35))

    def put(text, x, y, scale, col, thick=2):
        cv2.putText(out, text, (x, h + y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick, cv2.LINE_AA)

    put(status, 15, 45, 1.4, color, 3)
    ratio, lean = stats or (None, None)
    rows = [("Head height", ratio, ".2f", f"warn below {SLOUCH}", ratio is not None and ratio < SLOUCH),
            ("Lean in", lean, "+.2f", f"warn above {LEAN}", lean is not None and lean > LEAN)]
    for i, (name, value, fmt, limit, bad) in enumerate(rows):
        y = 90 + 35 * i
        put(name, 15, y, 1.0, WHITE)
        put("--" if value is None else format(value, fmt), 230, y, 1.0, RED if bad else WHITE)
        put(limit, 340, y, 0.7, GREY)
    put("c recalibrate    p pause    q quit", 15, 152, 0.7, GREY, 1)
    return out


def main():
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    if not shutil.which("notify-send"):
        raise SystemExit("notify-send not found (sudo dnf install libnotify)")
    if not MODEL.exists():
        raise SystemExit(f"model file missing: {MODEL}")
    cap = cv2.VideoCapture(CAMERA)
    if not cap.isOpened():
        raise SystemExit(f"cannot open camera {CAMERA}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=vision.RunningMode.VIDEO))
    cv2.namedWindow(WIN, cv2.WINDOW_GUI_NORMAL)  # resizable, without OpenCV's zoom/save toolbar
    cv2.resizeWindow(WIN, 400, 400 * (480 + PANEL) // 640)

    profile = load_profile()
    t0 = time.monotonic()
    calib = t0 if profile is None else None  # start time of a running calibration
    samples, recent = [], deque(maxlen=5)
    paused = away = False
    problem = bad_since = last_nag = None
    last_seen = last_detect = t0
    lm, stats = None, None
    log("start")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                raise SystemExit("camera read failed")
            now = time.monotonic()
            if (calib is not None or not paused) and now - last_detect >= EVERY:
                last_detect = now
                h, w = frame.shape[:2]
                res = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                    int(now * 1000))
                lm = res.pose_landmarks[0] if res.pose_landmarks else None
                m = measure(lm, w, h) if lm else None
                if m:
                    last_seen = now
                if calib is not None:
                    if m and now - calib >= COUNTDOWN:
                        samples.append(m)
                    if now - calib >= COUNTDOWN + SAMPLE:
                        if len(samples) >= 3:
                            profile = {**typical(samples), "created": datetime.now().isoformat(timespec="seconds")}
                            PROFILE.parent.mkdir(parents=True, exist_ok=True)
                            PROFILE.write_text(json.dumps(profile, indent=2))
                            log("calibrate")
                            calib, last_seen = None, now
                            recent.clear()
                        else:
                            calib, samples = now, []  # nobody seen: start over
                elif m is None:
                    if not away and now - last_seen >= AWAY_AFTER:
                        away = True
                        log("away")
                        problem = set_problem(problem, None)
                        recent.clear()
                else:
                    if away:
                        away = False
                        log("back")
                    recent.append(m)
                    if len(recent) >= 3:  # a median of one or two fresh samples is too noisy to judge
                        smooth = typical(recent)
                        ratio, lean = scores(profile, smooth)
                        stats = (ratio, lean)
                        new = judge(profile, smooth)
                        if new != problem:
                            problem = set_problem(problem, new)
                            bad_since, last_nag = now, None
                        if problem and due(bad_since, last_nag, now):
                            nag(problem)
                            last_nag = now

            if calib is not None:
                left = COUNTDOWN - (now - calib)
                status, color = (f"Sit straight: {math.ceil(left)}" if left > 0 else "Calibrating..."), YELLOW
            elif paused or away:
                status, color = "PAUSED" if paused else "AWAY", GREY
            elif problem:
                status, color = f"{problem}  {int(now - bad_since)}s", RED
            else:
                status, color = "OK", GREEN
            live = stats if calib is None and not paused and not away else None
            cv2.imshow(WIN, draw(frame, lm, status, color, live))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("p") and calib is None:
                paused = not paused
                log("pause" if paused else "resume")
                problem = set_problem(problem, None)
                recent.clear()
                lm, last_seen = None, now
            if key == ord("c"):
                calib, samples = now, []
                problem = set_problem(problem, None)
                recent.clear()
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a second Ctrl+C must not interrupt the teardown
        set_problem(problem, None)
        log("stop")  # the camera and window are freed when the process exits


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
