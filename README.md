# posture-check

posture-check watches your posture with a webcam. It shows a desktop notification when you slouch or lean toward the screen.

The app runs on your computer. It does not save images. It does not send data over the network.

Tested on Fedora with GNOME on Wayland.

## Requirements

- A webcam
- `notify-send` (package `libnotify`)
- `pw-play` (package `pipewire-utils`)
- [uv](https://docs.astral.sh/uv/)

## Start

1. Run `uv run posture.py`. The first run downloads the dependencies.
2. Sit straight when the window shows the countdown.
3. Stay still for 3 more seconds.

The app saves the result in `~/.config/posture-check/profile.json`. Later runs use this file.

Put the camera in front of you or up to about 45 degrees to the side.

## Keys

Click the window before you press a key.

| Key | Action |
|-----|--------|
| `c` | Calibrate again. Do this after you move the camera or the chair. |
| `p` | Pause or resume. |
| `m` | Mute or unmute the sounds. The notifications stay on. |
| `n` | Hide or show the notifications. The sounds stay on. |
| `q` | Quit. |

## How it works

The app compares your head with the profile. It uses two numbers:

- **Head height**: the distance from the head to the shoulders. This number gets smaller when you slouch.
- **Lean in**: how far the head moves toward the screen.

When a number passes its limit, the app starts a timer. After 20 seconds, you get a notification. The app repeats it every 2 minutes until you sit straight.

The limits are constants at the top of `posture.py`: `SLOUCH`, `LEAN`, `GRACE`, `REPEAT`, `DOWN_DELAY` and `UP_DELAY`. The window shows the live numbers.

## Sound

The app plays three sounds with `pw-play`.

- `winding_down.wav` plays when your posture has been bad for 2 seconds.
- `four_clicks.wav` plays with each notification.
- `ratchet_up.wav` plays when your posture has been good for 0.5 seconds. It plays only after `winding_down.wav` played.

Press `m` to mute the sounds. To change a sound, edit `sounds/synth.py`. Then run `python3 sounds/synth.py`.

## Log

The app writes events to `~/.local/share/posture-check/log.csv`. The columns are `timestamp`, `event` and `detail`.

The events are `start`, `stop`, `calibrate`, `pause`, `resume`, `away`, `back`, `bad_start` and `bad_end`. A `bad_start` row appears when bad posture begins. To ignore short dips, keep only the `bad_start` and `bad_end` pairs that last 20 seconds or more. If an interval is still open at `stop`, it ends at the `stop` row.

## Test

Run `python3 tests/test_posture.py`. The test needs no install.

## Plans

See [DEVEL-TODO.md](DEVEL-TODO.md).

## License

MIT. See [LICENSE](LICENSE). The model file keeps its own license (Apache 2.0).

## Credits

The pose model is `pose_landmarker_lite` from [MediaPipe](https://github.com/google-ai-edge/mediapipe) by Google (Apache 2.0).
