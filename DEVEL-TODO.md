# DEVEL-TODO

- **Sideways tilt**: shoulder-line angle against the profile. Dropped for now: the weakest signal from the ~45° camera position. Revisit once slouching and leaning in are reliable.
- `--report`: per-day minutes monitored, minutes in bad posture, nudges. Wait for a few days of `~/.local/share/posture-check/log.csv`.
- Launcher or autostart on login: a `.desktop` file.
- Noise-aware thresholds: store the spread of the calibration samples in `profile.json`. Only if the live numbers jump around.
