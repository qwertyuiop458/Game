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


def _stub_trace(level_index: int, _tables: dict) -> SimpleNamespace:
    return SimpleNamespace(level_index=level_index, script_chunk=10 + level_index, chapter=level_index, map_subchunk=0)


def test_build_chapter_matrix_uses_dynamic_m6_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(linker, 'JarProject', _JarProjectStub)
    monkeypatch.setattr(linker, 'parse_m9_chunk_tables', lambda payloads: {'chunk0_levels': {'levels': []}})
    monkeypatch.setattr(linker, 'parse_script_chunk_semantic', lambda payload: {'commands': []})
    monkeypatch.setattr(linker, 'resolve_level_trace', _stub_trace)

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
    assert set(payload['cross_check']['valid_confidence_totals']) == {'direct', 'inferred', 'unknown'}
    for chapter_row in payload['chapters']:
        for entry in chapter_row['direct_refs'] + chapter_row['inferred_refs']:
            assert entry['confidence'] in {'direct', 'inferred', 'unknown'}

    conflicts_path = tmp_path / 'docs' / 'reverse_engineering' / 'link_conflicts.json'
    conflicts_payload = json.loads(conflicts_path.read_text(encoding='utf-8'))
    assert set(conflicts_payload) == {'conflicts', 'summary'}
    assert conflicts_payload['summary'] == payload['cross_check']['conflict_summary']


def test_link_conflicts_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(linker, 'JarProject', _JarProjectStub)
    monkeypatch.setattr(linker, 'parse_m9_chunk_tables', lambda payloads: {'chunk0_levels': {'levels': []}})
    monkeypatch.setattr(linker, 'parse_script_chunk_semantic', lambda payload: {'commands': []})
    monkeypatch.setattr(linker, 'resolve_level_trace', _stub_trace)

    matrix = linker.build_chapter_matrix(tmp_path / 'dummy.jar', tmp_path)
    assert matrix['link_conflicts'] == []
    assert matrix['cross_check']['conflict_summary']['total_conflicts'] == 0
    assert matrix['linker_conflicts_summary'] == {'total_conflicts': 0, 'blocking_conflicts': 0, 'conflicts': []}
    assert set(matrix['cross_check']['valid_confidence_totals']) == {'direct', 'inferred', 'unknown'}
    assert all(value >= 0 for value in matrix['cross_check']['valid_confidence_totals'].values())


def test_link_conflicts_single(tmp_path: Path, monkeypatch) -> None:
    def _single_conflict_trace(level_index: int, _tables: dict) -> SimpleNamespace:
        chapter = 1 if level_index == 0 else level_index
        return SimpleNamespace(level_index=level_index, script_chunk=10 + level_index, chapter=chapter, map_subchunk=0)

    monkeypatch.setattr(linker, 'JarProject', _JarProjectStub)
    monkeypatch.setattr(linker, 'parse_m9_chunk_tables', lambda payloads: {'chunk0_levels': {'levels': []}})
    monkeypatch.setattr(linker, 'parse_script_chunk_semantic', lambda payload: {'commands': []})
    monkeypatch.setattr(linker, 'resolve_level_trace', _single_conflict_trace)

    matrix = linker.build_chapter_matrix(tmp_path / 'dummy.jar', tmp_path)
    assert len(matrix['link_conflicts']) == 1
    conflict = matrix['link_conflicts'][0]
    assert conflict['entity'] == 'chapter_0'
    assert conflict['conflict_type'] == 'chapter_target_mismatch'


def test_link_conflicts_multiple_same_type(tmp_path: Path, monkeypatch) -> None:
    def _multi_conflict_trace(level_index: int, _tables: dict) -> SimpleNamespace:
        chapter = (level_index + 1) % 4
        return SimpleNamespace(level_index=level_index, script_chunk=10 + level_index, chapter=chapter, map_subchunk=0)

    monkeypatch.setattr(linker, 'JarProject', _JarProjectStub)
    monkeypatch.setattr(linker, 'parse_m9_chunk_tables', lambda payloads: {'chunk0_levels': {'levels': []}})
    monkeypatch.setattr(linker, 'parse_script_chunk_semantic', lambda payload: {'commands': []})
    monkeypatch.setattr(linker, 'resolve_level_trace', _multi_conflict_trace)

    matrix = linker.build_chapter_matrix(tmp_path / 'dummy.jar', tmp_path)
    assert len(matrix['link_conflicts']) == 4
    assert {item['conflict_type'] for item in matrix['link_conflicts']} == {'chapter_target_mismatch'}
    assert matrix['cross_check']['conflict_summary']['by_type']['chapter_target_mismatch'] == 4
