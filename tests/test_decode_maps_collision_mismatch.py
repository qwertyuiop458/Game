from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from tools.decode_maps import decode_maps


def _make_container(*chunks: bytes) -> bytes:
    header = bytearray([len(chunks)])
    cursor = 0
    payload = bytearray()
    for chunk in chunks:
        header.extend(cursor.to_bytes(4, 'little'))
        payload.extend(chunk)
        cursor += len(chunk)
    return bytes(header + payload)


def test_decode_maps_marks_collision_size_mismatch_and_uses_collision_grid(tmp_path: Path) -> None:
    tile_values = [1, 2, 3, 4, 5, 6]
    tile_chunk = b''.join(value.to_bytes(2, 'little') for value in tile_values)
    collision_chunk = bytes([0, 1, 2, 3, 4])

    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m6_0', _make_container(tile_chunk, collision_chunk))

    output_dir = tmp_path / 'out'
    decode_maps(jar_path, output_dir)

    chunk_meta = json.loads((output_dir / 'extracted' / 'maps' / 'm6_0' / '00.json').read_text(encoding='utf-8'))
    assert chunk_meta['collision_size_mismatch'] is True
    assert chunk_meta['tile_cells'] == 6
    assert chunk_meta['collision_cells'] == 5

    collision_payload = json.loads((output_dir / 'extracted' / 'maps' / 'm6_0' / '00_collision.json').read_text(encoding='utf-8'))
    assert collision_payload['collision_size_mismatch'] is True
    assert collision_payload['tile_cells'] == 6
    assert collision_payload['collision_cells'] == 5
    assert collision_payload['width'] == 1
    assert collision_payload['height'] == 5

    with (output_dir / 'extracted' / 'maps' / 'm6_0' / '00_collision.csv').open(encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    assert rows[1]['index'] == '1'
    assert rows[1]['x'] == '0'
    assert rows[1]['y'] == '1'
