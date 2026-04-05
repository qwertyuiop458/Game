from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common import ensure_dir, u16le, write_json


M9_DOCS: dict[str, Any] = {
    'chunk0': {
        'record_size': 4,
        'fields': [
            {'name': 'chapter_hint', 'type': 'u8'},
            {'name': 'script_subchunk_hint', 'type': 'u8'},
            {'name': 'map_subchunk_hint', 'type': 'u8'},
            {'name': 'reserved_or_flags', 'type': 'u8'},
        ],
    },
    'chunk1': {
        'entry_type': 'u16',
        'guess': 'script offset / selector table',
    },
    'chunk2': {
        'entry_type': 'u16',
        'guess': 'trigger / object selector table',
    },
    'mission_script_rule': {
        'formula': 'script_chunk = 10 + level_index',
        'applies_to_levels': '0..N',
    },
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
        levels.append(
            {
                'level_index': len(levels),
                'chapter_hint': record[0],
                'script_subchunk_hint': record[1] if len(record) > 1 else 0,
                'map_subchunk_hint': record[2] if len(record) > 2 else 0,
                'raw': list(record),
            }
        )

    def to_u16_table(data: bytes) -> list[int]:
        limit = len(data) - (len(data) % 2)
        return [u16le(data, pos) for pos in range(0, limit, 2)]

    return {
        'docs': M9_DOCS,
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
        script_subchunk = entry.get('script_subchunk_hint', level_index)
        source = 'chunk0_levels'
    else:
        chapter = level_index % max(1, chapter_count)
        map_subchunk = 0
        script_subchunk = level_index
        source = 'fallback_formula'

    return LevelTrace(
        level_index=level_index,
        chapter=chapter,
        script_chunk=10 + script_subchunk,
        script_pack_name=f'm9#{10 + script_subchunk}',
        map_pack_name=f'm6_{chapter}',
        map_subchunk=map_subchunk,
        source=source,
    )


def build_chapter_mission_links(m9_tables: dict[str, Any], chapter_count: int = 6) -> dict[str, Any]:
    levels = m9_tables.get('chunk0_levels', {}).get('levels', [])
    mission_links = []
    chapter_index: dict[int, list[dict[str, Any]]] = {chapter: [] for chapter in range(chapter_count)}
    for level_index in range(len(levels)):
        trace = resolve_level_trace(level_index, m9_tables, chapter_count=chapter_count)
        row = {
            'level_index': level_index,
            'chapter': trace.chapter,
            'mission': level_index,
            'script_chunk': trace.script_chunk,
            'script_pack_name': trace.script_pack_name,
            'map_pack_name': trace.map_pack_name,
            'map_subchunk': trace.map_subchunk,
            'source': trace.source,
        }
        mission_links.append(row)
        chapter_index[trace.chapter].append(row)
    return {
        'chapter_count': chapter_count,
        'levels_total': len(mission_links),
        'mission_links': mission_links,
        'chapter_index': chapter_index,
    }


def build_semantic_level_exports(output: Path, m9_tables: dict[str, Any], m9_scripts: list[dict[str, Any]]) -> dict[str, Any]:
    levels_dir = output / 'scripts' / 'semantic'
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
        objects = []
        triggers = []
        command_links = []
        for command in commands:
            map_refs.extend(command.get('map_refs', []))
            objects.extend(command.get('object_placements', []))
            triggers.extend(command.get('triggers', []))
            command_links.extend(command.get('command_links', []))

        tile_layers = [
            {'pack': ref['pack'], 'subchunk': ref['subchunk'], 'kind': 'tile'}
            for ref in map_refs
            if ref.get('pack') and ref.get('subchunk') is not None
        ]
        collision_layers = [
            {'pack': ref['pack'], 'subchunk': ref['subchunk'] + 1, 'kind': 'collision'}
            for ref in map_refs
            if ref.get('pack') and ref.get('subchunk') is not None
        ]

        payload = {
            'level_index': level_index,
            'trace': trace.__dict__,
            'tile_layers': tile_layers,
            'collision_layers': collision_layers,
            'map_refs': map_refs,
            'objects': objects,
            'triggers': triggers,
            'command_links': command_links,
            'script_command_count': len(commands),
        }
        level_path = levels_dir / f'level_{level_index:02d}.json'
        write_json(level_path, payload)
        level_index_entries.append({'level_index': level_index, 'path': str(level_path.relative_to(output))})

    return {
        'levels_dir': str(levels_dir.relative_to(output)),
        'levels': level_index_entries,
    }
