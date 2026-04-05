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
    monkeypatch.setattr('tools.extract_zombie_infection.decode_audio', lambda *_args, **_kwargs: {'tracks': []})
    monkeypatch.setattr(
        'tools.extract_zombie_infection.decode_maps',
        lambda *_args, **_kwargs: {'maps': {'m1': {}}, 'scripts': {'s1': {}}},
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
        lambda *_args, **_kwargs: {'chapters': [{'id': 1}, {'id': 2}], 'cross_check': {'ok': True}},
    )

    summary = run_extractor(jar, output)

    expected_keys = {
        'jar',
        'containers',
        'container_quality',
        'text',
        'audio',
        'audio_stats',
        'maps',
        'scripts',
        'graphics',
        'ui',
        'final_table_rows',
        'chapter_mission_matrix_rows',
        'chapter_matrix_rows',
        'chapter_matrix_cross_check',
        'map_validation_summary',
    }
    assert set(summary) == expected_keys

    assert isinstance(summary['jar'], str)
    assert isinstance(summary['containers'], dict)
    assert isinstance(summary['container_quality'], dict)
    assert isinstance(summary['text'], dict)
    assert isinstance(summary['audio'], dict)
    assert isinstance(summary['audio_stats'], dict)
    assert isinstance(summary['maps'], dict)
    assert isinstance(summary['scripts'], dict)
    assert isinstance(summary['graphics'], dict)
    assert isinstance(summary['ui'], dict)
    assert isinstance(summary['final_table_rows'], int)
    assert isinstance(summary['chapter_mission_matrix_rows'], int)
    assert isinstance(summary['chapter_matrix_rows'], int)
    assert isinstance(summary['chapter_matrix_cross_check'], dict)
    assert summary['audio_stats'] == {'valid_midi': 0, 'invalid_midi': 0, 'raw_audio': 0}

    for quality in summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])

    written_summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert set(written_summary) == expected_keys
    for quality in written_summary['container_quality'].values():
        assert isinstance(quality.get('validation_errors'), list)
        assert all(isinstance(err, str) for err in quality['validation_errors'])
