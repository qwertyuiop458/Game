from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.decode_audio_m13 import decode_audio


def _make_midi(track_count: int = 1) -> bytes:
    header = b'MThd' + (6).to_bytes(4, 'big') + (0).to_bytes(2, 'big') + track_count.to_bytes(2, 'big') + (96).to_bytes(2, 'big')
    track = b'MTrk' + (4).to_bytes(4, 'big') + b'\x00\xff\x2f\x00'
    return header + track


def test_decode_audio_tracks_valid_invalid_and_raw(monkeypatch, tmp_path: Path) -> None:
    jar = tmp_path / 'dummy.jar'
    jar.write_bytes(b'')

    valid_midi = _make_midi(track_count=1)
    invalid_midi_no_tracks = b'MThd' + (6).to_bytes(4, 'big') + (0).to_bytes(2, 'big') + (0).to_bytes(2, 'big') + (96).to_bytes(2, 'big')
    raw_chunk = b'\x01\x02\x03\x04'

    class FakeProject:
        def __init__(self, _jar_path: Path, _out_path: Path) -> None:
            self.containers = {
                'm13_1': SimpleNamespace(payloads=[valid_midi, invalid_midi_no_tracks]),
                'm13_2': SimpleNamespace(payloads=[raw_chunk]),
            }

        def load(self) -> None:
            return None

    monkeypatch.setattr('tools.decode_audio_m13.JarProject', FakeProject)

    report = decode_audio(jar, tmp_path)

    assert report['counts'] == {'valid_midi': 1, 'invalid_midi': 1, 'raw_audio': 1}
    assert len(report['midi']) == 1
    assert len(report['invalid_midi']) == 1
    assert len(report['raw_audio']) == 1

    invalid_meta = tmp_path / report['invalid_midi'][0]['meta']
    invalid_payload = json.loads(invalid_meta.read_text(encoding='utf-8'))
    assert invalid_payload['kind'] == 'invalid_midi'
    assert invalid_payload['reason'] == 'invalid_track_count:0'

    index_payload = json.loads((tmp_path / 'extracted' / 'audio' / 'index.json').read_text(encoding='utf-8'))
    assert index_payload['counts'] == report['counts']
