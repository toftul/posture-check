"""Checks for the posture logic. Run from anywhere: python3 tests/test_posture.py (needs no install)."""
import random
import re
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from posture import (BREAK_AFTER, BREAK_AWAY, BREAK_REPEAT, CAMERA_RETRY, DOWN_DELAY, GRACE, LEAN, LEAN_EXIT, MIN_VISIBLE,
                     REPEAT, SLOUCH, SLOUCH_EXIT, UP_DELAY, VERSION, Breaks, Camera, Cues, due, fmt_span, judge, measure,
                     nag_text, typical)

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
# The version in posture.py is the newest version in CHANGELOG.md
changelog = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
assert re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M).group(1) == VERSION
print("ok")
