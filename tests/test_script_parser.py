from pathlib import Path

import pytest

from tools.script_parser import (
    build_opcode_coverage,
    build_semantic_level_exports,
    parse_m9_chunk_tables,
    parse_script_chunk_semantic,
    resolve_level_trace,
)


@pytest.mark.extractor
def test_parse_m9_chunk_tables_split() -> None:
    payloads = [
        bytes([1, 2, 3, 4, 7, 8, 9, 10]),
        bytes([1, 0, 2, 0]),
        bytes([3, 0, 4, 0]),
    ]
    parsed = parse_m9_chunk_tables(payloads)
    assert parsed['chunk0_levels']['level_count'] == 2
    assert parsed['chunk1_tables']['u16_values'] == [1, 2]
    assert parsed['chunk2_tables']['u16_values'] == [3, 4]


@pytest.mark.extractor
def test_trace_resolution_prefers_chunk0() -> None:
    tables = {
        'chunk0_levels': {
            'levels': [
                {'chapter_hint': 8, 'script_subchunk_hint': 4, 'map_subchunk_hint': 11},
            ],
        }
    }
    trace = resolve_level_trace(0, tables)
    assert trace.chapter == 2
    assert trace.script_chunk == 14
    assert trace.map_subchunk == 11
    assert trace.source == 'chunk0_levels'


@pytest.mark.extractor
def test_semantic_parser_and_coverage() -> None:
    # opcode 99 + 6 bytes; opcode 200 + size + payload; opcode 42 generic with 0 pairs
    chunk = bytes([99, 1, 2, 3, 4, 5, 6, 200, 2, 9, 8, 42, 0, 0, 0, 0, 0, 0, 0])
    parsed = parse_script_chunk_semantic(chunk)
    assert parsed['command_count'] == 3
    assert parsed['semantic_known_count'] == 2
    coverage = build_opcode_coverage([{'chunk_index': 10, 'commands': parsed['commands']}])
    assert coverage['semantic_unknown'] == 1
    assert 42 in coverage['unknown_opcodes']


@pytest.mark.extractor
def test_common_opcode_structures_have_named_fields_and_confidence() -> None:
    # opcode 100 + meta(6) + pair_count(1) + one u16 pair
    chunk = bytes([100, 7, 1, 2, 3, 4, 5, 1, 9, 0])
    parsed = parse_script_chunk_semantic(chunk)
    command = parsed['commands'][0]
    assert command['parsed_fields']['condition_code'] == 7
    assert command['parsed_fields']['m8_subchunk_index'] == 2
    assert command['refs']['m8']['confidence'] >= 0.9
    assert command['refs']['m6']['pack'] == 'm6_1'
    assert command['refs']['m6']['subchunk'] == 9
    assert any(link['target'] == 'm8' for link in command['command_links'])


@pytest.mark.extractor
def test_semantic_level_export(tmp_path: Path) -> None:
    tables = {
        'chunk0_levels': {
            'level_count': 1,
            'levels': [{'chapter_hint': 0, 'map_subchunk_hint': 1}],
        }
    }
    scripts = [{
        'chunk_index': 10,
        'commands': [
            {'map_refs': [{'pack': 'm6_0', 'subchunk': 1}], 'object_placements': [{'object_id': 7, 'x': 1, 'y': 2}], 'triggers': [{'trigger_id': 4}]},
        ],
    }]
    result = build_semantic_level_exports(tmp_path, tables, scripts)
    assert result['levels'][0]['path'] == 'scripts/semantic/level_00.json'
    exported = (tmp_path / 'scripts' / 'semantic' / 'level_00.json').read_text(encoding='utf-8')
    assert 'tile_layers' in exported
    assert 'collision_layers' in exported
    assert 'objects' in exported
    assert 'triggers' in exported
