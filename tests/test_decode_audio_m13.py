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


def _build_midi(track_count: int, tracks: list[bytes]) -> bytes:
    header = b'MThd' + (6).to_bytes(4, 'big') + (0).to_bytes(2, 'big') + track_count.to_bytes(2, 'big') + (96).to_bytes(2, 'big')
    body = b''.join(b'MTrk' + len(track).to_bytes(4, 'big') + track for track in tracks)
    return header + body


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
    assert report['midi_validation_summary'] == {'total': 0, 'valid': 0, 'invalid': 0, 'warnings': 0}


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


def test_decode_audio_marks_valid_midi_status(tmp_path: Path) -> None:
    midi = _build_midi(track_count=1, tracks=[b'\x00\xff\x2f\x00'])
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(midi))

    report = decode_audio(jar_path, tmp_path / 'out')

    assert len(report['midi']) == 1
    assert report['midi_validation'][0]['status'] == 'valid'
    assert report['midi_validation'][0]['reason'] == 'ok'
    assert report['midi_validation_summary'] == {'total': 1, 'valid': 1, 'invalid': 0, 'warnings': 0}


def test_decode_audio_marks_corrupted_midi_header_invalid(tmp_path: Path) -> None:
    corrupted = b'MThd\x00\x00\x00\x06\x00'
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(corrupted))

    report = decode_audio(jar_path, tmp_path / 'out')

    assert len(report['midi']) == 1
    assert report['midi_validation'][0]['status'] == 'invalid'
    assert report['midi_validation'][0]['reason'] == 'midi_header_too_short'
    assert report['midi_validation_summary'] == {'total': 1, 'valid': 0, 'invalid': 1, 'warnings': 0}


def test_decode_audio_marks_track_count_mismatch_warning(tmp_path: Path) -> None:
    inconsistent = _build_midi(track_count=2, tracks=[b'\x00\xff\x2f\x00'])
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('m13_1', _make_container(inconsistent))

    report = decode_audio(jar_path, tmp_path / 'out')

    assert len(report['midi']) == 1
    assert report['midi_validation'][0]['status'] == 'warning'
    assert report['midi_validation'][0]['reason'].startswith('track_count_mismatch')
    assert report['midi_validation_summary'] == {'total': 1, 'valid': 0, 'invalid': 0, 'warnings': 1}
