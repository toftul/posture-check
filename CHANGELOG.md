# Changelog

All notable changes to this project are in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The version numbers follow [Semantic Versioning](https://semver.org/).

For each change, add a line under `[Unreleased]`. To make a release, rename that section to the new version and the date. Set `VERSION` in `posture.py` to the same number. `tests/test_posture.py` checks that the two match.

## [Unreleased]

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
