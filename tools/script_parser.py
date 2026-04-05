from __future__ import annotations

from collections import Counter
from typing import Any

from tools.common import u16le
from tools.m9_semantics import (
    build_semantic_level_exports,
    parse_m9_chunk_tables,
    resolve_level_trace,
)


KNOWN_OPCODES: dict[int, dict[str, Any]] = {
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

OPCODE_MODEL: dict[int, dict[str, Any]] = KNOWN_OPCODES

COMMON_COMMAND_NAMES: dict[int, str] = {
    100: 'conditional_branch_a',
    101: 'conditional_branch_b',
    102: 'trigger_block',
}


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
    command_links: list[dict[str, Any]] = []

    if params:
        map_ref = {'pack': f'm6_{meta[0] % 6}', 'subchunk': params[0] % 255, 'source': 'params[0]'}
        map_refs.append(map_ref)
        command_links.append({'target': 'm6', 'pack': map_ref['pack'], 'subchunk': map_ref['subchunk'], 'kind': 'map_ref'})

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
    if parsed_common:
        command_links.append(
            {
                'target': 'm8',
                'pack_index': parsed_common['refs']['m8']['pack_index'],
                'subchunk_index': parsed_common['refs']['m8']['subchunk_index'],
                'kind': 'script_ref',
            }
        )
        if parsed_common['refs']['m6'].get('subchunk') is not None:
            command_links.append(
                {
                    'target': 'm6',
                    'pack': parsed_common['refs']['m6']['pack'],
                    'subchunk': parsed_common['refs']['m6']['subchunk'],
                    'kind': 'common_command_ref',
                }
            )

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
        'command_links': command_links,
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
            base['command_links'] = [{'target': 'm8', 'pack_index': values[1], 'subchunk_index': values[2], 'kind': 'opcode_99_explicit'}]
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
            base['command_links'] = []
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


def parse_m8_chunk_semantic(chunk: bytes) -> dict[str, Any]:
    parsed = parse_script_chunk_semantic(chunk)
    parsed['subchunk_offsets_guess'] = []
    for command in parsed['commands']:
        if command['opcode'] in (99, 100, 101, 102, 200):
            parsed['subchunk_offsets_guess'].append(command['offset'])
    return parsed


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
