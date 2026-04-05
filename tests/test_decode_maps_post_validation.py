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

    validation = bundle['collision_validation']
    assert validation['summary']['maps_validation_failed'] >= 1
    validation_report = json.loads((output_dir / 'extracted' / 'maps' / 'collision_validation.json').read_text(encoding='utf-8'))
    assert any(
        entry['severity'] == 'error'
        and entry['pack'] == 'm6_0'
        and entry['chunk'] == 99
        and 'out of bounds' in entry['message'].lower()
        for entry in validation_report['entries']
    )


def test_decode_maps_validation_passes_without_mismatch(tmp_path: Path) -> None:
    tile_chunk = (1).to_bytes(2, 'little') + (2).to_bytes(2, 'little')
    collision_chunk = bytes([0, 1])

    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m6_0', _make_container(tile_chunk, collision_chunk))

    output_dir = tmp_path / 'out'
    bundle = decode_maps(jar_path, output_dir)

    validation = bundle['collision_validation']
    assert validation['entries'] == []
    assert validation['summary'] == {'maps_validation_passed': 1, 'maps_validation_failed': 0}
