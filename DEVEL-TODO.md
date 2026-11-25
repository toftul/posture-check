# DEVEL-TODO

- **Sideways tilt**: shoulder-line angle against the profile. Dropped for now: the weakest signal from the ~45° camera position. Revisit once slouching and leaning in are reliable.
- Different sounds for slouching and leaning in. For now, one sound serves both.
- `--report`: per-day minutes monitored, minutes in bad posture, nudges. Removed for now. The log already has the `nag` and `break` rows that it needs.
- Autostart on login: a copy of the `.desktop` file in `~/.config/autostart/`. Document it in the README.
- An install script that fills in the paths of the `.desktop` file.
- Noise-aware thresholds: store the spread of the calibration samples in `profile.json`. Only if the live numbers still jump around after the hysteresis (`SLOUCH_EXIT`, `LEAN_EXIT`).
- Check `SLOUCH_EXIT` and `LEAN_EXIT` with a few days of use. The log has no numbers, so they came from reasoning, not from data. If a nag lasts too long after you sit up, move them closer to the limits.
- Check `MIN_VISIBLE` at the ~45° camera position. If the app shows AWAY while you sit, lower it.
- Eye reminder (20-20-20 rule): look 20 feet away for 20 seconds, every 20 minutes. Same mechanism as the break reminder.
- Raised shoulders: the gap between ear and shoulder, divided by the shoulder width. Probably the same signal as head height from this camera position.
- Guided calibration of the bad postures (PosturePilot): the limits would come from your own slouch, not from the constants. Costs about 30 seconds more at each calibration.
- A snooze button in the notification. `notify-send --action` needs `--wait`, so it needs a helper process.
- Stats in the window: today's bad time and nags. Best after `--report` is back, so both use the same numbers.
- Fill the timeline from the log at start. Today it is empty after each start.
- A target ring in the picture: where your head was at the calibration, next to the live head. It shows the distance without the numbers.
- Set the limits from the window. enkr1 has a sensitivity slider. The bars could take a click or a drag to move `SLOUCH` and `LEAN`.
- Scale the window. The text has a fixed size in pixels, so a resized window scales it with the picture.
- A palette for color blindness. Green and red are hard to tell apart for some people. The status text and the bars help, but the frame and the timeline use color only.
