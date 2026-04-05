from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import linker


class _JarProjectStub:
    def __init__(self, jar: Path, output: Path) -> None:
        self.jar = jar
        self.output = output
        self.containers = {
            **{f'm6_{idx}': SimpleNamespace(payloads=[b'a', b'b']) for idx in range(4)},
            'm8': SimpleNamespace(payloads=[b'x'] * 20),
            'm9': SimpleNamespace(payloads=[b'x'] * 20),
            'm13_1': SimpleNamespace(payloads=[b'MThd', b'raw', b'MThd', b'raw']),
            'm13_2': SimpleNamespace(payloads=[b'raw', b'MThd', b'raw', b'MThd']),
            'm3_0': SimpleNamespace(payloads=[b'g']),
            'm4_0': SimpleNamespace(payloads=[b'g']),
            'm11_0': SimpleNamespace(payloads=[b'g']),
            'm11_1': SimpleNamespace(payloads=[b'g']),
        }

    def load(self) -> None:
        return None


def test_build_chapter_matrix_uses_dynamic_m6_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(linker, 'JarProject', _JarProjectStub)
    monkeypatch.setattr(linker, 'parse_m9_chunk_tables', lambda payloads: {'chunk0_levels': {'levels': []}})
    monkeypatch.setattr(linker, 'parse_script_chunk_semantic', lambda payload: {'commands': []})
    monkeypatch.setattr(
        linker,
        'resolve_level_trace',
        lambda level_index, tables: SimpleNamespace(level_index=level_index, script_chunk=10 + level_index, chapter=level_index, map_subchunk=0),
    )

    matrix = linker.build_chapter_matrix(tmp_path / 'dummy.jar', tmp_path)
    chapters = matrix['chapters']
    assert len(chapters) == 4
    assert [row['chapter'] for row in chapters] == [0, 1, 2, 3]
    assert all(row['maps'][0]['map_chunk'].startswith(f"m6_{row['chapter']}#") for row in chapters)

    json_path = tmp_path / 'docs' / 'reverse_engineering' / 'chapter_matrix.json'
    payload = json.loads(json_path.read_text(encoding='utf-8'))
    assert len(payload['chapters']) == 4
    assert 'conflicts' in payload
    assert 'conflict_summary' in payload['cross_check']

    conflicts_path = tmp_path / 'docs' / 'reverse_engineering' / 'linker_conflicts.json'
    conflicts_payload = json.loads(conflicts_path.read_text(encoding='utf-8'))
    assert set(conflicts_payload) == {'conflicts', 'summary'}
    assert conflicts_payload['summary'] == payload['cross_check']['conflict_summary']
