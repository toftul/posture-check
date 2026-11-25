# DEVEL-TODO

- **Sideways tilt**: shoulder-line angle against the profile. Dropped for now: the weakest signal from the ~45° camera position. Revisit once slouching and leaning in are reliable.
- Different sounds for slouching and leaning in. For now, one sound serves both.
- `--report`: per-day minutes monitored, minutes in bad posture, nudges. Wait for a few days of `~/.local/share/posture-check/log.csv`.
- Autostart on login: a copy of the `.desktop` file in `~/.config/autostart/`. Document it in the README.
- An install script that fills in the paths of the `.desktop` file.
- Noise-aware thresholds: store the spread of the calibration samples in `profile.json`. Only if the live numbers jump around.
