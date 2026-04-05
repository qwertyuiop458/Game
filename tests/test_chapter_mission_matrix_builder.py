from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.decode_maps import build_chapter_mission_matrix


class _ProjectStub:
    def __init__(self) -> None:
        self.containers = {
            **{f'm6_{idx}': SimpleNamespace(payloads=[b'a', b'b']) for idx in range(6)},
            'm9': SimpleNamespace(payloads=[b'x'] * 20),
            'm13_1': SimpleNamespace(payloads=[b'x'] * 4),
            'm13_2': SimpleNamespace(payloads=[b'x'] * 4),
            'm3_0': SimpleNamespace(payloads=[b'x']),
            'm4_0': SimpleNamespace(payloads=[b'x']),
            't0': SimpleNamespace(payloads=[b'x'] * 6),
        }


def test_build_chapter_mission_matrix_exports_and_validates(tmp_path: Path) -> None:
    output = tmp_path
    text_dir = output / 'extracted' / 'text'
    text_dir.mkdir(parents=True)
    for idx in range(6):
        (text_dir / f't0_{idx:02d}_full.txt').write_text(
            f'chapter {idx} zombie laboratory final fight',
            encoding='utf-8',
        )

    maps_report = {f'm6_{idx}': {'map_count': 1} for idx in range(6)}
    script_report = {
        'm9': {
            'chapter_mission_links': {
                'mission_links': [
                    {'chapter': idx, 'mission': idx, 'script_chunk': 10 + idx}
                    for idx in range(6)
                ]
            }
        }
    }
    graphics_report = {'containers': {'m3_0': {'chunks': [{'chunk': 0}]}, 'm4_0': {'chunks': [{'chunk': 0}]}}}
    audio_report = {
        'midi': ['extracted/audio/m13_1/00.mid', 'extracted/audio/m13_2/01.mid'],
        'raw_audio': [{'path': 'extracted/audio/m13_1/02.bin'}],
    }
    text_report = {
        'chunks': [
            {'chunk_index': idx, 'path': f'extracted/text/t0_{idx:02d}_full.txt'}
            for idx in range(6)
        ]
    }

    rows = build_chapter_mission_matrix(
        _ProjectStub(),
        output,
        maps_report,
        script_report,
        graphics_report,
        audio_report,
        text_report,
    )

    assert len(rows) == 6
    assert all('audio assets' in row for row in rows)
    assert all('validation' in row for row in rows)

    json_path = output / 'extracted' / 'meta' / 'chapter_mission_matrix.json'
    md_path = output / 'extracted' / 'meta' / 'chapter_mission_matrix.md'
    assert json_path.exists()
    assert md_path.exists()

    payload = json.loads(json_path.read_text(encoding='utf-8'))
    assert payload[0]['graphics pack'] == 'm3_0, m4_0'
