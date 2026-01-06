# WavePunkOS — Foundation Rules

This document is the non-negotiable foundation for WavePunkOS v1.
All code, UI, and behavior must follow these rules unless explicitly revised.

## Core Metaphor
WavePunkOS feels like using an invisible glass trackpad in mid-air.

- Pinch = finger touching glass
- Movement while pinched moves the cursor (relative, anchored)
- Release = instant stop (no inertia)
- Actions happen on state changes, not motion guesses

## Input Parity (Required)
WavePunkOS must fully replace a trackpad:
- Move
- Left click (pinch tap)
- Click & drag (pinch hold)
- Scroll (two-finger pinch + vertical movement)
- Right click (thumb + middle pinch)

## Safety (Absolute)
- Clench fist for ~1 second = immediate OFF
- All buttons must be released on:
  - panic gesture
  - tracking loss
  - app stop / crash
- Physical mouse & keyboard must always continue working

## Visual Philosophy
- Overlay is extremely subtle
- Overlay follows the hand, not the cursor
- No landmarks, dots, or debug visuals outside Playground
- Silent by default; optional soft “haptic-style” sounds

## Onboarding
- First run includes a calm, guided ~30s calibration
- No overwhelming choices
- Defaults must feel good without tuning

## Profiles
- Presets only (v1):
  - Default
  - Precision
  - Chill
- No numeric tuning exposed unless explicitly entering Advanced mode

## Engineering Rules
- Deterministic state machine
- Hysteresis + time thresholds for all pinch decisions
- If tracking confidence drops: fail safe immediately
- Architecture must allow replaying recorded input sessions

## Scope Discipline
WavePunkOS v1 does NOT include:
- gesture libraries
- macros
- app-specific automation
- ML model training
- cloud features

Ship the feel first.
