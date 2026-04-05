from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tools.decode_audio_m13 import decode_audio


def _make_container(*chunks: bytes) -> bytes:
    header = bytearray([len(chunks)])
    cursor = 0
    payload = bytearray()
    for chunk in chunks:
        header.extend(cursor.to_bytes(4, 'little'))
        payload.extend(chunk)
        cursor += len(chunk)
    return bytes(header + payload)


def test_decode_audio_creates_raw_sidecar_and_signature_registry_for_non_midi_chunks(tmp_path: Path) -> None:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(b'\x00\x01\x02\x03', b'ABCD'))
        zf.writestr('m13_2', _make_container(b'\x10\x20\x30'))

    output_dir = tmp_path / 'out'
    report = decode_audio(jar_path, output_dir)

    assert report['midi'] == []
    assert len(report['raw_audio']) == 3
    assert report['stats'] == {'valid': 3, 'invalid': 0, 'raw': 3}

    for item in report['raw_audio']:
        raw_path = output_dir / item['path']
        sidecar_path = output_dir / item['meta']
        assert raw_path.exists()
        assert sidecar_path.exists()
        sidecar = json.loads(sidecar_path.read_text(encoding='utf-8'))
        assert 'size' in sidecar
        assert 'head_hex' in sidecar

    registry_path = output_dir / report['signature_registry']
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    assert len(registry) == 3
    assert all(item['kind'] == 'raw' for item in registry)
    assert all('sha1' in item and 'crc32_hex' in item for item in registry)


def test_decode_audio_swallows_chunk_errors_and_reports_invalid_stats(monkeypatch, tmp_path: Path) -> None:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(b'boom', b'ok'))

    output_dir = tmp_path / 'out'

    call_state = {'calls': 0}

    def _raise_once(_chunk: bytes) -> dict:
        call_state['calls'] += 1
        if call_state['calls'] == 1:
            raise RuntimeError('simulated decode failure')
        return {'size': 2, 'head_hex': '6f6b', 'nonzero_bytes': 2, 'top_bytes': [[111, 1], [107, 1]]}

    monkeypatch.setattr('tools.decode_audio_m13.analyse_audio_blob', _raise_once)

    report = decode_audio(jar_path, output_dir)

    assert report['stats'] == {'valid': 1, 'invalid': 1, 'raw': 1}
    assert len(report['invalid_audio']) == 1
    assert report['invalid_audio'][0]['container'] == 'm13_1'
    assert report['invalid_audio'][0]['chunk_index'] == 0
    assert 'simulated decode failure' in report['invalid_audio'][0]['error']

    assert len(report['raw_audio']) == 1
    assert (output_dir / report['raw_audio'][0]['path']).exists()
    assert (output_dir / report['raw_audio'][0]['meta']).exists()


def test_decode_audio_records_new_unsupported_signature(tmp_path: Path) -> None:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(b'\x01\x02\x03\x04\x05\x06'))

    output_dir = tmp_path / 'out'
    report = decode_audio(jar_path, output_dir)
    unsupported_path = output_dir / report['unsupported_signature_registry']
    unsupported = json.loads(unsupported_path.read_text(encoding='utf-8'))

    assert len(unsupported) == 1
    assert unsupported[0]['signature_hex'] == '010203040506'
    assert unsupported[0]['first_seen_pack'] == 'm13_1'
    assert unsupported[0]['chunk_index'] == 0
    assert unsupported[0]['length'] == 6


def test_decode_audio_does_not_duplicate_unsupported_signature(tmp_path: Path) -> None:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(b'\xaa\xbb\xcc', b'\xaa\xbb\xcc'))

    output_dir = tmp_path / 'out'
    report = decode_audio(jar_path, output_dir)
    unsupported_path = output_dir / report['unsupported_signature_registry']
    unsupported = json.loads(unsupported_path.read_text(encoding='utf-8'))

    assert len(unsupported) == 1
    assert unsupported[0]['signature_hex'] == 'aabbcc'


def test_decode_audio_unsupported_signature_report_has_expected_structure(tmp_path: Path) -> None:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_2', _make_container(b'\x00\xff\x7f\x80'))

    output_dir = tmp_path / 'out'
    report = decode_audio(jar_path, output_dir)
    unsupported_path = output_dir / report['unsupported_signature_registry']
    unsupported = json.loads(unsupported_path.read_text(encoding='utf-8'))

    assert isinstance(unsupported, list)
    assert len(unsupported) == 1
    assert set(unsupported[0].keys()) == {'signature_hex', 'first_seen_pack', 'chunk_index', 'length', 'notes'}
