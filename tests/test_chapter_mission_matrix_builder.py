from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.decode_maps import build_chapter_mission_matrix, build_final_table
from tests.fixtures_mission_semantics import EXPECTED_MISSION_ROWS


class _ProjectStub:
    def __init__(self, chapter_count: int = 6) -> None:
        self.containers = {
            **{f'm6_{idx}': SimpleNamespace(payloads=[b'a', b'b']) for idx in range(chapter_count)},
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
    assert set(payload[0]['confidence_summary']) == {'direct', 'inferred', 'unknown'}
    assert all(link['confidence'] in {'direct', 'inferred', 'unknown'} for link in payload[0]['links'])
    markdown = md_path.read_text(encoding='utf-8')
    assert 'confidence' in markdown.splitlines()[0]


def test_chapter_counts_follow_m6_containers(tmp_path: Path) -> None:
    output = tmp_path
    text_dir = output / 'extracted' / 'text'
    text_dir.mkdir(parents=True)
    for idx in range(4):
        (text_dir / f't0_{idx:02d}_full.txt').write_text(
            f'chapter {idx} zombie laboratory final fight',
            encoding='utf-8',
        )

    project = _ProjectStub(chapter_count=4)
    maps_report = {f'm6_{idx}': {'map_count': 1} for idx in range(4)}
    script_report = {
        'm9': {
            'chapter_mission_links': {
                'mission_links': [
                    {'chapter': idx, 'mission': idx, 'script_chunk': 10 + idx}
                    for idx in range(4)
                ]
            }
        }
    }
    graphics_report = {'containers': {'m3_0': {'chunks': [{'chunk': 0}]}, 'm4_0': {'chunks': [{'chunk': 0}]}}}
    audio_report = {
        'midi': [f'extracted/audio/m13_1/{idx:02d}.mid' for idx in range(4)],
        'raw_audio': [{'path': f'extracted/audio/m13_2/{idx:02d}.bin'} for idx in range(4)],
    }
    text_report = {
        'chunks': [
            {'chunk_index': idx, 'path': f'extracted/text/t0_{idx:02d}_full.txt'}
            for idx in range(4)
        ]
    }

    final_rows = build_final_table(project, output, maps_report, script_report, audio_report, text_report)
    matrix_rows = build_chapter_mission_matrix(
        project,
        output,
        maps_report,
        script_report,
        graphics_report,
        audio_report,
        text_report,
    )

    assert len(final_rows) == 4
    assert len(matrix_rows) == 4
    assert [row['chapter'] for row in final_rows] == [0, 1, 2, 3]
    assert [row['chapter'] for row in matrix_rows] == [0, 1, 2, 3]
    assert all(set(row['confidence']) == {'map pack', 'graphics pack', 'audio'} for row in final_rows)
    assert all(
        link['confidence'] in {'direct', 'inferred', 'unknown'}
        for row in matrix_rows
        for link in row['links']
    )


def test_graphics_chunk_links_are_not_identical_between_chapters_by_default(tmp_path: Path) -> None:
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
    graphics_report = {
        'containers': {
            'm3_0': {'chunks': [{'chunk': 0}, {'chunk': 1}, {'chunk': 2}]},
            'm4_0': {'chunks': [{'chunk': 0}, {'chunk': 1}, {'chunk': 2}]},
        }
    }
    audio_report = {'midi': [], 'raw_audio': []}
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

    chapter0_graphics = {
        (link['container'], link['chunk_index'])
        for link in rows[0]['links']
        if link['kind'] == 'graphics_chunk'
    }
    chapter1_graphics = {
        (link['container'], link['chunk_index'])
        for link in rows[1]['links']
        if link['kind'] == 'graphics_chunk'
    }

    assert chapter0_graphics
    assert chapter1_graphics
    assert chapter0_graphics != chapter1_graphics


def test_chapter_mission_matrix_uses_known_mission_fixture_rows(tmp_path: Path) -> None:
    output = tmp_path
    text_dir = output / 'extracted' / 'text'
    text_dir.mkdir(parents=True)
    for idx in range(6):
        (text_dir / f't0_{idx:02d}_full.txt').write_text(
            f'chapter {idx} zombie laboratory final fight',
            encoding='utf-8',
        )

    maps_report = {f'm6_{idx}': {'map_count': 1} for idx in range(6)}
    script_report = {'m9': {'chapter_mission_links': {'mission_links': EXPECTED_MISSION_ROWS}}}
    graphics_report = {'containers': {'m3_0': {'chunks': [{'chunk': 0}]}, 'm4_0': {'chunks': [{'chunk': 0}]}}}
    audio_report = {'midi': [], 'raw_audio': []}
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

    chapter_to_mission = {row['chapter']: row['mission'] for row in rows}
    assert chapter_to_mission[2] == '#0'
    assert chapter_to_mission[4] == '#1'
    assert chapter_to_mission[1] == '#2'
