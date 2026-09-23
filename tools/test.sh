#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

python3 tests/test_assets.py
node tests/test_engine.cjs
node tests/test_client.cjs
python3 tests/test_transport.py
python3 tests/test_codex_status.py
python3 tests/test_firmware_render.py
python3 tests/test_firmware_transport.py
python3 tests/test_setup_page.py
