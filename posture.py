# /// script
# dependencies = ["mediapipe"]
# ///
"""Posture check: watches you through the webcam and nags via notify-send.

Run: uv run posture.py [--camera N]
Keys (preview window must be focused): c = recalibrate, p = pause/resume, s = snooze, m = mute sound,
n = hide notifications, q = quit.
Log intervals still open at stop (bad posture, away, pause) end at the "stop" row.
"""
import argparse
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
VERSION = "0.4.0"   # keep in step with CHANGELOG.md (tests/test_posture.py checks it)
CAMERA = 0
SLOUCH = 0.85       # head-to-shoulder distance below this fraction of your baseline = slouching
SLOUCH_EXIT = 0.90  # once slouching, the distance must rise above this to end it (stops flicker at the limit)
LEAN = 0.06         # head moved this far toward the screen, in frame widths = leaning in
LEAN_EXIT = 0.04    # once leaning in, the lean must fall below this to end it
MIN_VISIBLE = 0.3   # the nose and both shoulders must be at least this visible, or nobody is seen
GRACE = 20          # seconds of bad posture before the first nag
REPEAT = 120        # seconds between nags while it continues
AWAY_AFTER = 10     # seconds without a detected person = away
DOWN_DELAY = 2      # seconds bad posture must last before its sound plays
UP_DELAY = 0.5      # seconds good posture must last before the "recovered" sound plays
SNOOZE = 300        # seconds the "s" key pauses the app
BREAK_AFTER = 1800  # seconds of sitting before the first break reminder
BREAK_REPEAT = 300  # seconds between break reminders while you keep sitting
BREAK_AWAY = 60     # seconds away (after AWAY_AFTER) that count as a break
CAMERA_RETRY = 2    # seconds of failed camera reads before the camera is opened again
CAMERA_LOST = 30    # seconds of failed camera reads before the app stops
COUNTDOWN = 5       # calibration: seconds to sit straight before sampling starts
SAMPLE = 3          # calibration: seconds averaged into the profile
EVERY = 0.5         # seconds between pose detections
PROFILE = Path.home() / ".config/posture-check/profile.json"
LOG = Path.home() / ".local/share/posture-check/log.csv"
MODEL = Path(__file__).with_name("pose_landmarker_lite.task")
SOUND_DIR = Path(__file__).with_name("sounds")
ICON = Path(__file__).with_name("icon") / "posture-check.svg"
SOUNDS = {"down": "winding_down.wav", "up": "ratchet_up.wav", "nag": "four_clicks.wav"}
TIPS = {"Slouching": "Lift your chest and pull your shoulders back.",
        "Leaning in": "Move your head back, so your ears are over your shoulders."}
WIN = "posture-check"
PANEL = 190      # height in pixels of the stats strip under the video
GREEN, RED, YELLOW, WHITE, GREY = (90, 220, 90), (90, 90, 255), (0, 220, 255), (235, 235, 235), (170, 170, 170)  # BGR


def seen(p):
    """True if MediaPipe is sure about this landmark. Points off the frame or hidden get a low visibility."""
    v = getattr(p, "visibility", None)
    return v is None or v >= MIN_VISIBLE


def measure(lm, w, h):
    """Landmarks (.x/.y in 0-1) to three numbers; None if the nose or a shoulder is not seen or the shoulders collapse."""
    if not all(seen(lm[i]) for i in (0, 11, 12)):
        return None
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


def judge(p, m, prev=None):
    """The problem now, or None. prev is the problem a moment ago: it ends only past its EXIT limit (hysteresis)."""
    ratio, lean = scores(p, m)
    if ratio < (SLOUCH_EXIT if prev == "Slouching" else SLOUCH):
        return "Slouching"
    if lean > (LEAN_EXIT if prev == "Leaning in" else LEAN):
        return "Leaning in"
    return None


def due(bad_since, last_nag, now):
    """First nag after GRACE seconds of bad posture, then one every REPEAT seconds."""
    if now - bad_since < GRACE:
        return False
    return last_nag is None or now - last_nag >= REPEAT


def fmt_span(seconds):
    """40 s, 5 min, 1 h 05 min."""
    s = round(seconds)
    if s < 60:
        return f"{s} s"
    m = round(s / 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def nag_text(problem, seconds):
    return f"{problem} for {fmt_span(seconds)}. {TIPS.get(problem, 'Sit up straight.')}"


class Cues:
    """Decides which sound to play. A sound plays only after the new state has lasted DOWN_DELAY (bad) or UP_DELAY (good).
    "down": posture turned bad. "up": posture is good again, but only after "down" played."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.announced, self.bad, self.since = False, False, 0.0

    def update(self, problem, now):
        if bool(problem) != self.bad:
            self.bad, self.since = bool(problem), now
        if now - self.since < (DOWN_DELAY if self.bad else UP_DELAY) or self.bad == self.announced:
            return None
        self.announced = self.bad
        return "down" if self.bad else "up"


class Breaks:
    """Break reminders. The first one comes after BREAK_AFTER seconds of sitting, then one every BREAK_REPEAT.
    Being away for BREAK_AWAY seconds counts as a break and starts the count again."""

    def __init__(self, now):
        self.since = now  # when you sat down; None during a break
        self.last = self.away_at = None

    def update(self, away, now):
        """True when a reminder is due."""
        if away:
            if self.away_at is None:
                self.away_at = now
            if now - self.away_at >= BREAK_AWAY:
                self.since = self.last = None
            return False
        self.away_at = None
        if self.since is None:
            self.since = now
        if now - self.since < BREAK_AFTER or (self.last is not None and now - self.last < BREAK_REPEAT):
            return False
        self.last = now
        return True


class Camera:
    """A webcam that opens itself again after read errors, for example after the laptop was suspended."""

    def __init__(self, opener):
        self.opener = opener
        self.cap = opener()
        self.failing = self.retried = None  # when the reads began to fail, when the camera was last opened again

    def read(self, now):
        """A frame, or None if the read failed."""
        ok, frame = self.cap.read() if self.cap.isOpened() else (False, None)
        if ok:
            self.failing = self.retried = None
            return frame
        if self.failing is None:
            self.failing = self.retried = now
        elif now - self.retried >= CAMERA_RETRY:
            self.cap.release()
            self.cap, self.retried = self.opener(), now
        return None

    def lost_for(self, now):
        return 0 if self.failing is None else now - self.failing


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


def notify(title, body):
    """A desktop notification. The synchronous hint makes a new one replace the old one, so nags do not pile up."""
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "posture-check", "-i", str(ICON),
                        "-h", "string:x-canonical-private-synchronous:posture-check", title, body], check=False)


def die(message):
    """Stop with a message. The menu launcher has no terminal, so the message also goes to a notification."""
    notify("posture-check stopped", message)
    raise SystemExit(message)


def play(name):
    subprocess.Popen(["pw-play", str(SOUND_DIR / SOUNDS[name])])  # does not wait: the app keeps running


def draw(frame, lm, status, color, stats, off, sitting):
    """The video with the skeleton on it, and a dark stats strip below.
    stats = (ratio, lean) or None. off = names of the features that are switched off. sitting = seconds or None."""
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
    for i, name in enumerate(off):
        put(f"{name} off", 430, 26 + 24 * i, 0.6, YELLOW, 1)
    ratio, lean = stats or (None, None)
    rows = [("Head height", ratio, ".2f", f"warn below {SLOUCH}", ratio is not None and ratio < SLOUCH),
            ("Lean in", lean, "+.2f", f"warn above {LEAN}", lean is not None and lean > LEAN)]
    for i, (name, value, fmt, limit, bad) in enumerate(rows):
        y = 90 + 35 * i
        put(name, 15, y, 1.0, WHITE)
        put("--" if value is None else format(value, fmt), 230, y, 1.0, RED if bad else WHITE)
        put(limit, 340, y, 0.7, GREY)
    if sitting is not None:
        put(f"sitting {fmt_span(sitting)}", 15, 152, 0.7, GREY, 1)
    put("c recalibrate  p pause  s snooze  m sound  n notify  q quit", 15, 180, 0.6, GREY, 1)
    return out


def main(camera=CAMERA):
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    if not shutil.which("notify-send"):
        raise SystemExit("notify-send not found (sudo dnf install libnotify)")
    if not shutil.which("pw-play"):
        die("pw-play not found (sudo dnf install pipewire-utils)")
    missing = [f for f in SOUNDS.values() if not (SOUND_DIR / f).exists()]
    if missing:
        die(f"sound files missing in {SOUND_DIR}: {', '.join(missing)} (run: python3 sounds/synth.py)")
    if not MODEL.exists():
        die(f"model file missing: {MODEL}")

    def open_camera():
        cap = cv2.VideoCapture(camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    cam = Camera(open_camera)
    if not cam.cap.isOpened():
        die(f"cannot open camera {camera} (is another program using it? posture-check may already run)")
    landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=vision.RunningMode.VIDEO))
    cv2.namedWindow(WIN, cv2.WINDOW_GUI_NORMAL)  # resizable, without OpenCV's zoom/save toolbar
    cv2.resizeWindow(WIN, 400, 400 * (480 + PANEL) // 640)
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # a logout must still write the "stop" row

    profile = load_profile()
    t0 = time.monotonic()
    calib = t0 if profile is None else None  # start time of a running calibration
    samples, recent = [], deque(maxlen=5)
    paused = away = muted = hushed = False  # muted: no sound. hushed: no notifications
    resume_at = None  # when a snooze ends
    cues, breaks = Cues(), Breaks(t0)
    problem = bad_since = last_nag = None
    last_seen = last_detect = t0
    lm, stats = None, None

    def set_pause(on, now, snooze=False):
        nonlocal paused, resume_at, problem, lm, last_seen
        paused, resume_at = on, now + SNOOZE if on and snooze else None
        log(("snooze" if snooze else "pause") if on else "resume", str(SNOOZE) if on and snooze else "")
        problem = set_problem(problem, None)
        recent.clear()
        cues.reset()
        lm, last_seen = None, now

    log("start")
    try:
        while True:
            now = time.monotonic()
            frame = cam.read(now)
            if frame is None:
                if cam.lost_for(now) >= CAMERA_LOST:
                    die("camera read failed")
                if cv2.waitKey(50) & 0xFF == ord("q"):
                    break
                continue
            if resume_at is not None and now >= resume_at:
                set_pause(False, now)
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
                        cues.reset()
                else:
                    if away:
                        away = False
                        log("back")
                    recent.append(m)
                    if len(recent) >= 3:  # a median of one or two fresh samples is too noisy to judge
                        smooth = typical(recent)
                        ratio, lean = scores(profile, smooth)
                        stats = (ratio, lean)
                        new = judge(profile, smooth, problem)
                        if new != problem:
                            problem = set_problem(problem, new)
                            bad_since, last_nag = now, None
                        cue = cues.update(problem, now)
                        if cue and not muted:
                            play(cue)
                        if problem and due(bad_since, last_nag, now):
                            log("nag", problem)
                            if not hushed:
                                notify("Posture", nag_text(problem, now - bad_since))
                            if not muted:
                                play("nag")
                            last_nag = now

            if calib is None and not paused and breaks.update(away, now):
                log("break", str(round(now - breaks.since)))
                if not hushed:
                    notify("Time for a break", f"You sat for {fmt_span(now - breaks.since)}. Stand up and move for a minute.")
                if not muted:
                    play("nag")

            if calib is not None:
                left = COUNTDOWN - (now - calib)
                status, color = (f"Sit straight: {math.ceil(left)}" if left > 0 else "Calibrating..."), YELLOW
            elif resume_at is not None:
                left = max(0, math.ceil(resume_at - now))
                status, color = f"SNOOZED {left // 60}:{left % 60:02d}", GREY
            elif paused or away:
                status, color = "PAUSED" if paused else "AWAY", GREY
            elif problem:
                status, color = f"{problem}  {int(now - bad_since)}s", RED
            else:
                status, color = "OK", GREEN
            live = stats if calib is None and not paused and not away else None
            off = [name for name, flag in (("sound", muted), ("notifications", hushed)) if flag]
            sitting = None if breaks.since is None or away else now - breaks.since
            cv2.imshow(WIN, draw(frame, lm, status, color, live, off, sitting))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("p") and calib is None:
                set_pause(not paused, now)
            if key == ord("s") and calib is None and not paused:
                set_pause(True, now, snooze=True)
            if key == ord("m"):
                muted = not muted
            if key == ord("n"):
                hushed = not hushed
            if key == ord("c"):
                calib, samples = now, []
                problem = set_problem(problem, None)
                recent.clear()
                cues.reset()
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a second Ctrl+C or a SIGTERM must not interrupt the teardown
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        set_problem(problem, None)
        log("stop")  # the camera and window are freed when the process exits


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Watch your posture with a webcam.")
    ap.add_argument("--camera", type=int, default=CAMERA, help=f"camera number (default {CAMERA})")
    ap.add_argument("--version", action="version", version=f"posture-check {VERSION}")
    try:
        main(ap.parse_args().camera)
    except KeyboardInterrupt:
        pass
