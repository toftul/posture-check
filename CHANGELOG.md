# Changelog

All notable changes to this project are in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The version numbers follow [Semantic Versioning](https://semver.org/).

For each change, add a line under `[Unreleased]`. To make a release, rename that section to the new version and the date. Set `VERSION` in `posture.py` to the same number. `tests/test_posture.py` checks that the two match.

## [Unreleased]

### Added

- A new window with three parts, after the design of posture-check by enkr1. The camera is on the left, the log of the day is on the right, and the controls are below.
- The log panel. TODAY shows the episodes, the bad time, the average length and the busiest hour. LOG lists the episodes with the outcome FIXED, SLOW or IGNORED, and also the breaks, snoozes, pauses, times away and calibrations. It reads the rows of today from the log file at start.
- Clickable buttons for every key. The buttons show their key and their state.
- The window shows three states in three colors. Green is OK. Yellow is a problem before the first nag. Red is a problem after a nag. The frame of the picture, the figure and the status text use the color.
- A bar for each number. It shows the limit, the band of the hysteresis, your baseline and the live value.
- A timeline of the last 30 minutes with the share of OK time ("aligned").
- A hint over the picture when a frame cannot be measured: "No person in view" or "Not seen: right shoulder".
- Calibration shows a large countdown number and a progress bar for the sampling.
- A badge, a clock and a scanline look on the picture. Set `CRT = False` in `posture.py` to remove the scanlines.
- Key `f` flips the picture.

### Changed

- The window is 960 by 640 pixels. Before, it was 400 pixels wide.
- The figure is a line for the shoulders and one dot for the head, with a dashed line between them. Before, it was 13 dots and the shoulder line.
- The picture is a mirror image. Set `MIRROR = False` in `posture.py` for the old view.
- The status text is yellow until the first nag. Before, it was red at once.
- A second press of `s` ends the snooze.
- The bars replace the text "warn below 0.85" and "warn above 0.06".
- The colors follow the enkr1 design.

## [0.4.0] - 2026-11-25

### Added

- Snooze: press `s` to pause for 5 minutes. The app starts again by itself.
- Break reminder after 30 minutes of sitting, then every 5 minutes. About 70 seconds away from the camera counts as a break. The window shows the sitting time.
- Each nag names the problem, says how long it lasted and gives one tip. A new notification replaces the old one. The notifications show the app icon.
- The option `--camera N` selects the camera. The option `--version` shows the version.
- The log has three new events: `snooze`, `nag` and `break`.
- The app opens the camera again after read errors, for example after suspend. After 30 seconds without a picture, the app stops.
- A start error or a lost camera shows as a notification, because the menu launcher has no terminal.

### Changed

- A problem now ends only when its number is back past `SLOUCH_EXIT` or `LEAN_EXIT`. Before, one limit started and ended it, and the state flickered near the limit.
- The app ignores a frame when it cannot see the nose or a shoulder well (`MIN_VISIBLE`). Standing up now shows as away.
- A SIGTERM, for example at logout, writes the `stop` row to the log.
- The stats strip in the window is 25 pixels taller.

## [0.3.0] - 2026-11-25

### Added

- App icon: a shrimp curled in a golden spiral.
- README steps for the desktop launcher.

## [0.2.0] - 2026-11-25

### Added

- Three sounds with `pw-play`: `winding_down.wav`, `four_clicks.wav` and `ratchet_up.wav`.
- Key `m` mutes the sounds. Key `n` hides the notifications. The window shows what is off.
- `sounds/synth.py` makes the sound files.

## [0.1.0] - 2026-11-25

### Added

- First release. The app watches you with a webcam and calibrates a profile from your upright posture.
- A desktop notification when you slouch or lean toward the screen.
- A preview window with the live numbers. Keys `c`, `p` and `q`.
- A CSV log of the events.
- MIT license.
