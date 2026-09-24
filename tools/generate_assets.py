#!/usr/bin/env python3
"""Generate the deterministic IconShow data and display assets."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import subprocess

from PIL import Image, ImageDraw, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
ASSET_DIR = WEB_DIR / "assets"
FIRMWARE_DIR = ROOT / "firmware" / "IconShow"

COLORS = {
    "red": "#FF0000",
    "orange": "#FF8000",
    "yellow": "#FFFF00",
    "green": "#00FF00",
    "cyan": "#00FFFF",
    "blue": "#0040FF",
    "purple": "#A000FF",
    "pink": "#FF4080",
    "white": "#FFFFFF",
    "off": "#000000",
}

def pattern(*rows: str) -> list[int]:
    """Turn an 8x8 grayscale drawing into the shared 64-byte format."""

    if len(rows) != 8 or any(len(row) != 8 for row in rows):
        raise ValueError(f"patterns must be 8x8, got {rows!r}")
    levels = {".": 0, "o": 96, "+": 180, "#": 255}
    try:
        return [levels[pixel] for row in rows for pixel in row]
    except KeyError as exc:
        raise ValueError(f"unknown pattern pixel {exc.args[0]!r}") from exc


def overlay(*layers: list[int]) -> list[int]:
    return [max(values) for values in zip(*layers)]


def save_png(frame: list[tuple[int, int, int]], path: Path, size: int = 8) -> None:
    image = Image.new("RGB", (8, 8))
    image.putdata(frame)
    if size != 8:
        image = image.resize((size, size), Image.Resampling.NEAREST)
    image.save(path, format="PNG", optimize=False)


def save_gif(frames: list[list[tuple[int, int, int]]], durations: list[int], path: Path) -> None:
    images = [Image.new("RGB", (8, 8)) for _ in frames]
    for image, frame in zip(images, frames):
        image.putdata(frame)
    images[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )


NODE_RENDERER = """
require('./web/data.js');
const Engine = require('./web/engine.js').IconEngine;
const request = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const engine = new Engine(globalThis.IconData);
for (const command of request.commands) {
  const result = engine.execute(command, 0);
  if (!result.ok) throw new Error(result.error);
}
process.stdout.write(JSON.stringify(request.times.map(time => engine.frame(time))));
"""


def engine_frames(commands: list[dict], times: list[int]) -> list[list[tuple[int, int, int]]]:
    """Use the browser engine as the sole pixel renderer for published assets."""

    commands = [{"id": 2147483647, "op": "brightness", "value": 217}, *commands]
    result = subprocess.run(
        ["node", "-e", NODE_RENDERER], cwd=ROOT,
        input=json.dumps({"commands": commands, "times": times}),
        text=True, capture_output=True, check=True,
    )
    return [[tuple(rgb) for rgb in frame] for frame in json.loads(result.stdout)]


# 5x7 rows, converted below to five column bytes with bit 0 at the top row.
FONT_ROWS: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    "%": ("11001", "11010", "00010", "00100", "01000", "01011", "10011"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00110", "00100"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    ";": ("00000", "00110", "00110", "00000", "00110", "00110", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "\\": ("10000", "01000", "01000", "00100", "00010", "00010", "00001"),
    "=": ("00000", "11111", "00000", "00000", "11111", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "#": ("01010", "11111", "01010", "01010", "11111", "01010", "00000"),
    "@": ("01110", "10001", "10111", "10101", "10111", "10000", "01111"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "^": ("00100", "01010", "10001", "00000", "00000", "00000", "00000"),
    "`": ("01000", "00100", "00000", "00000", "00000", "00000", "00000"),
    "'": ("00100", "00100", "00000", "00000", "00000", "00000", "00000"),
    '"': ("01010", "01010", "00000", "00000", "00000", "00000", "00000"),
    "$": ("00100", "01111", "10100", "01110", "00101", "11110", "00100"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "{": ("00010", "00100", "00100", "01000", "00100", "00100", "00010"),
    "}": ("01000", "00100", "00100", "00010", "00100", "00100", "01000"),
    "~": ("00000", "00000", "01001", "10110", "00000", "00000", "00000"),
}
FONT_ROWS.update({
    "a": ("00000", "00000", "01110", "00001", "01111", "10001", "01111"),
    "b": ("10000", "10000", "11110", "10001", "10001", "10001", "11110"),
    "c": ("00000", "00000", "01110", "10001", "10000", "10001", "01110"),
    "d": ("00001", "00001", "01111", "10001", "10001", "10001", "01111"),
    "e": ("00000", "00000", "01110", "10001", "11111", "10000", "01110"),
    "f": ("00110", "01001", "01000", "11100", "01000", "01000", "01000"),
    "g": ("00000", "00000", "01111", "10001", "01111", "00001", "01110"),
    "h": ("10000", "10000", "10110", "11001", "10001", "10001", "10001"),
    "i": ("00100", "00000", "01100", "00100", "00100", "00100", "01110"),
    "j": ("00010", "00000", "00110", "00010", "00010", "10010", "01100"),
    "k": ("10000", "10000", "10010", "10100", "11000", "10100", "10010"),
    "l": ("01100", "00100", "00100", "00100", "00100", "00100", "01110"),
    "m": ("00000", "00000", "11010", "10101", "10101", "10001", "10001"),
    "n": ("00000", "00000", "10110", "11001", "10001", "10001", "10001"),
    "o": ("00000", "00000", "01110", "10001", "10001", "10001", "01110"),
    "p": ("00000", "00000", "11110", "10001", "11110", "10000", "10000"),
    "q": ("00000", "00000", "01111", "10001", "01111", "00001", "00001"),
    "r": ("00000", "00000", "10110", "11001", "10000", "10000", "10000"),
    "s": ("00000", "00000", "01111", "10000", "01110", "00001", "11110"),
    "t": ("01000", "01000", "11100", "01000", "01000", "01001", "00110"),
    "u": ("00000", "00000", "10001", "10001", "10001", "10011", "01101"),
    "v": ("00000", "00000", "10001", "10001", "10001", "01010", "00100"),
    "w": ("00000", "00000", "10001", "10101", "10101", "11011", "10001"),
    "x": ("00000", "00000", "10001", "01010", "00100", "01010", "10001"),
    "y": ("00000", "00000", "10001", "10001", "01111", "00001", "01110"),
    "z": ("00000", "00000", "11111", "00010", "00100", "01000", "11111"),
})
for character in (chr(code) for code in range(0x20, 0x7F)):
    FONT_ROWS.setdefault(character, ("00000",) * 7)


def font_bytes() -> dict[str, list[int]]:
    result = {}
    for character in (chr(code) for code in range(0x20, 0x7F)):
        rows = FONT_ROWS[character]
        result[character] = [
            sum((int(rows[row][column]) << row) for row in range(7)) for column in range(5)
        ]
    return result


STATIC_PATTERNS = {
    "success": (
        "........", "......#.", ".....##.", ".#..##..", ".####...", "..##....", "........", "........"
    ),
    "error": (
        "##....##", ".##..##.", "..####..", "...##...", "..####..", ".##..##.", "##....##", "........"
    ),
    "warning": (
        "...##...", "..####..", ".##..##.", ".##..##.", "########", "...##...", "...##...", "........"
    ),
    "info": (
        "...##...", "........", "...##...", "..###...", "...##...", "...##...", ".######.", "........"
    ),
    "question": (
        "..####..", ".##..##.", "....##..", "...##...", "..##....", "........", "..##....", "........"
    ),
    "ready": (
        "..####..", ".##..##.", "##....##", "##.##.##", "##....##", ".##..##.", "..####..", "........"
    ),
    "wifi": (
        "........", "..####..", ".######.", "##....##", "...##...", "..####..", "...##...", "........"
    ),
    "bluetooth": (
        "...#....", "...##...", "...#.#..", ".#..#...", "...#.#..", "...##...", "...#....", "........"
    ),
    "disconnected": (
        "..####..", ".######.", "##....##", "...##...", "..##....", ".##.....", "##......", "........"
    ),
    "battery_full": (
        "........", ".######.", ".######.", ".#######", ".#######", ".######.", ".######.", "........"
    ),
    "battery_half": (
        "........", ".######.", ".###..#.", ".###..##", ".###..##", ".###..#.", ".######.", "........"
    ),
    "battery_low": (
        "........", ".######.", ".##...#.", ".##...##", ".##...##", ".##...#.", ".######.", "........"
    ),
    "play": (
        "..#.....", "..##....", "..###...", "..####..", "..###...", "..##....", "..#.....", "........"
    ),
    "pause": (
        ".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##.", "........"
    ),
    "stop": (
        ".######.", "########", "########", "########", "########", "########", ".######.", "........"
    ),
    "record": (
        "..####..", ".######.", "##....##", "##.##.##", "##....##", ".######.", "..####..", "........"
    ),
    "message": (
        "........", ".######.", "########", "##....##", "##....##", ".######.", "..##....", ".#......"
    ),
    "locked": (
        "..####..", ".##..##.", ".##..##.", "########", "##.##.##", "##....##", "########", "........"
    ),
    "unlocked": (
        "..####..", ".##.....", ".##.....", "########", "##.##.##", "##....##", "########", "........"
    ),
    "arrow_up": (
        "...#....", "..###...", ".#####..", "...#....", "...#....", "...#....", "...#....", "...#...."
    ),
    "arrow_down": (
        "...#....", "...#....", "...#....", "...#....", "...#....", ".#####..", "..###...", "...#...."
    ),
    "arrow_left": (
        "...#....", "..##....", ".###....", "########", ".###....", "..##....", "...#....", "........"
    ),
    "arrow_right": (
        "....#...", "....##..", "....###.", "########", "....###.", "....##..", "....#...", "........"
    ),
    "sad": (
        "........", ".##..##.", ".##..##.", "........", "........", "..####..", ".##..##.", "........"
    ),
    "angry": (
        ".##..##.", "..####..", "..####..", "........", ".##..##.", "..####..", ".##..##.", "........"
    ),
    "neutral": (
        "........", ".##..##.", ".##..##.", "........", "..####..", "........", "........", "........"
    ),
    "broken_heart": (
        ".##.##..", "#####...", ".###....", "..##....", "...###..", "....###.", ".....#..", "........"
    ),
    "check": (
        "........", "......#.", ".....##.", ".#..##..", ".####...", "..##....", "........", "........"
    ),
    "cross": (
        "##....##", ".##..##.", "..####..", "...##...", "..####..", ".##..##.", "##....##", "........"
    ),
    "plus": (
        "...##...", "...##...", "...##...", "########", "########", "...##...", "...##...", "........"
    ),
    "minus": (
        "........", "........", "########", "########", "........", "........", "........", "........"
    ),
}


STATIC_SPECS = [
    ("success", "成功", "green"), ("error", "错误", "red"), ("warning", "警告", "orange"),
    ("info", "信息", "cyan"), ("question", "问题", "yellow"), ("ready", "就绪", "green"),
    ("wifi", "无线", "cyan"), ("bluetooth", "蓝牙", "blue"), ("disconnected", "断开", "red"),
    ("battery_full", "满电", "green"), ("battery_half", "半电", "yellow"), ("battery_low", "低电", "red"),
    ("play", "播放", "green"), ("pause", "暂停", "yellow"), ("stop", "停止", "red"),
    ("record", "录制", "red"), ("message", "消息", "cyan"), ("locked", "锁定", "purple"),
    ("unlocked", "解锁", "green"), ("arrow_up", "上", "white"), ("arrow_down", "下", "white"),
    ("arrow_left", "左", "white"), ("arrow_right", "右", "white"), ("sad", "难过", "blue"),
    ("angry", "生气", "red"), ("neutral", "平静", "white"), ("broken_heart", "心碎", "pink"),
    ("check", "勾选", "green"), ("cross", "叉选", "red"), ("plus", "加号", "white"), ("minus", "减号", "white"),
]


def animate_patterns() -> dict[str, tuple[str, list[list[int]], list[int], str]]:
    ring_points = [(1, 3), (1, 4), (2, 5), (3, 6), (4, 6), (5, 5),
                   (6, 4), (6, 3), (5, 2), (4, 1), (3, 1), (2, 2)]
    connector_points = [(2, 3), (2, 4), (3, 4), (3, 5), (4, 5), (4, 4),
                        (5, 4), (5, 3), (4, 3), (4, 2), (3, 2), (3, 3)]
    step_durations = []
    rng = random.Random(0xB11A)
    paces = [rng.randint(280, 700) for _ in range(8)]
    for offset in range(len(ring_points) * 8):
        lap, step = divmod(offset, len(ring_points))
        progress = step / len(ring_points)
        eased = progress * progress * (3 - 2 * progress)
        pace = paces[lap] + (paces[(lap + 1) % len(paces)] - paces[lap]) * eased
        duration = round(pace + 84 * math.sin(math.tau * progress))
        step_durations.append(max(280, min(700, duration)))

    loading = []
    loading_durations = []

    def blade(index: int) -> list[int]:
        leading = ring_points[index % len(ring_points)]
        connector = connector_points[index % len(connector_points)]
        pixels = [0] * 64
        points = [(ring_points[(index - back) % len(ring_points)], level)
                  for back, level in ((1, 110), (2, 100), (3, 90))]
        points.extend(((leading, 190), (connector, 130)))
        for (row, column), level in points:
            pixels[row * 8 + column] = level
        return pixels

    for offset, duration in enumerate(step_durations):
        start = blade(offset)
        end = blade(offset + 1)
        for subframe in range(4):
            loading.append([round(a + (b - a) * subframe / 4) for a, b in zip(start, end)])
            loading_durations.append(duration // 4 + (subframe < duration % 4))

    waiting_patterns = [
        ("........", "........", "........", "........", "##......", "........", "........", "........"),
        ("........", "........", "........", "........", "##.##...", "........", "........", "........"),
        ("........", "........", "........", "........", "##.##.##", "........", "........", "........"),
        ("........", "........", "........", "........", "........", "........", "........", "........"),
    ]
    busy_patterns = [
        pattern("########", ".######.", "..####..", "...##...", "...##...", "..####..", ".######.", "########"),
        pattern("########", ".######.", "..####..", "...##...", "...##...", "...##...", ".######.", "########"),
        pattern("########", ".######.", "...##...", "...##...", "...##...", "..####..", ".######.", "########"),
        pattern("########", ".######.", "...##...", "..####..", "...##...", "..####..", ".######.", "########"),
    ]
    upload_base = pattern("...##...", "..###...", ".#####..", "...##...", "...##...", "...##...", "########", "........")
    download_base = pattern("...##...", "...##...", "...##...", "...##...", ".#####..", "..###...", "...##...", "########")

    def shift_y(pixels: list[int], amount: int) -> list[int]:
        shifted = [0] * 64
        for row in range(8):
            for column in range(8):
                shifted[((row + amount) % 8) * 8 + column] = pixels[row * 8 + column]
        return shifted

    def shift_x(pixels: list[int], amount: int) -> list[int]:
        shifted = [0] * 64
        for row in range(8):
            for column in range(8):
                shifted[row * 8 + (column + amount) % 8] = pixels[row * 8 + column]
        return shifted

    sync_patterns = [
        pattern("..####..", ".######.", "##....##", "##.###..", "..###.##", "##....##", ".######.", "..####.."),
        pattern("..####..", ".######.", "##....##", "##....##", "..######", "##....##", ".######.", "..####.."),
        pattern("..####..", ".######.", "##....##", "..###.##", "##.###..", "##....##", ".######.", "..####.."),
        pattern("..####..", ".######.", "##....##", "##....##", "##.###..", "##....##", ".######.", "..####.."),
    ]
    connecting = [
        pattern("........", "........", "........", "........", "...##...", "........", "........", "........"),
        pattern("........", "........", "........", "........", "..####..", "...##...", "........", "........"),
        pattern("........", ".######.", ".######.", "##....##", "...##...", "..####..", "...##...", "........"),
        pattern("........", "..####..", ".######.", "##....##", "...##...", "..####..", "...##...", "........"),
    ]
    battery = [
        pattern("........", ".######.", ".#....#.", ".#....##", ".#....##", ".#....#.", ".######.", "........"),
        pattern("........", ".######.", ".##...#.", ".##...##", ".##...##", ".##...#.", ".######.", "........"),
        pattern("........", ".######.", ".###..#.", ".###..##", ".###..##", ".###..#.", ".######.", "........"),
        pattern("........", ".######.", ".######.", ".#######", ".#######", ".######.", ".######.", "........"),
    ]
    bell = pattern("...##...", "..####..", ".######.", ".######.", "########", "...##...", "...##...", "..####..")
    bell_on = overlay(bell, pattern(".#....#.", "........", "........", "........", "........", "........", "........", "........"))
    face = pattern("........", ".##..##.", ".##..##.", "........", "#......#", ".#....#.", "..####..", "........")
    smile_closed = pattern("........", "........", ".##..##.", "........", "#......#", ".#....#.", "..####..", "........")
    wink = pattern("........", ".##.....", ".##..##.", "........", "#......#", ".#....#.", "..####..", "........")
    happy = pattern("........", ".##..##.", ".##..##.", "........", "..####..", ".##..##.", ".##..##.", "..####..")
    surprised = pattern("........", ".##..##.", ".##..##.", "........", "...##...", "..####..", "...##...", "........")
    sleepy = pattern("........", "........", ".######.", "........", "...##...", "..####..", "........", "........")
    heart_small = pattern("........", "..#..#..", ".######.", "..####..", "...##...", "........", "........", "........")
    heart_big = pattern(".##..##.", "###..###", "########", ".######.", "..####..", "...##...", "........", "........")
    return {
        "loading": ("加载", loading, loading_durations, "cyan"),
        "waiting": ("等待", [pattern(*rows) for rows in waiting_patterns], [300] * 4, "yellow"),
        "busy": ("忙碌", busy_patterns, [400] * 4, "orange"),
        "upload": ("上传", [shift_y(upload_base, -offset) for offset in range(8)], [100] * 8, "green"),
        "download": ("下载", [shift_y(download_base, offset) for offset in range(8)], [100] * 8, "blue"),
        "sync": ("同步", sync_patterns, [300] * 4, "purple"),
        "connecting": ("连接中", connecting, [300] * 4, "cyan"),
        "charging": ("充电", battery, [450] * 4, "yellow"),
        "notification": ("通知", [bell, shift_x(bell_on, -1), shift_x(bell_on, 1), bell], [250] * 4, "pink"),
        "smile": ("微笑", [face, smile_closed], [3800, 200], "yellow"),
        "happy": ("开心", [happy, face], [900, 300], "green"),
        "wink": ("眨眼", [face, wink], [2800, 200], "orange"),
        "surprised": ("惊讶", [face, surprised, face, surprised], [400] * 4, "pink"),
        "sleepy": ("困倦", [face, sleepy], [2400, 600], "blue"),
        "heart": ("心形", [heart_small, heart_big, heart_small, heart_big], [200, 200, 200, 600], "red"),
    }


def icon_records() -> dict[str, dict]:
    records = {}
    for icon_id, label, color_name in STATIC_SPECS:
        pixels = pattern(*STATIC_PATTERNS[icon_id])
        records[icon_id] = {
            "label": label,
            "color": COLORS[color_name],
            "period_ms": 1000,
            "static_frame": 0,
            "frames": [{"duration_ms": 1000, "pixels": pixels}],
        }
    for icon_id, (label, frames, durations, color_name) in animate_patterns().items():
        records[icon_id] = {
            "label": label,
            "color": COLORS[color_name],
            "period_ms": sum(durations),
            "static_frame": 0,
            "frames": [
                {"duration_ms": duration, "pixels": pixels}
                for duration, pixels in zip(durations, frames)
            ],
        }
    return records


def example_specs() -> list[dict]:
    """Protocol requests and sample cadence for gallery GIFs."""

    show = lambda icon, **extra: {"id": 1, "op": "show", "icon": icon, **extra}
    specs = [
        ("rainbow_cycle", "彩虹循环", "effect", show("loading", animation={"enabled": False}, color={"mode": "rainbow_cycle", "period_ms": 1200}), [100] * 12, 0),
        ("rainbow_flow", "彩虹流动", "effect", show("loading", animation={"enabled": False}, color={"mode": "rainbow_flow", "period_ms": 1200}), [100] * 12, 0),
        ("breathe", "呼吸", "effect", show("heart", animation={"enabled": False}, color={"mode": "solid", "values": ["cyan"]}, effect={"type": "breathe", "period_ms": 1200}), [200] * 6, 0),
        ("alternate", "交替", "effect", show("heart", animation={"enabled": False}, color={"mode": "solid", "values": ["white"]}, effect={"type": "alternate", "period_ms": 1200}), [300] * 4, 0),
        ("blink", "闪烁", "effect", show("heart", animation={"enabled": False}, color={"mode": "solid", "values": ["white"]}, effect={"type": "blink", "period_ms": 1000}), [250] * 4, 0),
        ("loading_rainbow_breathe", "彩虹呼吸加载", "combo", show("loading", color={"mode": "rainbow_flow", "period_ms": 1200}, effect={"type": "breathe", "period_ms": 1200}), [200] * 6, 0),
    ]
    for asset_id, text in (("text_100", "100%"), ("text_007", "007"), ("text_3_14", "3.14"), ("text_hello", "HELLO"), ("text_25_left", "25% LEFT")):
        command = {"id": 1, "op": "text", "text": text, "scroll": {"mode": "always", "direction": "left", "step_ms": 180, "repeat": 0}}
        specs.append((asset_id, text, "text", command, [80] * (len(text) * 6 + 10), 640))
    specs.append(("pet", "桌宠节奏示意", "pet", {"id": 1, "op": "idle", "mode": "pet"}, [100] * 994, 0))
    return [
        {"id": asset_id, "label": label, "kind": kind, "command": command, "durations": durations, "poster_time": poster_time}
        for asset_id, label, kind, command, durations, poster_time in specs
    ]


def manifest(specs: list[dict]) -> dict:
    return {"version": 1, "examples": [
        {"id": spec["id"], "label": spec["label"], "file": f"assets/{spec['id']}.gif", "kind": spec["kind"],
         "command": spec["command"], "poster": f"assets/{spec['id']}.png"}
        for spec in specs
    ]}


def c_values(values: list[int], per_line: int = 16) -> str:
    chunks = [values[index:index + per_line] for index in range(0, len(values), per_line)]
    return ",\n    ".join(", ".join(f"{value}" for value in chunk) for chunk in chunks)


def c_hex_values(values: list[int]) -> str:
    return ", ".join(f"0x{value:02X}" for value in values)


def c_identifier(icon_id: str) -> str:
    return "ICON_" + "".join(character if character.isalnum() else "_" for character in icon_id.upper())


def write_contact_sheets(records: dict[str, dict], asset_manifest: dict) -> None:
    """Write compact visual QA sheets from the final hardware-rendered assets."""

    card_width, card_height, columns = 120, 94, 8
    icon_ids = list(records)
    rows = math.ceil(len(icon_ids) / columns)
    sheet = Image.new("RGB", (card_width * columns, card_height * rows), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for index, icon_id in enumerate(icon_ids):
        x = (index % columns) * card_width
        y = (index // columns) * card_height
        with Image.open(ASSET_DIR / f"{icon_id}.png") as source:
            preview = source.convert("RGB").resize((64, 64), Image.Resampling.NEAREST)
        sheet.paste(preview, (x + (card_width - 64) // 2, y + 3))
        draw.text((x + 4, y + 70), icon_id, fill=(255, 255, 255))
    draw.text((4, 1), "BlinkTile icons | preview brightness 85%", fill=(180, 180, 180))
    sheet.save(ASSET_DIR / "contact-sheet.png", format="PNG", optimize=False)

    animation_ids = [icon_id for icon_id, record in records.items() if len(record["frames"]) > 1]
    animation_ids.extend(example["id"] for example in asset_manifest["examples"])
    tile, label_width, strip_height, max_frames = 20, 170, 34, 6
    strip = Image.new("RGB", (label_width + tile * max_frames, strip_height * len(animation_ids)), (0, 0, 0))
    draw = ImageDraw.Draw(strip)
    for row, asset_id in enumerate(animation_ids):
        path = ASSET_DIR / f"{asset_id}.gif"
        with Image.open(path) as source:
            count = source.n_frames
            indices = [round(index * (count - 1) / max(1, max_frames - 1)) for index in range(max_frames)]
            draw.text((4, row * strip_height + 9), asset_id, fill=(255, 255, 255))
            for frame_index, source_index in enumerate(indices):
                source.seek(source_index)
                frame = source.convert("RGB").resize((16, 16), Image.Resampling.NEAREST)
                strip.paste(frame, (label_width + frame_index * tile + 2, row * strip_height + 8))
    draw.text((4, 1), "Animation samples | preview brightness 85%", fill=(180, 180, 180))
    strip.save(ASSET_DIR / "animation-strip.png", format="PNG", optimize=False)


def write_firmware(records: dict[str, dict], font: dict[str, list[int]]) -> None:
    lines = [
        "#ifndef ICONSHOW_ASSETS_H",
        "#define ICONSHOW_ASSETS_H",
        "",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        "typedef struct {",
        "    const char* id;",
        "    uint32_t color;",
        "    uint32_t period;",
        "    uint16_t frameCount;",
        "    const uint8_t* pixels;",
        "    const uint16_t* durations;",
        "    uint8_t staticFrame;",
        "} IconDef;",
        "",
    ]
    for icon_id, record in records.items():
        identifier = c_identifier(icon_id)
        flat_pixels = [pixel for frame in record["frames"] for pixel in frame["pixels"]]
        durations = [frame["duration_ms"] for frame in record["frames"]]
        lines.extend([
            f"static const uint8_t {identifier}_PIXELS[{len(flat_pixels)}] = {{",
            f"    {c_values(flat_pixels)}",
            "};",
            f"static const uint16_t {identifier}_DURATIONS[{len(durations)}] = {{ {c_hex_values(durations)} }};",
            "",
        ])
    lines.extend(["const IconDef ICONS[] = {"])
    for icon_id, record in records.items():
        identifier = c_identifier(icon_id)
        lines.append(
            f'    {{"{icon_id}", 0x{int(record["color"][1:], 16):06X}u, {record["period_ms"]}u, '
            f'{len(record["frames"])}u, {identifier}_PIXELS, {identifier}_DURATIONS, {record["static_frame"]}u}},'
        )
    lines.extend(["};", "const size_t ICON_COUNT = sizeof(ICONS) / sizeof(ICONS[0]);", "", "const uint8_t FONT[95][5] = {"])
    for code in range(0x20, 0x7F):
        character = chr(code)
        lines.append(f"    {{ {c_hex_values(font[character])} }}, /* 0x{code:02X} {character if character != ' ' else 'space'} */")
    lines.extend(["};", "", "#endif  /* ICONSHOW_ASSETS_H */", ""])
    (FIRMWARE_DIR / "assets.h").write_text("\n".join(lines), encoding="utf-8")


def validate(records: dict[str, dict], font: dict[str, list[int]], asset_manifest: dict) -> None:
    assert len(records) == 46, len(records)
    assert set(font) == {chr(code) for code in range(0x20, 0x7F)}
    assert not any(not any(values) for character, values in font.items() if character != " ")
    for record in records.values():
        assert record["period_ms"] == sum(frame["duration_ms"] for frame in record["frames"])
        for frame in record["frames"]:
            assert len(frame["pixels"]) == 64
            assert all(0 <= pixel <= 255 for pixel in frame["pixels"])
    assert len(asset_manifest["examples"]) == 12
    assert all(isinstance(example["command"], dict) and "op" in example["command"] for example in asset_manifest["examples"])
    for icon_id in records:
        native = Image.open(ASSET_DIR / f"{icon_id}.png")
        preview = Image.open(ASSET_DIR / f"{icon_id}-preview.png")
        animation = Image.open(ASSET_DIR / f"{icon_id}.gif")
        assert native.size == (8, 8)
        assert preview.size == (64, 64)
        assert animation.size == (8, 8)
        assert sum(1 for _ in ImageSequence.Iterator(animation)) == len(records[icon_id]["frames"])
        native.close()
        preview.close()
        animation.close()
    for example in asset_manifest["examples"]:
        image = Image.open(ROOT / "web" / example["file"])
        assert image.size == (8, 8)
        image.close()
    for sheet in (ASSET_DIR / "contact-sheet.png", ASSET_DIR / "animation-strip.png"):
        with Image.open(sheet) as image:
            assert image.width > 0 and image.height > 0


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    records = icon_records()
    font = font_bytes()
    specs = example_specs()
    asset_manifest = manifest(specs)

    (DATA_DIR / "icons.json").write_text(
        json.dumps({"colors": COLORS, "icons": records, "font": font}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (ASSET_DIR / "manifest.json").write_text(json.dumps(asset_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_firmware(records, font)

    data_js = json.dumps({"colors": COLORS, "icons": records, "font": font}, ensure_ascii=False, separators=(",", ":"))
    manifest_js = json.dumps(asset_manifest, ensure_ascii=False, separators=(",", ":"))
    (WEB_DIR / "data.js").write_text(
        "// Generated by tools/generate_assets.py.\n"
        f"globalThis.IconData = {data_js};\n"
        f"globalThis.AssetManifest = {manifest_js};\n",
        encoding="utf-8",
    )

    for icon_id, record in records.items():
        durations = [frame["duration_ms"] for frame in record["frames"]]
        times = [sum(durations[:index]) for index in range(len(durations))]
        frames = engine_frames([{"id": 1, "op": "show", "icon": icon_id}], times)
        poster = frames[record["static_frame"]]
        save_png(poster, ASSET_DIR / f"{icon_id}.png")
        save_png(poster, ASSET_DIR / f"{icon_id}-preview.png", size=64)
        save_gif(frames, durations, ASSET_DIR / f"{icon_id}.gif")

    for spec in specs:
        durations = spec["durations"]
        times = [sum(durations[:index]) for index in range(len(durations))]
        frames = engine_frames([spec["command"]], times)
        save_gif(frames, durations, ASSET_DIR / f"{spec['id']}.gif")
        save_png(engine_frames([spec["command"]], [spec["poster_time"]])[0], ASSET_DIR / f"{spec['id']}.png")
    write_contact_sheets(records, asset_manifest)
    validate(records, font, asset_manifest)
    print(f"generated {len(records)} icons, {len(asset_manifest['examples'])} example assets, and 95 font glyphs")


if __name__ == "__main__":
    main()
