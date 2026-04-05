from __future__ import annotations

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


def test_decode_maps_keeps_pipeline_alive_and_reports_broken_refs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        'tools.decode_maps.parse_m8_chunk_semantic',
        lambda _chunk: {
            'commands': [{'map_refs': [{'pack': 'm6_0', 'subchunk': 99}], 'triggers': [], 'object_placements': []}],
            'opcode_histogram': {},
        },
    )

    tile_chunk = (1).to_bytes(2, 'little') + (2).to_bytes(2, 'little')
    collision_chunk = bytes([0, 1])
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m6_0', _make_container(tile_chunk, collision_chunk))
        zf.writestr('m8', _make_container(b'\x00'))

    output_dir = tmp_path / 'out'
    bundle = decode_maps(jar_path, output_dir)

    assert bundle['mismatch_report']['counts']['error'] >= 1
    mismatch_report = json.loads((output_dir / 'extracted' / 'maps' / 'mismatch_report.json').read_text(encoding='utf-8'))
    assert any(
        entry['check_name'] == 'out_of_range_layer_index' and entry['severity'] == 'error'
        for entry in mismatch_report['entries']
    )
