"""Checks for the posture logic. Run from anywhere: python3 tests/test_posture.py (needs no install)."""
import random
import re
import sys
import tempfile
from datetime import datetime
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import posture
from posture import (BAR_H, BREAK_AFTER, BREAK_AWAY, BREAK_REPEAT, BUTTONS, CAM_H, CAM_W, CAMERA_RETRY, CRT, DIM, DOWN_DELAY,
                     EDGE, FIXED_IN, GRACE, GREEN, LEAN, LEAN_EXIT, MIN_VISIBLE, REPEAT, RED, SIDE_W, SLOUCH, SLOUCH_EXIT,
                     T_AWAY, T_DRIFT, T_NAG, T_OK, UP_DELAY, VERSION, YELLOW, BG, Breaks, Camera, Cues, Timeline, View,
                     aligned, button_at, button_rects, button_style, draw, due, fmt_span, hint_for, judge, leaning,
                     load_today, log_entries, measure, nag_text, outcome, slouching, typical)

P = namedtuple("P", "x y")
base = {"head_to_shoulder": 0.5, "head_x": 0.5, "facing": -1}  # facing left: the screen is on the left


def at(h=0.5, x=0.5):
    return {"head_to_shoulder": h, "head_x": x, "facing": -1}


assert judge(base, at()) is None
assert judge(base, at(h=0.5 * SLOUCH + 0.01)) is None
assert judge(base, at(h=0.5 * SLOUCH - 0.01)) == "Slouching"
assert judge(base, at(x=0.5 - LEAN - 0.01)) == "Leaning in"  # moved left = toward the screen
assert judge(base, at(x=0.5 - LEAN + 0.01)) is None
assert judge(base, at(x=0.8)) is None  # leaning back is not flagged

assert not due(0, None, GRACE - 1)
assert due(0, None, GRACE)
assert not due(0, GRACE, GRACE + REPEAT - 1)
assert due(0, GRACE, GRACE + REPEAT)

# measure(): 100x100 frame, face points at (50, 20), shoulders at (40, 60) and (60, 60), span 20
lm = [P(0.5, 0.2)] * 11 + [P(0.4, 0.6), P(0.6, 0.6)]
m = measure(lm, 100, 100)
assert m["head_to_shoulder"] == 2.0 and m["head_x"] == 0.5
assert measure([P(0.5, 0.2)] * 11 + [P(0.5, 0.6)] * 2, 100, 100) is None  # shoulders on top of each other
assert measure([P(0.3, 0.2)] + [P(0.5, 0.2)] * 10 + [P(0.4, 0.6), P(0.6, 0.6)], 100, 100)["facing"] == -1  # nose left of ears

assert typical([at(h=0.4), at(h=0.5), at(h=0.9)])["head_to_shoulder"] == 0.5  # median ignores the outlier
assert typical([{"facing": 1}, {"facing": -1}])["facing"] == 1  # a tie must not give 0
# Cues: a sound plays only after the new state has lasted DOWN_DELAY (bad) or UP_DELAY (good) seconds
c = Cues()
assert c.update(None, 100) is None  # good at the start: silent
assert c.update("Slouching", 101) is None  # turns bad
assert c.update("Slouching", 101 + DOWN_DELAY - 0.1) is None
assert c.update("Slouching", 101 + DOWN_DELAY) == "down"
assert c.update("Slouching", 130) is None  # only once
assert c.update("Leaning in", 131) is None  # another kind of bad: no new sound
assert c.update(None, 140) is None  # turns good
assert c.update("Leaning in", 141) is None  # a flicker back to bad: no "up" ...
assert c.update("Leaning in", 150) is None  # ... and no second "down"
assert c.update(None, 160) is None
assert c.update(None, 160 + UP_DELAY - 0.1) is None
assert c.update(None, 160 + UP_DELAY) == "up"
assert c.update(None, 200) is None  # only once
c = Cues()  # a dip shorter than DOWN_DELAY makes no sound at all, not even "up"
c.update("Slouching", 0)
c.update(None, 1)
assert c.update(None, 10) is None
c = Cues()  # reset forgets that "down" played
c.update("Slouching", 0)
assert c.update("Slouching", DOWN_DELAY) == "down"
c.reset()
assert c.update(None, 50) is None and c.update(None, 60) is None

# measure(): a landmark that MediaPipe is not sure about means nobody is seen
V = namedtuple("V", "x y visibility")


def seen_lm(nose=1.0, left=1.0, right=1.0, ears=1.0):
    pts = [V(0.5, 0.2, 1.0)] * 33
    pts[0], pts[7], pts[8], pts[11], pts[12] = V(0.5, 0.2, nose), V(0.45, 0.2, ears), V(0.55, 0.2, ears), V(0.4, 0.6, left), V(0.6, 0.6, right)
    return pts


assert measure(seen_lm(), 100, 100) is not None
assert measure(seen_lm(nose=MIN_VISIBLE - 0.01), 100, 100) is None
assert measure(seen_lm(left=MIN_VISIBLE - 0.01), 100, 100) is None  # a shoulder off the frame
assert measure(seen_lm(right=MIN_VISIBLE - 0.01), 100, 100) is None
assert measure(seen_lm(ears=0.0), 100, 100) is not None  # at 45 degrees one ear is always hidden: not needed

# judge(): hysteresis. A problem ends only past its EXIT limit, so a number that hovers at the limit does not flicker
mid_slouch, mid_lean = (SLOUCH + SLOUCH_EXIT) / 2, (LEAN + LEAN_EXIT) / 2
assert judge(base, at(h=0.5 * mid_slouch)) is None  # in the band, but not slouching before
assert judge(base, at(h=0.5 * mid_slouch), "Slouching") == "Slouching"  # in the band, was slouching: still is
assert judge(base, at(h=0.5 * (SLOUCH_EXIT + 0.01)), "Slouching") is None  # clearly recovered
assert judge(base, at(h=0.5 * mid_slouch), "Leaning in") is None  # another problem's memory does not count
assert judge(base, at(x=0.5 - mid_lean)) is None
assert judge(base, at(x=0.5 - mid_lean), "Leaning in") == "Leaning in"
assert judge(base, at(x=0.5 - LEAN_EXIT + 0.01), "Leaning in") is None
assert judge(base, at(h=0.5 * (SLOUCH_EXIT + 0.01), x=0.5 - LEAN - 0.01), "Slouching") == "Leaning in"  # swaps to the other one
assert LEAN_EXIT < LEAN and SLOUCH < SLOUCH_EXIT < 1


def flips(use_memory):
    """How often the problem starts or ends for a number that hovers around the limit."""
    rng, problem, count = random.Random(1), None, 0
    for _ in range(500):
        new = judge(base, at(h=0.5 * rng.uniform(SLOUCH - 0.03, SLOUCH + 0.03)), problem if use_memory else None)
        count += new != problem
        problem = new
    return count


assert flips(False) > 100 and flips(True) < 5  # without hysteresis the problem flickers; with it, it flips once

# fmt_span, nag_text
assert [fmt_span(s) for s in (0, 40, 59.6, 60, 125, 3570, 3900)] == ["0 s", "40 s", "1 min", "1 min", "2 min", "1 h 00 min", "1 h 05 min"]
assert nag_text("Slouching", 20).startswith("Slouching for 20 s. ")
assert nag_text("Leaning in", 120).startswith("Leaning in for 2 min. ") and nag_text("Unknown", 5).endswith("Sit up straight.")

# Breaks: a reminder after BREAK_AFTER of sitting, then every BREAK_REPEAT
b = Breaks(0)
assert not b.update(False, BREAK_AFTER - 1)
assert b.update(False, BREAK_AFTER)
assert not b.update(False, BREAK_AFTER + 1)
assert not b.update(False, BREAK_AFTER + BREAK_REPEAT - 1)
assert b.update(False, BREAK_AFTER + BREAK_REPEAT)
b = Breaks(0)  # a short trip is not a break
assert not b.update(True, 100) and not b.update(True, 100 + BREAK_AWAY - 1)
assert not b.update(False, 100 + BREAK_AWAY)
assert b.update(False, BREAK_AFTER)
b = Breaks(0)  # a trip of BREAK_AWAY or more is a break: the count starts again when you sit down
b.update(True, 1000)
b.update(True, 1000 + BREAK_AWAY)
assert b.since is None
sat = 1000 + BREAK_AWAY + 10
assert not b.update(False, sat) and b.since == sat
assert not b.update(False, sat + BREAK_AFTER - 1)
assert b.update(False, sat + BREAK_AFTER)
assert not b.update(True, sat + BREAK_AFTER + 1)  # never a reminder while away


# Camera: opens again after failed reads
class Fake:
    def __init__(self, good):
        self.good, self.released = good, False

    def isOpened(self):
        return True

    def read(self):
        return (True, "frame") if self.good else (False, None)

    def release(self):
        self.released = True


made = []


def opener():
    made.append(Fake(good=bool(made)))  # the first camera is dead, the second one works
    return made[-1]


cam = Camera(opener)
assert cam.read(0) is None and cam.lost_for(1) == 1
assert cam.read(CAMERA_RETRY - 1) is None and len(made) == 1  # too early to open it again
assert cam.read(CAMERA_RETRY) is None and len(made) == 2 and made[0].released
assert cam.read(CAMERA_RETRY + 1) == "frame" and cam.lost_for(CAMERA_RETRY + 9) == 0
# slouching() and leaning() are what judge() and the window use, so both always agree
assert slouching(SLOUCH - 0.01) and not slouching(SLOUCH + 0.01)
assert not slouching(mid_slouch) and slouching(mid_slouch, "Slouching") and not slouching(mid_slouch, "Leaning in")
assert leaning(LEAN + 0.01) and not leaning(mid_lean) and leaning(mid_lean, "Leaning in")

# hint_for(): why a frame could not be measured
assert hint_for(None) == "No person in view"
assert hint_for(seen_lm()) is None
assert hint_for(seen_lm(nose=0.0)) == "Not seen: nose"
assert hint_for(seen_lm(left=0.0, right=0.0)) == "Not seen: left shoulder, right shoulder"
assert hint_for(seen_lm(ears=0.0)) is None  # an ear is not needed

# Timeline: bins of 10 s. A bin keeps the most serious state in it. Old bins fall out.
tl = Timeline(span=100, width=10)
assert tl.row(5) == [0] * 10
tl.add(5, T_OK)
tl.add(7, T_NAG)
tl.add(8, T_OK)
assert tl.row(9) == [0] * 9 + [T_NAG]
tl.add(15, T_DRIFT)
assert tl.row(19) == [0] * 8 + [T_NAG, T_DRIFT]
assert tl.row(105) == [T_DRIFT] + [0] * 9  # the first bin is older than 100 s
assert tl.row(110) == [0] * 10
for n in range(30):
    tl.add(10 * n, T_OK)
assert len(tl.bins) <= 10
assert len(Timeline().row(5000)) == CAM_W + SIDE_W - 32 and T_AWAY < T_OK < T_DRIFT < T_NAG

# aligned(): the share of OK bins. Away and empty bins do not count.
assert aligned([0, T_AWAY, T_OK, T_OK, T_OK, T_DRIFT]) == 75
assert aligned([T_NAG]) == 0 and aligned([T_OK, T_OK]) == 100
assert aligned([]) is None and aligned([0, T_AWAY]) is None

# outcome(): how you answered the nag
assert outcome(GRACE) == "FIXED" and outcome(GRACE + FIXED_IN - 1) == "FIXED"
assert outcome(GRACE + FIXED_IN) == "SLOW" and outcome(GRACE + REPEAT - 1) == "SLOW"
assert outcome(GRACE + REPEAT) == "IGNORED"


# log_entries(): the log panel and the numbers of the day
def tm(minute, second=0):
    return datetime(2026, 1, 1, 10, minute, second)


items, stats = log_entries([
    (tm(0), "start", ""), (tm(0, 8), "calibrate", ""),
    (tm(1), "bad_start", "Slouching"), (tm(1, 20), "nag", "Slouching"), (tm(1, 40), "bad_end", "Slouching"),       # 40 s: FIXED
    (tm(5), "bad_start", "Slouching"), (tm(5, 19), "bad_end", "Slouching"),                                       # a dip: not shown
    (tm(10), "bad_start", "Slouching"), (tm(13, 10), "bad_end", "Slouching"),                                     # 190 s: IGNORED
    (tm(20), "bad_start", "Leaning in"), (tm(21, 15), "bad_end", "Leaning in"),                                   # 75 s: SLOW
    (tm(30), "break", "1800"), (tm(31), "away", ""), (tm(39), "back", ""),
    (tm(40), "snooze", "300"), (tm(45), "resume", ""), (tm(50), "pause", ""),                                     # pause: still going on
    (tm(55), "bad_start", "Slouching"), (tm(55, 20), "nag", "Slouching")], tm(58))                                # an episode in progress
assert [(label, seconds, result) for _, label, seconds, result in items] == [
    ("PAUSE", 480, None), ("SNOOZE", 300, None), ("AWAY", 480, None), ("BREAK", 1800, None), ("LEAN IN", 75, "SLOW"),
    ("SLOUCH", 190, "IGNORED"), ("SLOUCH", 40, "FIXED"), ("CALIBRATED", None, None), ("START", None, None)]
assert items[0][0] == tm(50) and items[-1][0] == tm(0)
assert stats == {"episodes": 3, "ignored": 1, "bad": 305, "avg": 305 / 3, "peak": (10, 3)}

assert log_entries([]) == ([], {"episodes": 0, "ignored": 0, "bad": 0, "avg": None, "peak": None})
items, _ = log_entries([(tm(0), "bad_start", "Slouching"), (tm(0, 30), "bad_start", "Leaning in"), (tm(1), "stop", "")])
assert [(label, seconds) for _, label, seconds, _ in items] == [("LEAN IN", 30), ("SLOUCH", 30)]  # a new problem ends the old one
items, _ = log_entries([(tm(0), "bad_start", "Slouching"), (tm(30), "away", ""), (tm(40), "start", ""), (tm(41), "stop", "")])
assert [label for _, label, _, _ in items] == ["START"]  # a run without a stop row: its open intervals are dropped
_, stats = log_entries([(tm(0), "bad_start", "Slouching"), (tm(1), "bad_end", "Slouching")])
assert stats["episodes"] == 1
_, stats = log_entries([(datetime(2026, 1, 1, h), "bad_start", "Slouching") if i % 2 == 0 else (datetime(2026, 1, 1, h, 5), "bad_end", "Slouching")
                        for i, h in enumerate((9, 9, 14, 14))])
assert stats["peak"] == (9, 1)  # two hours with one episode each: the earlier one

# load_today(): the rows of today from the file. log() writes a row and remembers it.
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "log.csv"
    path.write_text("timestamp,event,detail\n2025-12-31T23:59:59,stop,\n2026-01-01T09:00:00,start,\nnot a time,start,\n"
                    "2026-01-01T09:05:00,stop\n2026-01-01T09:06:00,bad_start,Slouching\n")
    assert [(e, d) for _, e, d in load_today(path, today=datetime(2026, 1, 1).date())] == [("start", ""), ("stop", ""), ("bad_start", "Slouching")]
    assert load_today(Path(tmp) / "missing.csv") == []  # yesterday, a bad time and a missing file are skipped. A missing detail is empty.
    old_log, old_rows = posture.LOG, list(posture.ROWS)
    posture.LOG = Path(tmp) / "new" / "log.csv"
    posture.ROWS.clear()
    posture.log("nag", "Slouching")
    assert posture.LOG.read_text().splitlines()[0] == "timestamp,event,detail" and posture.LOG.read_text().endswith(",nag,Slouching\n")
    assert [(e, d) for _, e, d in posture.ROWS] == [("nag", "Slouching")]
    posture.LOG, posture.ROWS[:] = old_log, old_rows

# buttons: the layout is inside the controls, the buttons do not touch, a click on the middle of a button gives its key
rects = button_rects()
assert [r[0] for r in rects] == [b[0] for b in BUTTONS] == list("cpsmnfq")
assert all(y0 >= CAM_H and x1 <= CAM_W + SIDE_W and y1 <= CAM_H + BAR_H for _, _, x0, y0, x1, y1 in rects)
assert all(a[4] < b[2] for a, b in zip(rects, rects[1:]))
assert all(button_at((x0 + x1) // 2, (y0 + y1) // 2) == key for key, _, x0, y0, x1, y1 in rects)
assert all(button_at(x, y) == key for key, _, x0, y0, x1, y1 in rects for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)))  # the corners count
assert all(button_at(x, y) is None for _, _, x0, y0, x1, y1 in rects for x, y in ((x0 - 1, y0), (x1 + 1, y0), (x0, y0 - 1), (x1, y1 + 1)))
assert button_at(5, 5) is None and button_at(CAM_W + 100, 100) is None and button_at(rects[0][2] - 1, rects[0][3]) is None
assert button_at(rects[1][4] + 3, rects[1][3] + 3) is None  # the gap between two buttons
assert button_style("p", "PAUSE", "run", []) == ("PAUSE", "plain") and button_style("p", "PAUSE", "pause", []) == ("RESUME", "active")
assert button_style("p", "PAUSE", "snooze", [])[0] == "RESUME" and button_style("p", "PAUSE", "calibrate", [])[1] == "disabled"
assert button_style("s", "SNOOZE", "run", [])[1] == "plain" and button_style("s", "SNOOZE", "snooze", [])[1] == "active"
assert button_style("s", "SNOOZE", "pause", [])[1] == "disabled" and button_style("c", "CALIBRATE", "calibrate", [])[1] == "active"
assert button_style("m", "SOUND", "run", ["notifications"])[1] == "on" and button_style("m", "SOUND", "run", ["sound"])[1] == "off"
assert button_style("n", "NOTIFY", "run", ["sound"])[1] == "on" and button_style("n", "NOTIFY", "run", ["notifications"])[1] == "off"

# draw(): only if OpenCV is installed (uv run --with mediapipe tests/test_posture.py)
try:
    import cv2
    import numpy as np
except ImportError:
    print("skipped draw(): OpenCV is not installed")
else:
    video = np.full((CAM_H, CAM_W, 3), 120, np.uint8)
    lm = seen_lm()
    row = [T_OK] * 918 + [T_DRIFT] * 5 + [T_NAG] * 5
    items, stats = log_entries([(tm(1), "bad_start", "Slouching"), (tm(1, 40), "bad_end", "Slouching")])
    shown = draw(video.copy(), View("Slouching  42s", RED, lm=lm, level="nag", stats=(0.80, 0.08), problem="Slouching", off=["sound"],
                                    sitting=1520, row=row, aligned=aligned(row), items=items, today=stats, live=("Slouching", 42),
                                    clock="2026-01-01 10:00:00"))
    assert shown.shape == (CAM_H + BAR_H, CAM_W + SIDE_W, 3)
    # the frame of the picture: red and thick after a nag, and only inside the picture
    assert [tuple(shown[y, x]) for y, x in ((2, 320), (CAM_H - 3, 320), (240, 2), (240, CAM_W - 3))] == [RED] * 4
    assert tuple(shown[CAM_H + 2, 320]) == BG and tuple(shown[240, CAM_W + 2]) == BG and tuple(shown[8, 320]) != RED
    assert tuple(draw(video.copy(), View("x", YELLOW, level="drift"))[1, 320]) == YELLOW
    assert tuple(draw(video.copy(), View("OK", GREEN))[1, 320]) == GREEN
    assert tuple(draw(video.copy(), View("PAUSED", DIM, mode="pause"))[1, 320]) == EDGE
    assert tuple(draw(video.copy(), View("CAL", YELLOW, mode="calibrate"))[1, 320]) == YELLOW
    # the timeline in the controls
    y, x = CAM_H + 120 + 13, 16
    assert [tuple(shown[y, x + i]) for i in (0, 922, 927)] == [GREEN, YELLOW, RED]
    # the figure: a line for the shoulders and one dot for the head, mirrored or not
    assert tuple(shown[round(0.6 * CAM_H), 320]) == RED and tuple(shown[round(0.2 * CAM_H), 320]) == RED
    left = [V(0.3, p.y, p.visibility) if i < 11 else p for i, p in enumerate(lm)]  # the head on the left of the picture
    assert tuple(draw(video.copy(), View("OK", GREEN, lm=left))[round(0.2 * CAM_H), round(0.3 * CAM_W)]) == GREEN
    assert tuple(draw(video.copy(), View("OK", GREEN, lm=left, mirror=True))[round(0.2 * CAM_H), round(0.7 * CAM_W)]) == GREEN
    assert tuple(draw(video.copy(), View("OK", GREEN, lm=seen_lm(nose=0.0)))[round(0.2 * CAM_H), 320]) != GREEN  # not seen: no figure
    # the scanlines
    flat = draw(video.copy(), View("OK", GREEN))
    assert (flat[242, 320] < flat[241, 320]).all() == CRT
    # the log: the outcome has its colour, and an empty log says so
    assert (shown[200:CAM_H, CAM_W:] == GREEN).all(axis=2).any() and not (draw(video.copy(), View("OK", GREEN))[200:CAM_H, CAM_W:] == GREEN).all(axis=2).any()
    now_row = lambda img: (img[190:212, CAM_W + 16:CAM_W + 60] == RED).all(axis=2).any()  # "NOW" in red, the first row of the log
    assert now_row(shown) and not now_row(draw(video.copy(), View("OK", GREEN, items=items, today=stats)))
    # the buttons: a switched on toggle has a green border, a switched off one a grey border
    by_key = {r[0]: r for r in button_rects()}
    mid = lambda key: (by_key[key][3] + by_key[key][5]) // 2
    assert tuple(shown[mid("n"), by_key["n"][2]]) == GREEN and tuple(shown[mid("m"), by_key["m"][2]]) == EDGE
    # the hint, the countdown and the calibration bar
    hinted = draw(video.copy(), View("OK", GREEN, hint="No person in view"))
    assert tuple(hinted[CAM_H - 5, 5]) == BG and tuple(flat[CAM_H - 5, 5]) != BG
    assert draw(video.copy(), View("Sit straight: 3", YELLOW, mode="calibrate", big="3"))[200:300, 250:390].max() == 235
    bar = draw(video.copy(), View("Calibrating...", YELLOW, mode="calibrate", progress=0.5))
    assert tuple(bar[CAM_H + 133, 16 + 300]) == YELLOW and tuple(bar[CAM_H + 133, 16 + 600]) != YELLOW
    # mirror: a lit point on the left of the picture appears on the right
    dot = np.zeros((CAM_H, CAM_W, 3), np.uint8)
    dot[100, 50] = (255, 255, 255)
    mirrored, unflipped = draw(dot.copy(), View("OK", GREEN, mirror=True)), draw(dot.copy(), View("OK", GREEN))
    assert mirrored[100, CAM_W - 1 - 50].all() and not mirrored[100, 50].any()
    assert unflipped[100, 50].all() and not unflipped[100, CAM_W - 1 - 50].any()
    # the log and the controls are kept between frames, but never stale and never shared with the caller
    base = View("OK", GREEN, row=row, sitting=100)
    assert posture.panels(base) is posture.panels(View("OK", GREEN, row=row, sitting=100.4, lm=lm, mirror=True, hint="x", clock="t"))
    assert posture.panels(View("OK", GREEN, row=row, sitting=161)) is not posture.panels(base)
    assert not np.array_equal(draw(video.copy(), View("OK", GREEN))[CAM_H:], draw(video.copy(), View("AWAY", GREEN))[CAM_H:])
    assert not np.array_equal(draw(video.copy(), View("OK", GREEN, stats=(1.0, 0.0)))[CAM_H:], draw(video.copy(), View("OK", GREEN, stats=(0.7, 0.0)))[CAM_H:])
    first = draw(video.copy(), base)
    first[:] = 0  # the caller may do anything with the image
    assert draw(video.copy(), base)[CAM_H:].any()
    for v in (View("SNOOZED 4:32", DIM, mode="snooze", row=[0] * 928), View("PAUSED", DIM, mode="pause"), View("AWAY", DIM, hint="No person in view")):
        assert draw(video.copy(), v).shape == (CAM_H + BAR_H, CAM_W + SIDE_W, 3)

# The version in posture.py is the newest version in CHANGELOG.md
changelog = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
assert re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M).group(1) == VERSION
print("ok")
