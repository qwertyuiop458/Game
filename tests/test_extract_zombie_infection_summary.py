from __future__ import annotations

import json
from pathlib import Path

from tools.extract_zombie_infection import run_extractor


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
    assert written_summary['container_quality'] == container_quality
    assert written_summary['audio_stats'] == summary['audio_stats']
