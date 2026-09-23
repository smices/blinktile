# BlinkTile local project memory

## User requirements recorded 2026-09-22

- Model routing: Astra is the planning/analysis brain; Sol low handles ordinary tasks; Luna xhigh executes worker tasks. Repeatedly unsuccessful Luna work may escalate to Terra high.
- Every user-facing response must identify its actual model when known. Do not mislabel a runtime whose exact model is unavailable.
- Commit each completed and verified coherent feature locally. No push was requested.
- Before delivery, perform a reviewer-style audit, fix confirmed defects, then rerun relevant validation. Continue work while applying these rules.

## Product decisions

- ESP32-C3 SuperMini, GPIO2, WS2812B 8×8, GRB 800kHz, linear row-major mapping (current firmware does not reverse odd rows).
- USB 5V/1A. Default brightness 25% (64/255); apply per-frame estimated LED current budget of 500mA and verify on hardware.
- Deliver real PNGs and animated GIFs inside an offline HTML gallery; provide a working HTML BLE/WebSocket controller and JavaScript integration example.
- Static icons, shape animations, rainbow cycling/flow, breathing, alternating brightness, blink, independent periods and global speed.
- ASCII 5×7 digits/English/symbols, smooth one-pixel scrolling for 100% and longer text.
- Idle pet interrupted by external status, then restored on release/expiration.
- Current idle pet starts with six-lane green falling streaks (random length, depth and density; 200ms/row), with brief smile and wink/heart interludes. BLE broadcasts `BlinkTile`; the setup hotspot still uses `IconShow-`.
- Build firmware after design and controller work. First setup over USB; subsequent Wi-Fi setup through a password-protected device hotspot at 192.168.4.1. Failed candidate connection must preserve previous credentials.
- Reference project is read-only. Do not modify it.

## Acceptance boundary

At the start of implementation no ESP32 USB serial port was detected. By 2026-09-23 the current firmware had been flashed with hash verification and serial readback confirmed pet idle, 64/255 boot brightness and 8/255 after a temporary command. BLE radio, electrical measurements and the latest animation's visual quality remain unverified on hardware; do not infer them from compilation or simulation.
