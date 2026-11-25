"""Checks for the posture logic. Run from anywhere: python3 tests/test_posture.py (needs no install)."""
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from posture import DOWN_DELAY, GRACE, LEAN, REPEAT, SLOUCH, UP_DELAY, Cues, due, judge, measure, typical

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
print("ok")
