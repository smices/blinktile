#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$root_dir/.build/arduino"
dist_dir="$root_dir/dist"
# The complete BLE/Wi-Fi/HTTP image is 1.34 MiB; default leaves only 1.25 MiB.
fqbn='esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashSize=4M,PartitionScheme=huge_app,CPUFreq=160,FlashFreq=80,FlashMode=dio'
file_prefix_map="-ffile-prefix-map=${HOME}=/build"

mkdir -p "$build_dir" "$dist_dir"
arduino-cli compile \
  --fqbn "$fqbn" \
  --clean \
  --build-property "compiler.c.extra_flags=${file_prefix_map}" \
  --build-property "compiler.cpp.extra_flags=${file_prefix_map}" \
  --build-path "$build_dir" \
  --output-dir "$dist_dir" \
  "$root_dir/firmware/IconShow"

printf 'built %s\n' "$dist_dir"
