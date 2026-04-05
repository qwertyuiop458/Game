from pathlib import Path

from tools.script_parser import (
    build_opcode_coverage,
    build_semantic_level_exports,
    parse_m9_chunk_tables,
    parse_script_chunk_semantic,
    resolve_level_trace,
)


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


def test_trace_resolution_prefers_chunk0() -> None:
    tables = {
        'chunk0_levels': {
            'levels': [
                {'chapter_hint': 8, 'map_subchunk_hint': 11},
            ],
        }
    }
    trace = resolve_level_trace(0, tables)
    assert trace.chapter == 2
    assert trace.script_chunk == 12
    assert trace.map_subchunk == 11
    assert trace.source == 'chunk0_levels'


def test_semantic_parser_and_coverage() -> None:
    # opcode 99 + 6 bytes; opcode 200 + size + payload; opcode 42 generic with 0 pairs
    chunk = bytes([99, 1, 2, 3, 4, 5, 6, 200, 2, 9, 8, 42, 0, 0, 0, 0, 0, 0, 0])
    parsed = parse_script_chunk_semantic(chunk)
    assert parsed['command_count'] == 3
    assert parsed['semantic_known_count'] == 2
    coverage = build_opcode_coverage([{'chunk_index': 10, 'commands': parsed['commands']}])
    assert coverage['semantic_unknown'] == 1
    assert 42 in coverage['unknown_opcodes']


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
    assert result['levels'][0]['path'] == 'scripts/semantic/levels/0.json'
    exported = (tmp_path / 'scripts' / 'semantic' / 'levels' / '0.json').read_text(encoding='utf-8')
    assert 'map_refs' in exported
    assert 'object_placements' in exported
    assert 'triggers' in exported
