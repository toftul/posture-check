# /// script
# dependencies = ["mediapipe"]
# ///
"""Posture check: watches you through the webcam and nags via notify-send.

Run: uv run posture.py [--camera N]
Keys (preview window must be focused): c = recalibrate, p = pause/resume, s = snooze, m = mute sound,
n = hide notifications, f = flip the picture, q = quit.
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
from dataclasses import dataclass
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
HISTORY = 1800      # seconds the timeline under the video shows
MIRROR = True       # show the picture as in a mirror (key f flips it)
PROFILE = Path.home() / ".config/posture-check/profile.json"
LOG = Path.home() / ".local/share/posture-check/log.csv"
MODEL = Path(__file__).with_name("pose_landmarker_lite.task")
SOUND_DIR = Path(__file__).with_name("sounds")
ICON = Path(__file__).with_name("icon") / "posture-check.svg"
SOUNDS = {"down": "winding_down.wav", "up": "ratchet_up.wav", "nag": "four_clicks.wav"}
TIPS = {"Slouching": "Lift your chest and pull your shoulders back.",
        "Leaning in": "Move your head back, so your ears are over your shoulders."}
WIN = "posture-check"
CAM_W, CAM_H, SIDE_W, BAR_H = 640, 480, 320, 160  # the window: the camera and the log side by side, the controls below both
FIXED_IN = 30    # an episode that ends this many seconds after its first nag counts as FIXED
CRT = True       # scanlines and a vignette on the picture
# BGR. The palette of the enkr1 design: #0a0a0a, #d0d0d0, #20c060, #ffd020, #ff2020. DIM is lighter than there, for contrast.
BG, FG, DIM, EDGE, FRAME = (10, 10, 10), (208, 208, 208), (128, 128, 128), (64, 64, 64), (26, 26, 26)
GREEN, RED, YELLOW, WHITE, GREY = (96, 192, 32), (32, 32, 255), (32, 208, 255), (235, 235, 235), (144, 144, 144)
LABELS = {"Slouching": "SLOUCH", "Leaning in": "LEAN IN"}  # how the log shows a problem
# key, label, width of the control buttons. A click on a button works like its key.
BUTTONS = (("c", "CALIBRATE", 122), ("p", "PAUSE", 100), ("s", "SNOOZE", 94), ("m", "SOUND", 86), ("n", "NOTIFY", 94),
           ("f", "FLIP", 72), ("q", "QUIT", 72))
KEY = {"nose": 0, "left shoulder": 11, "right shoulder": 12}  # the landmarks the numbers come from
T_AWAY, T_OK, T_DRIFT, T_NAG = 1, 2, 3, 4  # what the timeline records, from the least to the most serious


def seen(p):
    """True if MediaPipe is sure about this landmark. Points off the frame or hidden get a low visibility."""
    v = getattr(p, "visibility", None)
    return v is None or v >= MIN_VISIBLE


def measure(lm, w, h):
    """Landmarks (.x/.y in 0-1) to three numbers; None if the nose or a shoulder is not seen or the shoulders collapse."""
    if not all(seen(lm[i]) for i in KEY.values()):
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


def slouching(ratio, prev=None):
    """prev is the problem a moment ago: slouching ends only past SLOUCH_EXIT (hysteresis)."""
    return ratio < (SLOUCH_EXIT if prev == "Slouching" else SLOUCH)


def leaning(lean, prev=None):
    return lean > (LEAN_EXIT if prev == "Leaning in" else LEAN)


def judge(p, m, prev=None):
    """The problem now, or None. prev is the problem a moment ago."""
    ratio, lean = scores(p, m)
    if slouching(ratio, prev):
        return "Slouching"
    if leaning(lean, prev):
        return "Leaning in"
    return None


def hint_for(lm):
    """What to tell you when the frame cannot be measured: a short text, or None."""
    if lm is None:
        return "No person in view"
    names = [name for name, i in KEY.items() if not seen(lm[i])]
    return f"Not seen: {', '.join(names)}" if names else None


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


class Timeline:
    """What happened in the last `span` seconds, as `width` bins. A bin keeps the most serious state in it."""

    def __init__(self, span=HISTORY, width=SIDE_W + CAM_W - 32):
        self.width, self.step = width, span / width
        self.bins = {}  # bin number -> T_AWAY, T_OK, T_DRIFT or T_NAG

    def add(self, now, state):
        n = int(now / self.step)
        self.bins[n] = max(self.bins.get(n, 0), state)
        if len(self.bins) > self.width:
            self.bins = {k: v for k, v in self.bins.items() if k > n - self.width}

    def row(self, now):
        """One state for each bin, the oldest first. 0 = nothing recorded."""
        n = int(now / self.step)
        return [self.bins.get(k, 0) for k in range(n - self.width + 1, n + 1)]


def aligned(row):
    """Percent of the OK bins in a timeline row. Away and paused bins do not count. None if no bin counts."""
    ok, bad = row.count(T_OK), row.count(T_DRIFT) + row.count(T_NAG)
    return round(100 * ok / (ok + bad)) if ok + bad else None


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


ROWS = []  # (time, event, detail) of today: the rows of earlier runs and of this run. The log panel shows them.


def log(event, detail=""):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    now = datetime.now().replace(microsecond=0)
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "event", "detail"])
        w.writerow([now.isoformat(), event, detail])
    ROWS.append((now, event, detail))


def load_today(path=None, today=None):
    """The rows of the log file from today. A row that does not parse is skipped."""
    today, rows = today or datetime.now().date(), []
    try:
        with open(path or LOG, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    t = datetime.fromisoformat(r["timestamp"])
                    if t.date() == today:
                        rows.append((t, r["event"], r["detail"] or ""))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        pass
    return rows


def outcome(seconds):
    """How you answered the nag of an episode: FIXED within FIXED_IN seconds, SLOW before the next nag, IGNORED after."""
    late = seconds - GRACE
    return "FIXED" if late < FIXED_IN else "SLOW" if late < REPEAT else "IGNORED"


def log_entries(rows, now=None):
    """The log panel from the rows of one day: (items, stats).
    items are (time, label, seconds, outcome), the newest first. A bad posture episode of GRACE seconds or more is one item.
    Shorter dips are not shown. An away or pause interval is one item. stats: episodes, ignored, bad, avg, peak = (hour, count)."""
    items, episodes, open_ = [], [], {}  # open_: "bad", "away" or "pause" -> (since, label)

    def close(kind, end):
        since, label = open_.pop(kind)
        seconds = (end - since).total_seconds()
        if kind != "bad":
            items.append((since, label, seconds, None))
        elif seconds >= GRACE:
            episodes.append((since, seconds))
            items.append((since, LABELS.get(label, label.upper()), seconds, outcome(seconds)))

    for t, event, detail in rows:
        if event == "start":
            open_.clear()  # a run that ended without a "stop" row: its open intervals have no known end
            items.append((t, "START", None, None))
            continue
        if event in ("bad_start", "bad_end", "stop") and "bad" in open_:
            close("bad", t)
        if event in ("back", "stop") and "away" in open_:
            close("away", t)
        if event in ("resume", "stop") and "pause" in open_:
            close("pause", t)
        if event == "bad_start":
            open_["bad"] = (t, detail)
        elif event == "away":
            open_["away"] = (t, "AWAY")
        elif event in ("pause", "snooze"):
            open_["pause"] = (t, event.upper())
        elif event == "calibrate":
            items.append((t, "CALIBRATED", None, None))
        elif event == "break":
            items.append((t, "BREAK", float(detail) if detail.isdigit() else None, None))
    for kind in ("away", "pause"):  # still going on
        if kind in open_ and now:
            close(kind, now)
    items = [it for _, it in sorted(enumerate(items), key=lambda pair: (pair[1][0], pair[0]), reverse=True)]
    hours = {}
    for t, _ in episodes:
        hours[t.hour] = hours.get(t.hour, 0) + 1
    bad = sum(sec for _, sec in episodes)
    return items, {
        "episodes": len(episodes), "ignored": sum(outcome(sec) == "IGNORED" for _, sec in episodes), "bad": bad,
        "avg": bad / len(episodes) if episodes else None,
        "peak": max(hours.items(), key=lambda kv: (kv[1], -kv[0])) if hours else None}


def button_rects():
    """(key, label, x0, y0, x1, y1) of each control button in window pixels."""
    x, y = 16, CAM_H + 62
    rects = []
    for key, label, width in BUTTONS:
        rects.append((key, label, x, y, x + width, y + 30))
        x += width + 6
    return rects


def button_at(x, y):
    """The key of the button at this pixel, or None."""
    for key, _, x0, y0, x1, y1 in button_rects():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return key


def button_style(key, label, mode, off):
    """(label, kind) of a button. kind: plain, active, on, off or disabled. mode: run, calibrate, pause or snooze."""
    if key == "c":
        return label, "active" if mode == "calibrate" else "plain"
    if key == "p":
        return ("RESUME", "active") if mode in ("pause", "snooze") else (label, "disabled" if mode == "calibrate" else "plain")
    if key == "s":
        return label, "active" if mode == "snooze" else "disabled" if mode in ("pause", "calibrate") else "plain"
    if key in ("m", "n"):
        return label, "off" if {"m": "sound", "n": "notifications"}[key] in off else "on"
    return label, "plain"


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


@dataclass
class View:
    """What draw() shows."""
    status: str
    color: tuple
    mode: str = "run"       # run, calibrate, pause or snooze
    lm: object = None       # landmarks, or None
    level: str = None       # "drift" or "nag": the colour of the frame around the picture
    stats: tuple = None     # (head height as a fraction of baseline, lean) or None
    problem: str = None
    off: tuple = ()         # names of the features that are switched off
    sitting: float = None   # seconds
    row: list = None        # Timeline.row()
    aligned: int = None     # aligned(row)
    hint: str = None        # shown over the picture
    big: str = None         # a large number over the picture: the calibration countdown
    progress: float = None  # 0-1, the calibration sampling bar
    mirror: bool = False
    items: tuple = ()       # log_entries(): the log panel
    today: dict = None      # log_entries(): the numbers of the day
    live: tuple = None      # (problem, seconds): the episode that is going on and has had its first nag
    clock: str = ""         # the time shown on the picture


# (lo, hi, baseline, a, b, low_is_bad) for gauge(): the bar runs from lo to hi, the band between a and b keeps the old state
HEIGHT_SCALE = (0.6, 1.2, 1.0, SLOUCH, SLOUCH_EXIT, True)
LEAN_SCALE = (-0.10, 0.15, 0.0, LEAN_EXIT, LEAN, False)
FONT = 0  # the value of cv2.FONT_HERSHEY_SIMPLEX


def dim(color, k=0.4):
    return tuple(int(c * k) for c in color)


def put(img, text, x, y, scale=0.45, color=FG, thick=1, track=0, align="l"):
    """Text with its baseline at y. track = extra pixels between the letters, for wide upper case labels."""
    import cv2
    if track:
        widths = [cv2.getTextSize(ch, FONT, scale, thick)[0][0] + track for ch in text]
        total = sum(widths) - track
    else:
        total = cv2.getTextSize(text, FONT, scale, thick)[0][0]
    x -= total if align == "r" else total // 2 if align == "c" else 0
    if track:
        for ch, width in zip(text, widths):
            cv2.putText(img, ch, (x, y), FONT, scale, color, thick, cv2.LINE_AA)
            x += width
    else:
        cv2.putText(img, text, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def heading(img, text, x, y, width):
    """A red mark, the title in wide letters and a thin line under it."""
    import cv2
    cv2.rectangle(img, (x, y - 9), (x + 2, y + 1), RED, -1)
    put(img, text, x + 11, y, 0.4, FG, track=3)
    cv2.line(img, (x, y + 8), (x + width, y + 8), FRAME, 1)


def dashed(img, a, b, color, dash=5, gap=4):
    import cv2
    length = math.dist(a, b)
    for start in range(0, int(length), dash + gap):
        s, e = start / length, min(length, start + dash) / length
        cv2.line(img, (round(a[0] + (b[0] - a[0]) * s), round(a[1] + (b[1] - a[1]) * s)),
                 (round(a[0] + (b[0] - a[0]) * e), round(a[1] + (b[1] - a[1]) * e)), color, 1, cv2.LINE_AA)


def crt(img):
    """Scanlines and a vignette on the picture."""
    import numpy as np
    global _crt
    if _crt is None or _crt.shape[:2] != img.shape[:2]:
        h, w = img.shape[:2]
        y, x = np.ogrid[:h, :w]
        edge = np.clip((np.hypot((x - w / 2) / (w / 2), (y - h / 2) / (h / 2)) / 1.414 - 0.45) / 0.55, 0, 1)
        _crt = ((1 - 0.55 * edge) * np.where(y % 3 == 2, 0.8, 1.0))[..., None].astype(np.float32)
    return (img * _crt).astype(np.uint8)


_crt = None


def figure(img, lm, color, mirror):
    """A line for the shoulders and one dot for the head, as the numbers see you. A dashed line joins them."""
    import cv2
    if not all(seen(lm[i]) for i in KEY.values()):
        return

    def point(x, y):  # the picture is the top left part of the window
        return round((1 - x if mirror else x) * CAM_W), round(y * CAM_H)

    left, right = point(lm[11].x, lm[11].y), point(lm[12].x, lm[12].y)
    head = point(*(sum(c) / 11 for c in zip(*[(q.x, q.y) for q in lm[:11]])))  # the same head centre as measure()
    dashed(img, head, ((left[0] + right[0]) // 2, (left[1] + right[1]) // 2), GREY)
    cv2.line(img, left, right, color, 3, cv2.LINE_AA)
    cv2.circle(img, head, 8, color, -1, cv2.LINE_AA)


def gauge(img, x, y, w, value, scale):
    """A bar for one number: the bad zone, the band where the old state stays, the good zone.
    A thin line marks your baseline and a white mark the value."""
    import cv2
    lo, hi, base, a, b, low_is_bad = scale

    def px(v):
        return x + round((min(max(v, lo), hi) - lo) / (hi - lo) * w)

    left, right = (RED, GREEN) if low_is_bad else (GREEN, RED)
    for z0, z1, col in ((lo, a, left), (a, b, YELLOW), (b, hi, right)):
        cv2.rectangle(img, (px(z0), y), (px(z1), y + 14), dim(col), -1)
    cv2.line(img, (px(base), y), (px(base), y + 14), GREY, 1)
    if value is not None:
        cv2.line(img, (px(value), y - 4), (px(value), y + 18), WHITE, 3)


def camera(img, v, frame):
    """Region A: the picture with the figure, the frame, the badge, the clock and the hints."""
    import cv2
    if v.mirror:
        frame = cv2.flip(frame, 1)
    if CRT:
        frame = crt(frame)
    img[:CAM_H, :CAM_W] = frame
    if v.lm:
        figure(img, v.lm, v.color, v.mirror)
    if v.hint:
        cv2.rectangle(img, (0, CAM_H - 40), (CAM_W, CAM_H), BG, -1)
        put(img, v.hint.upper(), 16, CAM_H - 14, 0.5, YELLOW, 1, track=2)
    if v.big:
        tw, th = cv2.getTextSize(v.big, FONT, 6, 14)[0]
        for thick, col in ((14, BG), (6, WHITE)):  # a dark outline keeps the number readable on any picture
            put(img, v.big, (CAM_W - tw) // 2, (CAM_H + th) // 2, 6, col, thick)
    edge = {"drift": (YELLOW, 2), "nag": (RED, 6)}.get(v.level) or {"run": (GREEN, 2), "calibrate": (YELLOW, 2)}.get(v.mode, (EDGE, 2))
    for x0, y0, x1, y1 in ((0, 0, CAM_W, edge[1]), (0, CAM_H - edge[1], CAM_W, CAM_H), (0, 0, edge[1], CAM_H), (CAM_W - edge[1], 0, CAM_W, CAM_H)):
        cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), edge[0], -1)  # the frame, inside the picture
    badge, col = {"run": ("LIVE", RED), "calibrate": ("CALIBRATING", YELLOW), "pause": ("PAUSED", GREY), "snooze": ("SNOOZED", GREY)}[v.mode]
    cv2.circle(img, (22, 24), 5, col, -1, cv2.LINE_AA)
    put(img, badge, 36, 29, 0.5, BG, 4, track=2)  # a dark outline, then the letters
    put(img, badge, 36, 29, 0.5, col, 1, track=2)
    put(img, v.clock, CAM_W - 14, CAM_H - 14, 0.45, BG, 4, align="r")
    put(img, v.clock, CAM_W - 14, CAM_H - 14, 0.45, FG, 1, align="r")


def side(img, v):
    """Region B: the numbers of the day and the log."""
    import cv2
    x, w = CAM_W + 16, SIDE_W - 32
    cv2.line(img, (CAM_W, 0), (CAM_W, CAM_H), FRAME, 1)
    heading(img, "TODAY", x, 30, w)
    t = v.today or {"episodes": 0, "ignored": 0, "bad": 0, "avg": None, "peak": None}
    rows = (("EPISODES", f"{t['episodes']}" + (f" ({t['ignored']} ignored)" if t["ignored"] else "")),
            ("BAD TIME", fmt_span(t["bad"]) if t["episodes"] else "-"),
            ("AVG LENGTH", fmt_span(t["avg"]) if t["avg"] is not None else "-"),
            ("PEAK HOUR", f"{t['peak'][0]:02d}:00 ({t['peak'][1]})" if t["peak"] else "-"))
    for i, (label, value) in enumerate(rows):
        put(img, label, x, 58 + 22 * i, 0.4, DIM, track=1)
        put(img, value, x + w, 58 + 22 * i, 0.45, FG, align="r")
    heading(img, "LOG", x, 170, w)
    shown = ([(None, LABELS.get(v.live[0], v.live[0].upper()), v.live[1], None)] if v.live else []) + list(v.items)
    if not shown:
        put(img, "- no events yet -", x, 204, 0.42, DIM)
    for i, (when, label, seconds, result) in enumerate(shown[:(CAM_H - 190) // 24]):
        y = 204 + 24 * i
        put(img, "NOW" if when is None else f"{when:%H:%M}", x, y, 0.42, RED if when is None else DIM)
        put(img, label, x + 48, y, 0.42, RED if when is None else FG)
        if seconds is not None:
            put(img, fmt_span(seconds), x + 205, y, 0.42, DIM, align="r")
        if result:
            put(img, result, x + 218, y, 0.42, {"FIXED": GREEN, "SLOW": YELLOW, "IGNORED": RED}[result])
        cv2.line(img, (x, y + 7), (x + w, y + 7), FRAME, 1)


def bar(img, v):
    """Region C: the status, the bars of the two numbers, the buttons and the timeline."""
    import cv2
    import numpy as np
    y0 = CAM_H
    cv2.line(img, (0, y0), (CAM_W + SIDE_W, y0), EDGE, 1)
    put(img, v.status.upper(), 16, y0 + 42, 0.9, v.color, 2, track=1)
    ratio, lean = v.stats or (None, None)
    for x, name, value, fmt, bad, scale in (
            (336, "HEAD HEIGHT", ratio, ".2f", ratio is not None and slouching(ratio, v.problem), HEIGHT_SCALE),
            (654, "LEAN IN", lean, "+.2f", lean is not None and leaning(lean, v.problem), LEAN_SCALE)):
        put(img, name, x, y0 + 22, 0.4, DIM, track=2)
        put(img, "--" if value is None else format(value, fmt), x + 290, y0 + 22, 0.5, RED if bad else FG, align="r")
        gauge(img, x, y0 + 30, 290, value, scale)

    for key, label, x0, y1, x1, y2 in button_rects():
        label, kind = button_style(key, label, v.mode, v.off)
        border, text = {"plain": (EDGE, FG), "active": (YELLOW, YELLOW), "on": (GREEN, FG), "off": (EDGE, DIM), "disabled": (FRAME, EDGE)}[kind]
        cv2.rectangle(img, (x0, y1), (x1, y2), border, 1)
        put(img, label, x0 + 10, y1 + 20, 0.4, text, track=2)
        put(img, key, x1 - 9, y1 + 20, 0.4, EDGE if kind == "disabled" else DIM, align="r")
        if kind == "off":
            cv2.line(img, (x0 + 8, y1 + 15), (x0 + 8 + 9 * len(label), y1 + 15), DIM, 1)
    if v.sitting is not None:
        put(img, f"SITTING {fmt_span(v.sitting).upper()}", CAM_W + SIDE_W - 16, y0 + 82, 0.42, DIM, track=1, align="r")

    if v.progress is not None:
        put(img, "HOLD STILL", 16, y0 + 112, 0.4, DIM, track=2)
        cv2.rectangle(img, (16, y0 + 120), (944, y0 + 146), FRAME, -1)
        cv2.rectangle(img, (16, y0 + 120), (16 + round(928 * v.progress), y0 + 146), YELLOW, -1)
    elif v.row:
        put(img, f"LAST {HISTORY // 60} MIN", 16, y0 + 112, 0.4, DIM, track=2)
        if v.aligned is not None:
            put(img, f"ALIGNED {v.aligned}%", 140, y0 + 112, 0.4, FG, track=2)
        colors = np.array([FRAME, EDGE, GREEN, YELLOW, RED], np.uint8)  # indexed by T_*, 0 = nothing recorded
        img[y0 + 120:y0 + 146, 16:16 + len(v.row)] = colors[np.array(v.row)][None]
        for age in range(600, HISTORY, 600):  # a tick for every 10 minutes
            x = 16 + len(v.row) - round(age * len(v.row) / HISTORY)
            cv2.line(img, (x, y0 + 146), (x, y0 + 152), DIM, 1)


_panels = (None, None)  # (what the panels show, their image)


def panels(v):
    """The log and the controls (B and C) as one image. They change about once a second, so the last image is kept
    and drawn again only when something it shows has changed."""
    import numpy as np
    global _panels
    key = (v.status, v.color, v.mode, v.problem, tuple(v.off), v.aligned, v.progress, v.today, tuple(v.items),
           None if v.stats is None else (round(v.stats[0], 3), round(v.stats[1], 3)),
           None if v.sitting is None else int(v.sitting), None if v.live is None else (v.live[0], int(v.live[1])),
           None if v.row is None else tuple(v.row))
    if _panels[0] != key:
        img = np.full((CAM_H + BAR_H, CAM_W + SIDE_W, 3), BG, np.uint8)
        side(img, v)
        bar(img, v)
        _panels = (key, img)
    return _panels[1]


def draw(frame, v):
    """The whole window: the camera (A) and the log (B) side by side, the controls (C) under both."""
    img = panels(v).copy()
    camera(img, v, frame)
    return img


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
    cv2.resizeWindow(WIN, CAM_W + SIDE_W, CAM_H + BAR_H)
    clicks = []  # keys of the buttons that were clicked

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and button_at(x, y):
            clicks.append(ord(button_at(x, y)))

    cv2.setMouseCallback(WIN, on_mouse)
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
    lm, stats, hint = None, None, None
    timeline, mirror = Timeline(), MIRROR

    def set_pause(on, now, snooze=False):
        nonlocal paused, resume_at, problem, lm, last_seen
        paused, resume_at = on, now + SNOOZE if on and snooze else None
        log(("snooze" if snooze else "pause") if on else "resume", str(SNOOZE) if on and snooze else "")
        problem = set_problem(problem, None)
        recent.clear()
        cues.reset()
        lm, last_seen = None, now

    ROWS[:] = load_today()
    log("start")
    shown_for, items, today = None, (), None
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
            if frame.shape[:2] != (CAM_H, CAM_W):
                frame = cv2.resize(frame, (CAM_W, CAM_H))
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
                hint = None if m else hint_for(lm)
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

            level = ("nag" if last_nag is not None else "drift") if problem else None  # the border of the video
            state = big = progress = None  # state: what the timeline records
            if calib is not None:
                left = COUNTDOWN - (now - calib)
                status, color = (f"Sit straight: {math.ceil(left)}" if left > 0 else "Calibrating..."), YELLOW
                big, progress = (str(math.ceil(left)), None) if left > 0 else (None, min(1.0, -left / SAMPLE))
            elif resume_at is not None:
                left = max(0, math.ceil(resume_at - now))
                status, color, state = f"SNOOZED {left // 60}:{left % 60:02d}", GREY, T_AWAY
            elif paused or away:
                status, color, state = "PAUSED" if paused else "AWAY", GREY, T_AWAY
            elif problem:  # amber until the first nag, then red
                status, color = f"{problem}  {int(now - bad_since)}s", RED if level == "nag" else YELLOW
                state = T_NAG if level == "nag" else T_DRIFT
            else:
                status, color, state = "OK", GREEN, T_OK
            if state:
                timeline.add(now, state)
            row = timeline.row(now)
            wall = datetime.now()
            if shown_for != (len(ROWS), int(now)):  # the log panel changes with a new row and with each second
                shown_for = (len(ROWS), int(now))
                items, today = log_entries([r for r in ROWS if r[0].date() == wall.date()], wall)
            mode = "calibrate" if calib is not None else "snooze" if resume_at is not None else "pause" if paused else "run"
            cv2.imshow(WIN, draw(frame, View(
                status, color, mode=mode, lm=lm, level=level, problem=problem, row=row, aligned=aligned(row), mirror=mirror,
                stats=stats if mode == "run" and not away else None,
                off=[name for name, flag in (("sound", muted), ("notifications", hushed)) if flag],
                sitting=None if breaks.since is None or away else now - breaks.since,
                hint=None if paused else hint, big=big, progress=progress, items=items, today=today,
                live=(problem, now - bad_since) if level == "nag" else None, clock=f"{wall:%Y-%m-%d %H:%M:%S}")))
            key = cv2.waitKey(1) & 0xFF
            if clicks:
                key = clicks.pop(0)  # a click on a button works like its key
            if key == ord("q") or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("p") and calib is None:
                set_pause(not paused, now)
            if key == ord("s") and calib is None and (resume_at is not None or not paused):
                set_pause(resume_at is None, now, snooze=True)  # a second "s" ends the snooze
            if key == ord("m"):
                muted = not muted
            if key == ord("n"):
                hushed = not hushed
            if key == ord("f"):
                mirror = not mirror
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
