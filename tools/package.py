#!/usr/bin/env python3
"""Package committed source, offline gallery and flashable bins; omit debug/build caches."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=ROOT).returncode:
    raise SystemExit('Commit verified source changes before packaging.')
tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
files = {name: ROOT / name for name in tracked if name and name != '.gitignore'}
for name in ('IconShow.ino.bin', 'IconShow.ino.bootloader.bin', 'IconShow.ino.partitions.bin', 'IconShow.ino.merged.bin'):
    path = ROOT / 'dist' / name
    if not path.is_file():
        raise SystemExit(f'Missing dist/{name}; run tools/build.sh first.')
    files['dist/' + name] = path
manifest = {'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), 'sha256': {}}
payloads = {}
for name, path in sorted(files.items()):
    data = path.read_bytes()
    if str(Path.home()).encode() in data:
        raise SystemExit(f'Local home path detected in {name}; do not distribute.')
    manifest['sha256'][name] = hashlib.sha256(data).hexdigest()
    payloads[name] = data
destination = ROOT / 'dist/IconShow-release.zip'
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name, data in payloads.items():
        archive.writestr('IconShow/' + name, data)
    archive.writestr('IconShow/release.json', json.dumps(manifest, indent=2) + '\n')
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
print(f'Packaged dist/{destination.name}: {len(files)} files, {destination.stat().st_size} bytes; checksums in release.json')
