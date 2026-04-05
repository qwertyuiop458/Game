from __future__ import annotations

import json
from pathlib import Path

from tools.extract_zombie_infection import run_extractor


def test_run_extractor_summary_contract(monkeypatch, tmp_path: Path) -> None:
    jar = tmp_path / 'dummy.jar'
    jar.write_bytes(b'')
    output = tmp_path / 'out'

    class FakeProject:
        def __init__(self, jar_path: Path, out_path: Path) -> None:
            self.jar_path = jar_path
            self.output = out_path
            self.raw_entries: dict[str, bytes] = {}

        def load(self) -> None:
            return None

    def fake_parse_packs(_jar: Path, _out: Path) -> dict:
        return {
            'ok_container': {
                'header_mode': 'u32',
                'validation': 'ok',
                'validation_errors': [],
                'chunk_count': 3,
                'header_size': 13,
                'payload_size': 90,
            },
            'bad_container': {
                'header_mode': 'u8',
                'validation': 'errors',
                'validation_errors': ['offset_count mismatch', 404],
                'chunk_count': 2,
                'header_size': 9,
                'payload_size': 44,
            },
        }

    monkeypatch.setattr('tools.extract_zombie_infection.JarProject', FakeProject)
    monkeypatch.setattr('tools.extract_zombie_infection.parse_packs', fake_parse_packs)
    monkeypatch.setattr('tools.extract_zombie_infection.decode_text', lambda *_args, **_kwargs: {'decoded': 1})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_audio',
        lambda *_args, **_kwargs: {
            'tracks': [],
            'audio_coverage': {
                'total_tracks': 0,
                'decoded_tracks': 0,
                'coverage_percent': 0.0,
            },
        },
    )
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {
            'maps': {'m1': {}},
            'scripts': {'s1': {}},
            'map_mismatch_summary': {
                'total_maps': 1,
                'mismatched_maps': 0,
                'mismatch_details': [],
            },
        },
    )
    monkeypatch.setattr('tools.extract_zombie_infection.decode_graphics', lambda *_args, **_kwargs: {'atlas': []})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.extract_ui_assets',
        lambda *_args, **_kwargs: {'copied': {}, 'missing': [], 'manifest': 'extracted/meta/ui_manifest.json'},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.build_final_table', lambda *_args, **_kwargs: [{'id': 1}])
    monkeypatch.setattr(
        'tools.extract_zombie_infection.build_chapter_mission_matrix',
        lambda *_args, **_kwargs: [{'chapter': 1}],
    )
    monkeypatch.setattr(
        'tools.extract_zombie_infection.build_chapter_matrix',
        lambda *_args, **_kwargs: {
            'chapters': [{'id': 1}, {'id': 2}],
            'cross_check': {'ok': True},
            'linker_conflicts_summary': {
                'total_conflicts': 0,
                'blocking_conflicts': 0,
                'conflicts': [],
            },
        },
    )

    summary = run_extractor(jar, output)

    expected_keys = {
        'jar',
        'containers',
        'container_quality',
        'text',
        'audio',
        'maps',
        'scripts',
        'map_mismatch_summary',
        'audio_coverage',
        'graphics',
        'ui',
        'final_table_rows',
        'chapter_mission_matrix_rows',
        'chapter_matrix_rows',
        'chapter_matrix_cross_check',
        'linker_conflicts_summary',
    }
    assert set(summary) == expected_keys

    assert isinstance(summary['jar'], str)
    assert isinstance(summary['containers'], dict)
    assert isinstance(summary['container_quality'], dict)
    assert isinstance(summary['text'], dict)
    assert isinstance(summary['audio'], dict)
    assert isinstance(summary['maps'], dict)
    assert isinstance(summary['scripts'], dict)
    assert isinstance(summary['map_mismatch_summary'], dict)
    assert isinstance(summary['audio_coverage'], dict)
    assert isinstance(summary['graphics'], dict)
    assert isinstance(summary['ui'], dict)
    assert isinstance(summary['final_table_rows'], int)
    assert isinstance(summary['chapter_mission_matrix_rows'], int)
    assert isinstance(summary['chapter_matrix_rows'], int)
    assert isinstance(summary['chapter_matrix_cross_check'], dict)
    assert isinstance(summary['linker_conflicts_summary'], dict)

    map_mismatch_summary = summary['map_mismatch_summary']
    assert isinstance(map_mismatch_summary.get('total_maps'), int)
    assert map_mismatch_summary['total_maps'] >= 0
    assert isinstance(map_mismatch_summary.get('mismatched_maps'), int)
    assert 0 <= map_mismatch_summary['mismatched_maps'] <= map_mismatch_summary['total_maps']
    assert isinstance(map_mismatch_summary.get('mismatch_details'), list)

    audio_coverage = summary['audio_coverage']
    assert isinstance(audio_coverage.get('total_tracks'), int)
    assert audio_coverage['total_tracks'] >= 0
    assert isinstance(audio_coverage.get('decoded_tracks'), int)
    assert 0 <= audio_coverage['decoded_tracks'] <= audio_coverage['total_tracks']
    assert isinstance(audio_coverage.get('coverage_percent'), float)
    assert 0.0 <= audio_coverage['coverage_percent'] <= 100.0

    linker_conflicts_summary = summary['linker_conflicts_summary']
    assert isinstance(linker_conflicts_summary.get('total_conflicts'), int)
    assert linker_conflicts_summary['total_conflicts'] >= 0
    assert isinstance(linker_conflicts_summary.get('blocking_conflicts'), int)
    assert 0 <= linker_conflicts_summary['blocking_conflicts'] <= linker_conflicts_summary['total_conflicts']
    assert isinstance(linker_conflicts_summary.get('conflicts'), list)

    for quality in summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])

    written_summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert set(written_summary) == set(summary) == expected_keys
    assert written_summary == summary
    for quality in written_summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])
