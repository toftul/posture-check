"""Checks for the posture logic. Run from anywhere: python3 tests/test_posture.py (needs no install)."""
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from posture import GRACE, LEAN, REPEAT, SLOUCH, due, judge, measure, typical

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
print("ok")
