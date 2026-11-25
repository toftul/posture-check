"""The three alert sounds, made from stdlib only. The meaning is in the rhythm, not the pitch.
Run: python3 sounds/synth.py   (rewrites the .wav files next to this script)"""
import math
import random
import struct
import sys
import wave
from pathlib import Path

RATE = 48000
TAU = 2 * math.pi
PEAK = 0.25  # clicks are judged by their peak, not their average level
LEAD = 0.3   # seconds of silence first, to wake a sleeping Bluetooth output

THOCK = dict(decay=0.025, noise=0.25, bright=1100)  # soft, rubbery keyboard
TICK = dict(decay=0.007, noise=0.5, bright=2400)    # dry wooden clock


def click(body, decay, noise, bright, seed=0):
    """One click: a 2 ms burst of band-passed noise (the contact) on a short damped sine (the body)."""
    rng, n = random.Random(seed), int(RATE * decay * 6)
    f, low, band, out = 2 * math.sin(math.pi * bright / RATE), 0.0, 0.0, []
    for i in range(n):
        t = i / RATE
        low += f * band
        band += f * (rng.uniform(-1, 1) - low - band / 1.5)
        v = noise * 4 * band * math.exp(-t / 0.0015) + math.sin(TAU * body * t) * math.exp(-t / decay)
        out.append(v * min(1.0, t / 0.0005) * min(1.0, (n - i) / (0.01 * RATE)))
    return out


def train(steps, **kw):
    """steps: (start_seconds, body_hz, gain) for each click."""
    return [(t, click(b, **kw), g) for t, b, g in steps]


def mix(parts, peak=PEAK):
    """parts: (start_seconds, samples, gain). Adds the lead-in silence and sets the peak level."""
    offs = [int(RATE * (LEAD + s)) for s, _, _ in parts]
    out = [0.0] * max(o + len(x) for o, (_, x, _) in zip(offs, parts))
    for off, (_, x, gain) in zip(offs, parts):
        for i, v in enumerate(x):
            out[off + i] += v * gain
    k = peak / max(abs(v) for v in out)
    return [v * k for v in out]


def save(path, samples):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in samples))


sounds = {
    # posture turns bad: five soft clicks that slow down and fall in pitch, like something settling
    "winding_down": mix(train([(0, 620, 1), (0.10, 540, .85), (0.24, 470, .7), (0.44, 410, .55), (0.72, 360, .4)], **THOCK)),
    # posture is good again: four quick ticks rising in pitch, like a ratchet winding up
    "ratchet_up": mix(train([(0, 800, .6), (0.065, 1000, .7), (0.13, 1250, .85), (0.195, 1550, 1)], **TICK)),
    # still bad after 20 s: four even, high clicks. Steady, so it is not mistaken for the ratchet. 3 dB louder.
    "four_clicks": mix(train([(i * 0.13, 2000, 1) for i in range(4)], decay=0.006, noise=0.4, bright=2800), peak=0.35),
}

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    for name, s in sounds.items():
        save(out / f"{name}.wav", s)
        print(f"{name}.wav  {len(s) / RATE:.2f}s")
