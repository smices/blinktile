#!/usr/bin/env python3
"""Check the deliverable files, not just the generator's in-memory data."""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / 'data/icons.json').read_text())
assert set(data['font']) == {chr(n) for n in range(32, 127)}, 'ASCII coverage'
assert all(len(cols) == 5 and all(0 <= n < 128 for n in cols) for cols in data['font'].values())
assert all(any(cols) for char, cols in data['font'].items() if char != ' '), 'Printable glyph rendered blank'
assert data['font']['a'] != data['font']['A'], 'Lowercase must remain lowercase'
required = {'loading', 'waiting', 'upload', 'download', 'smile', 'wink', 'heart', 'success', 'error'}
assert required <= data['icons'].keys()
loading = data['icons']['loading']['frames']
assert len(loading) == 8 * 12 * 4, 'loading should have four subframes per logical step'
loading_durations = [frame['duration_ms'] for frame in loading]
assert data['icons']['loading']['period_ms'] == 43_609
step_durations = [sum(loading_durations[i:i + 4]) for i in range(0, len(loading_durations), 4)]
assert all(max(loading_durations[i:i + 4]) - min(loading_durations[i:i + 4]) <= 1
           for i in range(0, len(loading_durations), 4)), 'subframes should evenly divide each step'
loading_laps = [sum(step_durations[i:i + 12]) for i in range(0, len(step_durations), 12)]
assert min(step_durations) >= 280 and max(step_durations) <= 700
assert all(max(step_durations[i:i + 12]) - min(step_durations[i:i + 12]) >= 100
           for i in range(0, len(step_durations), 12)), 'each orbit should have a visible speed range'
assert max(loading_laps) - min(loading_laps) >= 2_000, 'loading orbit periods should span at least 2 seconds'
assert max(abs(step_durations[i] - step_durations[(i + 1) % len(step_durations)])
           for i in range(len(step_durations))) <= 100, 'loading speed should change smoothly at every step'
loading_ring = [(1, 3), (1, 4), (2, 5), (3, 6), (4, 6), (5, 5),
                (6, 4), (6, 3), (5, 2), (4, 1), (3, 1), (2, 2)]
loading_connectors = [(2, 3), (2, 4), (3, 4), (3, 5), (4, 5), (4, 4),
                       (5, 4), (5, 3), (4, 3), (4, 2), (3, 2), (3, 3)]
assert all(max(abs(ring[0] - connector[0]), abs(ring[1] - connector[1])) == 1
           for ring, connector in zip(loading_ring, loading_connectors)), \
    'each connector should neighbor its outer ring point'
ring_indices = [row * 8 + column for row, column in loading_ring]
connector_indices = [row * 8 + column for row, column in loading_connectors]

def blade(step):
    pixels = [0] * 64
    for back, level in ((1, 110), (2, 100), (3, 90), (0, 190)):
        index = (step - back) % len(ring_indices)
        pixels[ring_indices[index]] = level
    pixels[connector_indices[step % len(connector_indices)]] = 130
    return pixels

loading_max_lit = 0
loading_totals = []
for offset, frame in enumerate(loading):
    lit = {index for index, pixel in enumerate(frame['pixels']) if pixel}
    step, subframe = divmod(offset, 4)
    start, end = blade(step), blade(step + 1)
    expected = [round(a + (b - a) * subframe / 4) for a, b in zip(start, end)]
    assert frame['pixels'] == expected, 'loading should move the leading point, trailing arc, and connector together'
    loading_max_lit = max(loading_max_lit, len(lit))
    loading_totals.append(sum(frame['pixels']))
    assert min(frame['pixels'][index] for index in lit) >= 20, 'loading should avoid dim transition pixels'
assert loading_max_lit == 7, 'four-point arc and connector handoff should peak at seven lit pixels'
assert max(loading_totals) - min(loading_totals) <= 4, 'loading blade brightness should stay stable'
assert loading[0]['pixels'][ring_indices[0]] == 190
assert [loading[0]['pixels'][ring_indices[index]] for index in (11, 10, 9)] == [110, 100, 90]
assert loading[0]['pixels'][connector_indices[0]] == 130
for name in ('upload', 'download', 'waiting', 'smile', 'wink'):
    masks = {tuple(p > 0 for p in f['pixels']) for f in data['icons'][name]['frames']}
    assert len(masks) > 1, f'{name}: brightness-only pulsing is not a shape animation'
for name in ('smile', 'wink'):
    durations = [f['duration_ms'] for f in data['icons'][name]['frames']]
    assert max(durations) >= 5 * min(durations), f'{name}: blink needs a long open-eye dwell'
for name in ('loading', 'upload', 'download'):
    frames = [f['pixels'] for f in data['icons'][name]['frames']]
    changes = [sum(abs(a-b) for a, b in zip(frames[i], frames[(i+1) % len(frames)]))
               for i in range(len(frames))]
    assert changes[-1] <= max(changes[:-1]), f'{name}: loop seam jumps farther than normal frames'
assert data['icons']['success']['frames'][0]['pixels'] != data['icons']['arrow_up']['frames'][0]['pixels']
animated = 0
for name, icon in data['icons'].items():
    assert icon['period_ms'] == sum(f['duration_ms'] for f in icon['frames']), name
    assert 0 <= icon['static_frame'] < len(icon['frames']), name
    for frame in icon['frames']:
        assert len(frame['pixels']) == 64, name
        assert all(isinstance(p, int) and 0 <= p <= 255 for p in frame['pixels']), name
        assert frame['duration_ms'] >= 20, name
    with Image.open(ROOT / 'web/assets' / f'{name}.png') as image:
        assert image.size == (8, 8), name
        pixels = list(image.convert('RGB').get_flattened_data())
        expected = icon['frames'][icon['static_frame']]['pixels']
        assert [any(rgb) for rgb in pixels] == [p > 0 for p in expected], name
    with Image.open(ROOT / 'web/assets' / f'{name}-preview.png') as image:
        assert image.width == image.height and image.width % 8 == 0, name
    if len(icon['frames']) > 1:
        animated += 1
        with Image.open(ROOT / 'web/assets' / f'{name}.gif') as image:
            assert image.n_frames > 1, name
            assert image.info.get('loop') == 0, name
            elapsed = 0
            for index in range(image.n_frames):
                image.seek(index)
                elapsed += image.info.get('duration', 0)
            assert abs(elapsed - icon['period_ms']) <= len(icon['frames']) * 10, (name, elapsed)
gifs = list((ROOT / 'web/assets').glob('*.gif'))
assert len(gifs) >= animated + 10, 'Missing effect/text/pet GIF examples'
for path in gifs:
    with Image.open(path) as image:
        static = path.stem in data['icons'] and len(data['icons'][path.stem]['frames']) == 1
        assert static or image.n_frames > 1, path.name
        for frame in range(image.n_frames):
            image.seek(frame)
            image.load()
            assert image.info.get('duration', 0) >= 20, path.name
print(f'PASS assets: {len(data["icons"])} icons, 95 glyphs, {len(gifs)} decoded GIFs')
