from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common import ensure_dir, u16le, write_json


OPCODE_MODEL: dict[int, dict[str, Any]] = {
    99: {
        'mnemonic': 'load_m8_script',
        'arg_types': ['u8:channel', 'u8:m8_pack_index', 'u8:m8_subchunk_index', 'u8:flag_a', 'u8:flag_b', 'u8:flag_c'],
        'refs': ['m8'],
        'category': 'script_ref',
    },
    100: {
        'mnemonic': 'conditional_branch_a',
        'arg_types': ['u8:condition_code', 'u8:m8_pack_index', 'u8:m8_subchunk_index', 'u8:lhs', 'u8:rhs', 'u8:reserved', 'pairs:u16'],
        'refs': ['m6_*', 'm8'],
        'category': 'control_flow',
    },
    101: {
        'mnemonic': 'conditional_branch_b',
        'arg_types': ['u8:condition_code', 'u8:m8_pack_index', 'u8:m8_subchunk_index', 'u8:lhs', 'u8:rhs', 'u8:reserved', 'pairs:u16'],
        'refs': ['m6_*', 'm8'],
        'category': 'control_flow',
    },
    102: {
        'mnemonic': 'trigger_block',
        'arg_types': ['u8:trigger_id', 'u8:event_code', 'u8:m8_subchunk_hint', 'u8:target_x', 'u8:target_y', 'u8:reserved', 'pairs:u16'],
        'refs': ['m6_*', 'm8'],
        'category': 'trigger',
    },
    200: {
        'mnemonic': 'blob_payload',
        'arg_types': ['u8:size', 'bytes:payload'],
        'refs': [],
        'category': 'data_blob',
    },
}

COMMON_COMMAND_NAMES: dict[int, str] = {
    100: 'conditional_branch_a',
    101: 'conditional_branch_b',
    102: 'trigger_block',
}


@dataclass
class LevelTrace:
    level_index: int
    chapter: int
    script_chunk: int
    script_pack_name: str
    map_pack_name: str
    map_subchunk: int
    source: str


def parse_m9_chunk_tables(payloads: list[bytes]) -> dict[str, Any]:
    chunk0 = payloads[0] if payloads else b''
    chunk1 = payloads[1] if len(payloads) > 1 else b''
    chunk2 = payloads[2] if len(payloads) > 2 else b''

    levels = []
    for idx in range(0, len(chunk0), 4):
        record = chunk0[idx:idx + 4]
        if len(record) < 2:
            break
        levels.append({
            'level_index': len(levels),
            'chapter_hint': record[0],
            'script_subchunk_hint': record[1] if len(record) > 1 else 0,
            'map_subchunk_hint': record[2] if len(record) > 2 else 0,
            'raw': list(record),
        })

    def to_u16_table(data: bytes) -> list[int]:
        limit = len(data) - (len(data) % 2)
        return [u16le(data, pos) for pos in range(0, limit, 2)]

    return {
        'chunk0_levels': {
            'size': len(chunk0),
            'record_size': 4,
            'level_count': len(levels),
            'levels': levels,
        },
        'chunk1_tables': {
            'size': len(chunk1),
            'u16_values': to_u16_table(chunk1),
        },
        'chunk2_tables': {
            'size': len(chunk2),
            'u16_values': to_u16_table(chunk2),
        },
    }


def resolve_level_trace(level_index: int, m9_tables: dict[str, Any], chapter_count: int = 6) -> LevelTrace:
    levels = m9_tables.get('chunk0_levels', {}).get('levels', [])
    if 0 <= level_index < len(levels):
        entry = levels[level_index]
        chapter = entry.get('chapter_hint', 0) % max(1, chapter_count)
        map_subchunk = entry.get('map_subchunk_hint', 0)
        source = 'chunk0_levels'
    else:
        chapter = level_index % max(1, chapter_count)
        map_subchunk = 0
        source = 'fallback_formula'

    return LevelTrace(
        level_index=level_index,
        chapter=chapter,
        script_chunk=10 + chapter,
        script_pack_name=f'm9#{10 + chapter}',
        map_pack_name=f'm6_{chapter}',
        map_subchunk=map_subchunk,
        source=source,
    )


def _parse_common_command(opcode: int, meta: list[int], params: list[int]) -> dict[str, Any]:
    m6_subchunk = params[0] % 255 if params else None
    m8_pack_index = meta[1]
    m8_subchunk_index = meta[2]

    common_fields: dict[str, Any] = {
        'condition_code': meta[0],
        'm8_pack_index': m8_pack_index,
        'm8_subchunk_index': m8_subchunk_index,
        'lhs': meta[3],
        'rhs': meta[4],
        'reserved': meta[5],
        'pair_count': len(params),
        'param_pairs_u16': params,
    }
    if opcode == 102:
        common_fields = {
            'trigger_id': meta[0],
            'event_code': meta[1],
            'm8_subchunk_hint': meta[2],
            'target_x': meta[3],
            'target_y': meta[4],
            'reserved': meta[5],
            'pair_count': len(params),
            'param_pairs_u16': params,
        }

    refs = {
        'm8': {
            'pack_index': m8_pack_index,
            'subchunk_index': m8_subchunk_index,
            'confidence': 0.92 if opcode in (100, 101) else 0.88,
            'source': 'common_command_fields',
        },
        'm6': {
            'pack': f'm6_{meta[0] % 6}',
            'subchunk': m6_subchunk,
            'confidence': 0.76 if m6_subchunk is not None else 0.35,
            'source': 'params[0] when present',
        },
    }

    return {'args': common_fields, 'refs': refs}


def _semantic_for_generic(opcode: int, meta: list[int], params: list[int]) -> dict[str, Any]:
    map_refs = []
    object_placements = []
    triggers = []
    control_flow: dict[str, Any] = {}

    if params:
        map_refs.append({'pack': f'm6_{meta[0] % 6}', 'subchunk': params[0] % 255, 'source': 'params[0]'})

    if opcode in (100, 101):
        control_flow = {
            'kind': 'conditional_jump',
            'condition_code': meta[0],
            'target_hint': params[0] if params else None,
        }
    if opcode == 102:
        triggers.append({'trigger_id': meta[0], 'event_code': meta[1], 'params': params[:4]})

    if len(params) >= 3:
        object_placements.append({'object_id': params[0], 'x': params[1], 'y': params[2]})

    parsed_common = _parse_common_command(opcode, meta, params) if opcode in COMMON_COMMAND_NAMES else None

    return {
        'args': {
            'meta': {
                'condition_or_type': meta[0],
                'arg1': meta[1],
                'arg2': meta[2],
                'arg3': meta[3],
                'arg4': meta[4],
                'arg5': meta[5],
            },
            'params': params,
        },
        'parsed_fields': parsed_common['args'] if parsed_common else None,
        'refs': parsed_common['refs'] if parsed_common else {
            'm8': {'pack_index': meta[1], 'subchunk_index': meta[2]},
            'm6_candidate': {'pack': f'm6_{meta[0] % 6}', 'subchunk': params[0] if params else None},
        },
        'control_flow': control_flow,
        'triggers': triggers,
        'object_placements': object_placements,
        'map_refs': map_refs,
    }


def parse_script_chunk_semantic(chunk: bytes) -> dict[str, Any]:
    cursor = 0
    commands = []
    opcode_hist = Counter()
    semantic_known = 0

    while cursor < len(chunk):
        start = cursor
        opcode = chunk[cursor]
        cursor += 1
        opcode_hist[opcode] += 1

        model = OPCODE_MODEL.get(opcode)
        base: dict[str, Any] = {
            'offset': start,
            'opcode': opcode,
            'mnemonic': model['mnemonic'] if model else 'unknown',
            'arg_types': model['arg_types'] if model else ['unknown'],
            'category': model['category'] if model else 'unknown',
            'semantic_known': model is not None,
        }

        if model is not None:
            semantic_known += 1

        if opcode == 99 and cursor + 6 <= len(chunk):
            values = list(chunk[cursor:cursor + 6])
            cursor += 6
            m8_ref = {
                'pack_index': values[1],
                'subchunk_index': values[2],
                'confidence': 1.0,
                'source': 'opcode_99_explicit',
            }
            base['args'] = {
                'channel': values[0],
                'm8_pack_index': values[1],
                'm8_subchunk_index': values[2],
                'flag_a': values[3],
                'flag_b': values[4],
                'flag_c': values[5],
            }
            base['refs'] = {'m8': m8_ref}
            base['control_flow'] = {}
            base['triggers'] = []
            base['map_refs'] = []
            base['object_placements'] = []
            commands.append(base)
            continue

        if opcode == 200 and cursor < len(chunk):
            size = chunk[cursor]
            cursor += 1
            payload = list(chunk[cursor:cursor + size])
            cursor += size
            base['args'] = {
                'payload_size': size,
                'payload_preview': payload[:16],
                'payload_checksum16': sum(payload) % 65536,
            }
            base['refs'] = {}
            base['control_flow'] = {}
            base['triggers'] = []
            base['map_refs'] = []
            base['object_placements'] = []
            commands.append(base)
            continue

        if cursor + 7 > len(chunk):
            base['truncated'] = True
            commands.append(base)
            break

        meta = list(chunk[cursor:cursor + 6])
        cursor += 6
        pair_count = chunk[cursor]
        cursor += 1
        params = []
        for _ in range(pair_count):
            if cursor + 2 > len(chunk):
                break
            params.append(u16le(chunk, cursor))
            cursor += 2

        semantic = _semantic_for_generic(opcode, meta, params)
        base['pair_count'] = pair_count
        base.update(semantic)
        commands.append(base)

    return {
        'command_count': len(commands),
        'semantic_known_count': semantic_known,
        'semantic_unknown_count': len(commands) - semantic_known,
        'opcode_histogram': dict(sorted(opcode_hist.items())),
        'commands': commands,
    }


def build_semantic_level_exports(output: Path, m9_tables: dict[str, Any], m9_scripts: list[dict[str, Any]]) -> dict[str, Any]:
    levels_dir = output / 'scripts' / 'semantic' / 'levels'
    ensure_dir(levels_dir)

    level_count = m9_tables.get('chunk0_levels', {}).get('level_count', 0)
    if level_count == 0:
        level_count = max(1, len(m9_scripts))

    level_index_entries = []
    for level_index in range(level_count):
        trace = resolve_level_trace(level_index, m9_tables)
        script_entry = next((row for row in m9_scripts if row['chunk_index'] == trace.script_chunk), None)
        commands = script_entry.get('commands', []) if script_entry else []

        map_refs = []
        placements = []
        triggers = []
        for command in commands:
            map_refs.extend(command.get('map_refs', []))
            placements.extend(command.get('object_placements', []))
            triggers.extend(command.get('triggers', []))

        payload = {
            'level_index': level_index,
            'trace': trace.__dict__,
            'map_refs': map_refs,
            'object_placements': placements,
            'triggers': triggers,
            'script_command_count': len(commands),
        }
        level_path = levels_dir / f'{level_index}.json'
        write_json(level_path, payload)
        level_index_entries.append({'level_index': level_index, 'path': str(level_path.relative_to(output))})

    return {
        'levels_dir': str(levels_dir.relative_to(output)),
        'levels': level_index_entries,
    }


def build_opcode_coverage(m9_scripts: list[dict[str, Any]]) -> dict[str, Any]:
    total_commands = 0
    semantic_known = 0
    opcode_counter: Counter[int] = Counter()

    for row in m9_scripts:
        for command in row.get('commands', []):
            total_commands += 1
            if command.get('semantic_known'):
                semantic_known += 1
            opcode_counter[command['opcode']] += 1

    unknown = total_commands - semantic_known
    unknown_opcodes = sorted(opcode for opcode in opcode_counter if opcode not in OPCODE_MODEL)
    return {
        'total_commands': total_commands,
        'semantic_known': semantic_known,
        'semantic_unknown': unknown,
        'semantic_coverage_percent': round((semantic_known / total_commands * 100.0), 2) if total_commands else 0.0,
        'unknown_opcodes': unknown_opcodes,
        'opcode_histogram': dict(sorted(opcode_counter.items())),
    }
