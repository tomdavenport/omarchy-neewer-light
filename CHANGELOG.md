# Changelog

## 2.5.0 — Gentle transitions and automatic power

- Preferences now offers Gentle (1 second), Quick (0.42 seconds) or Off for theme changes.
- Optional Off when locked uses Hyprland lock notifications; unlock restores only a successful automatic Off. Manual Off stays off.
- Optional Off on shutdown sends a bounded Off attempt before a normal shutdown or restart.
- Fix stale UI responses that could misreport Cycle state. Commands now wait for both process exit and complete output, and older snapshots are ignored.
- Stopping Cycle also stops an active theme fade and holds the last colour sent.

## 2.4.1 — Fade with theme changes

- Blend from the current light colour into a new theme using Omarchy's 420 ms cubic easing.
- Start near the background transition, with a short fallback for changes without a background.
- Preserve Cycle progress and brightness; clicking a swatch still previews immediately.
- Rapid theme changes continue from the last colour sent. Reconnecting lights apply the latest palette, and Off stays off.

## 2.4.0 — First public release

- Guided first-use setup: enable local controls, find the RGB1, test its colour and confirm.
- Three swatches selected from the active Omarchy palette.
- Immediate theme following while connected and click-to-preview colour changes.
- Gentle colour fades with Slow, Medium and Fast speeds.
- Saved brightness, deliberate On/Off and persistent Bluetooth connection handling.
- Per-user installation, staged dependency upgrades, rollback and documented removal.

The preceding local versions established RGB1 control, theme matching and fading through live use. This release supports one RGB1; support for other models and multiple lights is not claimed.
