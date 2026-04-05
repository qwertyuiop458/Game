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
                'total_tracks': 3,
                'decoded_tracks': 2,
                'coverage_percent': 66.6,
            },
            'midi_validation_summary': {'total': 3, 'valid': 2, 'invalid': 1, 'warnings': 0},
        },
    )
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {
            'maps': {'m1': {}},
            'scripts': {'s1': {}},
            'map_mismatch_summary': {
                'total_maps': 2,
                'mismatched_maps': 1,
                'mismatch_details': [{
                    'pack': 'm6_0',
                    'chunk': 0,
                    'expected': {'grid_cells': 6},
                    'actual': {'grid_cells': 5},
                    'severity': 'error',
                    'message': 'collision grid cell count mismatch',
                }],
                'maps_validation_passed': 1,
                'maps_validation_failed': 1,
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
            'cross_check': {
                'total_refs': 5,
                'valid_refs': 4,
                'valid_confidence_totals': {'direct': 3, 'inferred': 1, 'unknown': 0},
                'invalid_refs': [{'ref': {'container': 'm6_0', 'chunk_index': 99}, 'error': 'missing'}],
                'dropped_invalid_refs': [],
                'conflict_summary': {'total_conflicts': 1, 'by_type': {'chapter_target_mismatch': 1}},
            },
            'linker_conflicts_summary': {
                'total_conflicts': 1,
                'blocking_conflicts': 1,
                'conflicts': [{'conflict_type': 'chapter_target_mismatch', 'chapters': [0, 1]}],
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
        'audio_stats',
        'audio_validation_summary',
        'maps',
        'scripts',
        'map_mismatch_summary',
        'maps_validation_passed',
        'maps_validation_failed',
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
    assert isinstance(summary['audio_stats'], dict)
    assert isinstance(summary['audio_validation_summary'], dict)
    assert isinstance(summary['maps'], dict)
    assert isinstance(summary['scripts'], dict)
    assert isinstance(summary['map_mismatch_summary'], dict)
    assert isinstance(summary['maps_validation_passed'], int)
    assert isinstance(summary['maps_validation_failed'], int)
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

    midi_validation_summary = summary['audio_validation_summary']
    assert set(midi_validation_summary) == {'total', 'valid', 'invalid', 'warnings'}
    assert all(isinstance(midi_validation_summary[key], int) for key in midi_validation_summary)
    assert all(midi_validation_summary[key] >= 0 for key in midi_validation_summary)
    assert midi_validation_summary['valid'] <= midi_validation_summary['total']
    assert midi_validation_summary['invalid'] <= midi_validation_summary['total']

    linker_conflicts_summary = summary['linker_conflicts_summary']
    assert isinstance(linker_conflicts_summary.get('total_conflicts'), int)
    assert linker_conflicts_summary['total_conflicts'] >= 0
    assert isinstance(linker_conflicts_summary.get('blocking_conflicts'), int)
    assert 0 <= linker_conflicts_summary['blocking_conflicts'] <= linker_conflicts_summary['total_conflicts']
    assert isinstance(linker_conflicts_summary.get('conflicts'), list)

    chapter_matrix_cross_check = summary['chapter_matrix_cross_check']
    assert isinstance(chapter_matrix_cross_check.get('total_refs'), int)
    assert chapter_matrix_cross_check['total_refs'] >= 0
    assert isinstance(chapter_matrix_cross_check.get('valid_refs'), int)
    assert 0 <= chapter_matrix_cross_check['valid_refs'] <= chapter_matrix_cross_check['total_refs']
    assert isinstance(chapter_matrix_cross_check.get('valid_confidence_totals'), dict)
    assert set(chapter_matrix_cross_check['valid_confidence_totals']) == {'direct', 'inferred', 'unknown'}
    for key in ('direct', 'inferred', 'unknown'):
        value = chapter_matrix_cross_check['valid_confidence_totals'][key]
        assert isinstance(value, int)
        assert value >= 0
    assert isinstance(chapter_matrix_cross_check.get('invalid_refs'), list)
    assert isinstance(chapter_matrix_cross_check.get('dropped_invalid_refs'), list)
    assert isinstance(chapter_matrix_cross_check.get('conflict_summary'), dict)
    assert isinstance(chapter_matrix_cross_check['conflict_summary'].get('total_conflicts'), int)
    assert chapter_matrix_cross_check['conflict_summary']['total_conflicts'] >= 0
    assert isinstance(chapter_matrix_cross_check['conflict_summary'].get('by_type'), dict)
    assert all(
        isinstance(key, str) and isinstance(value, int) and value >= 0
        for key, value in chapter_matrix_cross_check['conflict_summary']['by_type'].items()
    )

    assert map_mismatch_summary['maps_validation_passed'] >= 0
    assert map_mismatch_summary['maps_validation_failed'] >= 0
    assert map_mismatch_summary['maps_validation_passed'] <= map_mismatch_summary['total_maps']
    assert map_mismatch_summary['maps_validation_failed'] <= map_mismatch_summary['total_maps']
    assert summary['maps_validation_passed'] == map_mismatch_summary['maps_validation_passed']
    assert summary['maps_validation_failed'] == map_mismatch_summary['maps_validation_failed']
    for entry in map_mismatch_summary['mismatch_details']:
        assert isinstance(entry, dict)
        assert {'pack', 'chunk', 'expected', 'actual', 'severity', 'message'} <= set(entry)
        assert isinstance(entry['pack'], str)
        assert isinstance(entry['chunk'], int)
        assert isinstance(entry['expected'], dict)
        assert isinstance(entry['actual'], dict)
        assert isinstance(entry['severity'], str)
        assert isinstance(entry['message'], str)

    for quality in summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])

    written_summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert set(written_summary) == set(summary) == expected_keys
    assert written_summary == summary
    for quality in written_summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])
