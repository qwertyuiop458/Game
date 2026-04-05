from __future__ import annotations

import json
from pathlib import Path

from tools.extract_zombie_infection import SUMMARY_SCHEMA_VERSION, run_extractor


def test_summary_container_quality_contains_detailed_fields(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr('tools.extract_zombie_infection.decode_text', lambda *_args, **_kwargs: {})
    monkeypatch.setattr('tools.extract_zombie_infection.decode_audio', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {'maps': {}, 'scripts': {}},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.decode_graphics', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.extract_ui_assets',
        lambda *_args, **_kwargs: {'copied': {}, 'missing': [], 'manifest': 'extracted/meta/ui_manifest.json'},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.build_final_table', lambda *_args, **_kwargs: [])
    monkeypatch.setattr('tools.extract_zombie_infection.build_chapter_mission_matrix', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        'tools.extract_zombie_infection.build_chapter_matrix',
        lambda *_args, **_kwargs: {'chapters': [], 'cross_check': {}},
    )

    summary = run_extractor(jar, output)
    container_quality = summary['container_quality']
    assert summary['summary_schema_version'] == SUMMARY_SCHEMA_VERSION
    assert summary['audio_stats'] == {'valid_midi': 0, 'invalid_midi': 0, 'raw_audio': 0}

    assert container_quality['ok_container'] == {
        'header_mode': 'u32',
        'validation': 'ok',
        'validation_errors': [],
        'chunk_count': 3,
        'header_size': 13,
        'payload_size': 90,
    }
    assert container_quality['bad_container'] == {
        'header_mode': 'u8',
        'validation': 'errors',
        'validation_errors': ['offset_count mismatch', '404'],
        'chunk_count': 2,
        'header_size': 9,
        'payload_size': 44,
    }

    written_summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert written_summary['summary_schema_version'] == SUMMARY_SCHEMA_VERSION
    assert written_summary['container_quality'] == container_quality
    assert written_summary['audio_stats'] == summary['audio_stats']


def test_summary_normalizes_required_summary_blocks(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.setattr('tools.extract_zombie_infection.JarProject', FakeProject)
    monkeypatch.setattr('tools.extract_zombie_infection.parse_packs', lambda *_args, **_kwargs: {})
    monkeypatch.setattr('tools.extract_zombie_infection.decode_text', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_audio',
        lambda *_args, **_kwargs: {'audio_coverage': {'total_tracks': 1, 'decoded_tracks': 10}},
    )
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {'maps': {}, 'scripts': {}, 'map_mismatch_summary': {'total_maps': 4}},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.decode_graphics', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.extract_ui_assets',
        lambda *_args, **_kwargs: {'copied': {}, 'missing': [], 'manifest': 'extracted/meta/ui_manifest.json'},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.build_final_table', lambda *_args, **_kwargs: [])
    monkeypatch.setattr('tools.extract_zombie_infection.build_chapter_mission_matrix', lambda *_args, **_kwargs: [])
    monkeypatch.setattr('tools.extract_zombie_infection.build_chapter_matrix', lambda *_args, **_kwargs: {'chapters': []})

    summary = run_extractor(jar, output)
    assert summary['audio_coverage'] == {'total_tracks': 1, 'decoded_tracks': 1, 'coverage_percent': 0.0}
    assert summary['audio_validation_summary'] == {'total': 0, 'valid': 0, 'invalid': 0, 'warnings': 0}
    assert summary['map_mismatch_summary'] == {
        'total_maps': 4,
        'mismatched_maps': 0,
        'mismatch_details': [],
        'maps_validation_passed': 0,
        'maps_validation_failed': 0,
    }
    assert summary['chapter_matrix_cross_check'] == {
        'total_refs': 0,
        'valid_refs': 0,
        'valid_confidence_totals': {'direct': 0, 'inferred': 0, 'unknown': 0},
        'invalid_refs': [],
        'dropped_invalid_refs': [],
        'conflict_summary': {'total_conflicts': 0, 'by_type': {}},
    }
    assert summary['linker_conflicts_summary'] == {'total_conflicts': 0, 'blocking_conflicts': 0, 'conflicts': []}


def test_summary_normalizes_partial_and_unknown_entries(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.setattr('tools.extract_zombie_infection.JarProject', FakeProject)
    monkeypatch.setattr('tools.extract_zombie_infection.parse_packs', lambda *_args, **_kwargs: {})
    monkeypatch.setattr('tools.extract_zombie_infection.decode_text', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_audio',
        lambda *_args, **_kwargs: {
            'audio_coverage': {'total_tracks': '10', 'decoded_tracks': '7', 'coverage_percent': '70.0'},
            'midi_validation_summary': {'total': '2', 'valid': '1', 'invalid': '1', 'warnings': None},
        },
    )
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {
            'maps': {},
            'scripts': {},
            'map_mismatch_summary': {
                'total_maps': 1,
                'mismatched_maps': 1,
                'mismatch_details': [
                    {'pack': None, 'chunk': -3, 'expected': None, 'actual': {'grid_cells': 0}, 'message': 123},
                    'bad',
                ],
                'maps_validation_passed': 0,
                'maps_validation_failed': 1,
            },
        },
    )
    monkeypatch.setattr('tools.extract_zombie_infection.decode_graphics', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.extract_ui_assets',
        lambda *_args, **_kwargs: {'copied': {}, 'missing': [], 'manifest': 'extracted/meta/ui_manifest.json'},
    )
    monkeypatch.setattr('tools.extract_zombie_infection.build_final_table', lambda *_args, **_kwargs: [])
    monkeypatch.setattr('tools.extract_zombie_infection.build_chapter_mission_matrix', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        'tools.extract_zombie_infection.build_chapter_matrix',
        lambda *_args, **_kwargs: {
            'chapters': [],
            'cross_check': {'total_refs': None, 'valid_confidence_totals': None, 'conflict_summary': {'by_type': None}},
            'linker_conflicts_summary': {'total_conflicts': 3, 'blocking_conflicts': 2, 'conflicts': [None, {'ok': 1}]},
        },
    )

    summary = run_extractor(jar, output)
    assert summary['audio_coverage'] == {'total_tracks': 10, 'decoded_tracks': 7, 'coverage_percent': 70.0}
    assert summary['audio_validation_summary'] == {'total': 2, 'valid': 1, 'invalid': 1, 'warnings': 0}
    assert summary['map_mismatch_summary']['mismatch_details'] == [
        {'pack': 'None', 'chunk': 0, 'expected': {}, 'actual': {'grid_cells': 0}, 'severity': 'unknown', 'message': '123'},
        {'pack': '', 'chunk': 0, 'expected': {}, 'actual': {}, 'severity': 'unknown', 'message': ''},
    ]
    assert summary['chapter_matrix_cross_check']['valid_confidence_totals'] == {'direct': 0, 'inferred': 0, 'unknown': 0}
    assert summary['linker_conflicts_summary']['conflicts'] == [{'value': 'None'}, {'ok': 1}]
