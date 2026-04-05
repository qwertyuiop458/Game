from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from tools.common import CHAPTER_COUNT, COMMON_WIDTHS, JarProject, detect_m6_chapter_count, ensure_dir, pseudo_color, u16le, write_json, write_rgba_png
from tools.m9_semantics import build_chapter_mission_links
from tools.script_parser import (
    build_opcode_coverage,
    build_semantic_level_exports,
    parse_m8_chunk_semantic,
    parse_m9_chunk_tables,
    parse_script_chunk_semantic,
)


def factor_grid(cells: int) -> tuple[int, int]:
    if cells <= 0:
        return 1, 1
    best = (cells, 1)
    best_score = 10**18
    for width in COMMON_WIDTHS:
        if cells % width == 0:
            height = cells // width
            score = abs(height - width) + abs(width - 40)
            if score < best_score:
                best = (width, height)
                best_score = score
    if best_score < 10**18:
        return best
    for w in range(1, int(math.sqrt(cells)) + 1):
        if cells % w:
            continue
        h = cells // w
        score = abs(h - w)
        if score < best_score:
            best = (w, h)
            best_score = score
    return best


def parse_tile_chunk(chunk: bytes) -> dict[str, Any]:
    if not chunk:
        return {'skip': 0, 'cells': 0, 'width': 1, 'height': 1, 'values': [], 'tile_range': [0, 0], 'nonzero_cells': 0}
    candidates = []
    for skip in (0, 1):
        trimmed = chunk[skip:]
        even_len = len(trimmed) - (len(trimmed) % 2)
        values = [u16le(trimmed, pos) for pos in range(0, even_len, 2)]
        if not values:
            continue
        width, height = factor_grid(len(values))
        density = sum(1 for value in values if value) / len(values)
        candidates.append((abs(width - 40), -density, skip, values, width, height))
    if not candidates:
        return {'skip': 0, 'cells': 0, 'width': 1, 'height': 1, 'values': [], 'tile_range': [0, 0], 'nonzero_cells': 0}
    candidates.sort()
    _, _, skip, values, width, height = candidates[0]
    return {
        'skip': skip,
        'cells': len(values),
        'width': width,
        'height': height,
        'values': values,
        'tile_range': [min(values), max(values)],
        'nonzero_cells': sum(1 for value in values if value),
    }


def _build_m6_chunk_pairs(payload_count: int) -> list[dict[str, int | None]]:
    pairs: list[dict[str, int | None]] = []
    for tile_index in range(0, payload_count, 2):
        collision_index = tile_index + 1 if tile_index + 1 < payload_count else None
        pairs.append({'tile_chunk_index': tile_index, 'collision_chunk_index': collision_index})
    return pairs


def _build_mission_lookup(chapter_mission_links: dict[str, Any]) -> tuple[dict[int, list[dict[str, Any]]], dict[tuple[str, int], list[dict[str, Any]]]]:
    by_script_chunk: dict[int, list[dict[str, Any]]] = {}
    by_map_ref: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in chapter_mission_links.get('mission_links', []):
        script_chunk = row.get('script_chunk')
        if isinstance(script_chunk, int):
            by_script_chunk.setdefault(script_chunk, []).append(row)
        map_pack_name = row.get('map_pack_name')
        map_subchunk = row.get('map_subchunk')
        if isinstance(map_pack_name, str) and isinstance(map_subchunk, int):
            by_map_ref.setdefault((map_pack_name, map_subchunk), []).append(row)
    return by_script_chunk, by_map_ref


def _write_grid_csv(path: Path, values: list[int], width: int, height: int, field_name: str) -> None:
    ensure_dir(path.parent)
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['index', 'x', 'y', field_name])
        writer.writeheader()
        for index, value in enumerate(values):
            x = index % width if width else 0
            y = index // width if width else 0
            writer.writerow({'index': index, 'x': x, 'y': y, field_name: value})


def _write_rows_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, '') for name in fieldnames})


def build_final_table(project: JarProject, output: Path, maps_report: dict, script_report: dict, audio_report: dict, text_report: dict) -> list[dict[str, Any]]:
    chapter_count = detect_m6_chapter_count(project.containers, fallback=CHAPTER_COUNT)
    map_counts = {name: maps_report.get(name, {}).get('map_count', 0) for name in maps_report}
    rows = []
    chapter_names = [
        'GLT телестанция / вспышка',
        'Центр / бар Джо / улицы',
        'Озеро / лес / окраины',
        'Лаборатория Ротванга / кладбище',
        'Пожарная станция / зоопарк',
        'Секретный этаж / финал',
    ]
    enemy_hints = ['зомби, полицейские-зомби', 'зомби, заражённые собаки', 'военные, мутанты', 'лабораторные мутанты', 'животные-мутанты, тяжёлые враги', 'элитные мутанты, Ротванг']
    story_hints = [
        'ТВ-группа прибывает на место массового убийства и фиксирует старт заражения.',
        'Игрок проходит городские кварталы и связанные интерьеры, собирая ключевые предметы.',
        'Маршрут уводит в лес и лагерь повстанцев.',
        'Сюжет концентрируется вокруг лаборатории, отключения питания и кладбища.',
        'Локации становятся более экзотическими и давление на игрока возрастает.',
        'Финальная развязка ведёт к секретному этажу и бою с Ротвангом.',
    ]
    for chapter in range(chapter_count):
        rows.append({
            'chapter': chapter,
            'mission': chapter_names[chapter] if chapter < len(chapter_names) else f'Глава {chapter}',
            'map pack': f'm6_{chapter} ({map_counts.get(f"m6_{chapter}", 0)} maps)',
            'graphics pack': 'm3_0 + m4_0 + m7 + m11_0 + m11_1',
            'audio': 'm13_1/m13_2 MIDI + raw cues',
            'key enemies': enemy_hints[chapter] if chapter < len(enemy_hints) else 'n/a',
            'key story events': story_hints[chapter] if chapter < len(story_hints) else 'n/a',
        })
    md = output / 'docs' / 'reverse_engineering' / 'final_asset_table.md'
    ensure_dir(md.parent)
    headers = ['chapter', 'mission', 'map pack', 'graphics pack', 'audio', 'key enemies', 'key story events']
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row[h]) for h in headers) + ' |')
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(output / 'docs' / 'reverse_engineering' / 'final_asset_table.json', rows)
    return rows


def build_chapter_mission_matrix(
    project: JarProject,
    output: Path,
    maps_report: dict,
    script_report: dict,
    graphics_report: dict,
    audio_report: dict,
    text_report: dict,
) -> list[dict[str, Any]]:
    chapter_count = detect_m6_chapter_count(project.containers, fallback=CHAPTER_COUNT)

    def _validate_link(container: str, chunk_index: int | None = None) -> dict[str, Any]:
        container_obj = project.containers.get(container)
        if container_obj is None:
            return {'container': container, 'chunk_index': chunk_index, 'valid': False, 'error': f'container {container} is missing'}
        if chunk_index is None:
            return {'container': container, 'chunk_index': None, 'valid': True}
        if not (0 <= chunk_index < len(container_obj.payloads)):
            return {
                'container': container,
                'chunk_index': chunk_index,
                'valid': False,
                'error': f'chunk {container}#{chunk_index:02d} is missing',
            }
        return {'container': container, 'chunk_index': chunk_index, 'valid': True}

    def _partition(items: list[dict[str, Any]], chapter: int, chapter_count: int = chapter_count) -> list[dict[str, Any]]:
        if not items:
            return []
        block = max(1, (len(items) + chapter_count - 1) // chapter_count)
        start = chapter * block
        end = min(len(items), start + block)
        if start >= len(items):
            return []
        return items[start:end]

    def _extract_keywords(text_blob: str, keywords: list[str]) -> list[str]:
        lowered = text_blob.lower()
        found = []
        for word in keywords:
            if word in lowered:
                found.append(word)
        return found

    def _text_blob(entry: dict[str, Any]) -> str:
        rel = entry.get('reconstructed_path') or entry.get('path')
        if not rel:
            return ''
        candidate = output / rel
        if not candidate.exists():
            return ''
        return candidate.read_text(encoding='utf-8', errors='ignore')

    def _parse_audio_ref(path_value: Any, expected_suffix: str | None = None) -> dict[str, Any] | None:
        if not isinstance(path_value, str) or not path_value:
            return None

        path_obj = Path(path_value)
        parts = path_obj.parts
        if len(parts) < 4:
            return None
        if parts[0] != 'extracted' or parts[1] != 'audio':
            return None

        container = parts[2]
        chunk_name = parts[3]
        chunk_path = Path(chunk_name)
        if expected_suffix is not None and chunk_path.suffix.lower() != expected_suffix.lower():
            return None

        try:
            chunk_index = int(chunk_path.stem)
        except (TypeError, ValueError):
            return None

        return {'container': container, 'chunk_index': chunk_index}

    rows: list[dict[str, Any]] = []
    mission_links = script_report.get('m9', {}).get('chapter_mission_links', {}).get('mission_links', [])
    text_chunks = text_report.get('chunks', [])
    graphics_packs = sorted(graphics_report.get('containers', {}).keys())
    graphics_refs = [
        {'container': pack_name, 'chunk_index': chunk.get('chunk')}
        for pack_name, pack_payload in graphics_report.get('containers', {}).items()
        for chunk in pack_payload.get('chunks', [])
        if isinstance(chunk, dict) and isinstance(chunk.get('chunk'), int)
    ]
    by_chapter = {chapter: [] for chapter in range(chapter_count)}
    for item in mission_links:
        by_chapter[item.get('chapter', 0) % chapter_count].append(item)

    for chapter in range(chapter_count):
        map_pack = f'm6_{chapter}'
        chapter_missions = sorted(by_chapter.get(chapter, []), key=lambda row: row.get('mission', 0))

        if chapter_missions:
            mission_ids = sorted({item.get('mission', chapter) for item in chapter_missions})
            mission_label = ', '.join(f'#{mission}' for mission in mission_ids)
        else:
            mission_label = f'#{chapter}'

        audio_refs: list[dict[str, Any]] = []
        midi_rows = [
            ref
            for path in audio_report.get('midi', [])
            if (ref := _parse_audio_ref(path, expected_suffix='.mid')) is not None
        ]
        raw_rows = [
            ref
            for item in audio_report.get('raw_audio', [])
            if isinstance(item, dict) and (ref := _parse_audio_ref(item.get('path'))) is not None
        ]
        audio_refs.extend(_partition(midi_rows, chapter))
        audio_refs.extend(_partition(raw_rows, chapter))

        text_entry = text_chunks[chapter] if chapter < len(text_chunks) else (text_chunks[-1] if text_chunks else {})
        text_blob = _text_blob(text_entry) if isinstance(text_entry, dict) else ''
        enemy_terms = _extract_keywords(
            text_blob,
            ['zombie', 'zombies', 'mutant', 'mutants', 'soldier', 'dog', 'boss', 'ротванг', 'зомби', 'мутант', 'босс'],
        )
        story_terms = _extract_keywords(
            text_blob,
            ['lab', 'laboratory', 'tv', 'station', 'escape', 'final', 'fight', 'лаборатор', 'станц', 'побег', 'финал', 'бой'],
        )

        links = [
            {'kind': 'map_pack', **_validate_link(map_pack, None)},
            {'kind': 'text_chunk', **_validate_link('t0', text_entry.get('chunk_index') if isinstance(text_entry, dict) else None)},
        ]
        links.extend({'kind': 'graphics_chunk', **_validate_link(ref['container'], ref['chunk_index'])} for ref in graphics_refs)
        links.extend({'kind': 'audio_chunk', **_validate_link(ref['container'], ref['chunk_index'])} for ref in audio_refs)
        links.extend(
            {'kind': 'script_chunk', **_validate_link('m9', mission.get('script_chunk'))}
            for mission in chapter_missions
            if mission.get('script_chunk') is not None
        )
        invalid_links = [link for link in links if not link.get('valid')]

        rows.append(
            {
                'chapter': chapter,
                'mission': mission_label,
                'map pack': map_pack,
                'graphics pack': ', '.join(graphics_packs) if graphics_packs else 'n/a',
                'audio assets': [f"{ref['container']}#{ref['chunk_index']:02d}" for ref in audio_refs],
                'key enemies': ', '.join(enemy_terms[:4]) if enemy_terms else 'n/a',
                'key story events': ', '.join(story_terms[:4]) if story_terms else 'n/a',
                'links': links,
                'validation': {
                    'all_links_valid': not invalid_links,
                    'invalid_links': invalid_links,
                },
            }
        )

    meta_dir = output / 'extracted' / 'meta'
    ensure_dir(meta_dir)
    write_json(meta_dir / 'chapter_mission_matrix.json', rows)

    headers = ['chapter', 'mission', 'map pack', 'graphics pack', 'audio assets', 'key enemies', 'key story events']
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        lines.append(
            '| ' + ' | '.join(
                [
                    str(row['chapter']),
                    str(row['mission']),
                    str(row['map pack']),
                    str(row['graphics pack']),
                    ', '.join(row['audio assets']) or '-',
                    str(row['key enemies']),
                    str(row['key story events']),
                ]
            ) + ' |'
        )
    (meta_dir / 'chapter_mission_matrix.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return rows


def decode_maps(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    maps_dir = output / 'extracted' / 'maps'
    tiles_dir = output / 'extracted' / 'tiles'
    meta_dir = output / 'extracted' / 'meta'
    ensure_dir(maps_dir)
    ensure_dir(tiles_dir)
    ensure_dir(meta_dir)
    report: dict[str, Any] = {}
    level_manifest_entries: list[dict[str, Any]] = []
    m6_chunk_manifest: dict[str, list[dict[str, Any]]] = {}
    exported_tile_layers: list[dict[str, Any]] = []
    exported_collision_layers: list[dict[str, Any]] = []
    exported_trigger_data: list[dict[str, Any]] = []
    exported_object_placements: list[dict[str, Any]] = []

    chapter_count = detect_m6_chapter_count(project.containers, fallback=CHAPTER_COUNT)
    for name in [f'm6_{index}' for index in range(chapter_count) if f'm6_{index}' in project.containers]:
        container = project.containers[name]
        entries = []
        chunk_pairs = _build_m6_chunk_pairs(len(container.payloads))
        m6_chunk_manifest[name] = []
        for pair in chunk_pairs:
            idx = pair['tile_chunk_index']
            chunk = container.payloads[idx]
            parsed = parse_tile_chunk(chunk)
            width = parsed['width']
            height = parsed['height']
            rgba = [pseudo_color(value) for value in parsed['values']] + [0] * (width * height - len(parsed['values']))
            preview = maps_dir / name / f'{idx:02d}.png'
            write_rgba_png(preview, width, height, rgba)
            collision_chunk_index = pair['collision_chunk_index']
            sidecar = container.payloads[collision_chunk_index] if isinstance(collision_chunk_index, int) else b''
            collision_values = list(sidecar)
            tile_base = f'{idx:02d}_tile'
            collision_base = f'{idx:02d}_collision'

            tile_json = tiles_dir / name / f'{tile_base}.json'
            tile_csv = tiles_dir / name / f'{tile_base}.csv'
            collision_json = maps_dir / name / f'{collision_base}.json'
            collision_csv = maps_dir / name / f'{collision_base}.csv'

            tile_payload = {
                'container': name,
                'chunk_index': idx,
                'kind': 'tile_layer',
                'width': width,
                'height': height,
                'cell_count': parsed['cells'],
                'skip': parsed['skip'],
                'tile_range': parsed['tile_range'],
                'nonzero_cells': parsed['nonzero_cells'],
                'values': parsed['values'],
            }
            collision_payload = {
                'container': name,
                'chunk_index': collision_chunk_index,
                'paired_tile_chunk_index': idx,
                'kind': 'collision_layer',
                'width': width,
                'height': height,
                'cell_count': len(collision_values),
                'values': collision_values,
            }
            write_json(tile_json, tile_payload)
            _write_grid_csv(tile_csv, parsed['values'], width, height, 'tile_id')
            write_json(collision_json, collision_payload)
            _write_grid_csv(collision_csv, collision_values, width, height, 'collision')

            meta = {
                'container': name,
                'chunk_index': idx,
                'preview_png': str(preview.relative_to(output)),
                'tile_json': str(tile_json.relative_to(output)),
                'tile_csv': str(tile_csv.relative_to(output)),
                'collision_json': str(collision_json.relative_to(output)),
                'collision_csv': str(collision_csv.relative_to(output)),
                'collision_layer_preview': collision_values[:128],
                **{k: v for k, v in parsed.items() if k != 'values'},
                'tile_preview': parsed['values'][:128],
            }
            write_json(maps_dir / name / f'{idx:02d}.json', meta)
            entries.append(meta)
            m6_chunk_manifest[name].append({
                'tile_chunk_index': idx,
                'collision_chunk_index': collision_chunk_index,
                'tile_json': str(tile_json.relative_to(output)),
                'tile_csv': str(tile_csv.relative_to(output)),
                'collision_json': str(collision_json.relative_to(output)),
                'collision_csv': str(collision_csv.relative_to(output)),
                'preview_png': str(preview.relative_to(output)),
            })
            exported_tile_layers.append({
                'container': name,
                'tile_chunk_index': idx,
                'collision_chunk_index': collision_chunk_index,
                'width': width,
                'height': height,
                'cell_count': parsed['cells'],
                'tile_json': str(tile_json.relative_to(output)),
            })
            exported_collision_layers.append({
                'container': name,
                'tile_chunk_index': idx,
                'collision_chunk_index': collision_chunk_index,
                'width': width,
                'height': height,
                'cell_count': len(collision_values),
                'collision_json': str(collision_json.relative_to(output)),
            })
        report[name] = {'map_count': len(entries), 'maps': entries}

    docs_dir = output / 'docs' / 'reverse_engineering'
    ensure_dir(docs_dir)
    scripts: dict[str, Any] = {}
    mission_by_script_chunk: dict[int, list[dict[str, Any]]] = {}
    mission_by_map_ref: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for name in ('m8', 'm9', 'm10'):
        container = project.containers.get(name)
        if not container:
            continue
        if name == 'm8':
            chunks = []
            for idx, chunk in enumerate(container.payloads):
                parsed = parse_m8_chunk_semantic(chunk)
                tile_layers = [ref for command in parsed['commands'] for ref in command.get('map_refs', [])]
                collision_layers = [
                    {'pack': ref.get('pack'), 'subchunk': ref.get('subchunk', 0) + 1}
                    for ref in tile_layers
                    if ref.get('subchunk') is not None
                ]
                triggers = [item for command in parsed['commands'] for item in command.get('triggers', [])]
                objects = [item for command in parsed['commands'] for item in command.get('object_placements', [])]
                path = docs_dir / f'm8_chunk_{idx:02d}.json'
                write_json(path, parsed)
                chunks.append(
                    {
                        'chunk_index': idx,
                        'size': len(chunk),
                        'path': str(path.relative_to(output)),
                        'opcode_histogram': parsed['opcode_histogram'],
                        'tile_layers': tile_layers,
                        'collision_layers': collision_layers,
                        'triggers': triggers,
                        'objects': objects,
                    }
                )
            scripts['m8'] = {'chunk_count': len(chunks), 'chunks': chunks}
        elif name == 'm9':
            table_chunks = parse_m9_chunk_tables(container.payloads)
            chapter_mission_links = build_chapter_mission_links(table_chunks)
            mission_by_script_chunk, mission_by_map_ref = _build_mission_lookup(chapter_mission_links)
            script_packs = []
            semantic_rows = []
            for idx, chunk in enumerate(container.payloads):
                if idx < 10:
                    continue
                parsed = parse_script_chunk_semantic(chunk)
                path = docs_dir / f'm9_script_{idx:02d}.json'
                write_json(path, parsed)
                script_packs.append({
                    'chunk_index': idx,
                    'size': len(chunk),
                    'path': str(path.relative_to(output)),
                    'chapter_mission_links': mission_by_script_chunk.get(idx, []),
                    'opcode_histogram': parsed['opcode_histogram'],
                    'semantic_known_count': parsed['semantic_known_count'],
                    'semantic_unknown_count': parsed['semantic_unknown_count'],
                    'tile_layers': [ref for command in parsed['commands'] for ref in command.get('map_refs', [])],
                    'collision_layers': [
                        {'pack': ref.get('pack'), 'subchunk': ref.get('subchunk', 0) + 1}
                        for command in parsed['commands']
                        for ref in command.get('map_refs', [])
                        if ref.get('subchunk') is not None
                    ],
                    'triggers': [item for command in parsed['commands'] for item in command.get('triggers', [])],
                    'objects': [item for command in parsed['commands'] for item in command.get('object_placements', [])],
                })
                semantic_rows.append({'chunk_index': idx, 'commands': parsed['commands']})

            semantic_levels = build_semantic_level_exports(output, table_chunks, semantic_rows)
            opcode_coverage = build_opcode_coverage(semantic_rows)
            level_rows: list[dict[str, Any]] = []
            for level_entry in semantic_levels.get('levels', []):
                level_path = output / level_entry['path']
                if not level_path.exists():
                    continue
                level_payload = json.loads(level_path.read_text(encoding='utf-8'))
                level_index = level_payload.get('level_index', 0)
                trace = level_payload.get('trace', {})
                chapter = trace.get('chapter', 0)
                map_pack = trace.get('map_pack_name', f'm6_{chapter}')
                map_subchunk = trace.get('map_subchunk', 0)
                object_rows = [
                    {
                        'level_index': level_index,
                        'object_order': obj_index,
                        'object_id': obj.get('object_id'),
                        'x': obj.get('x'),
                        'y': obj.get('y'),
                    }
                    for obj_index, obj in enumerate(level_payload.get('objects', []))
                ]
                trigger_rows = [
                    {
                        'level_index': level_index,
                        'trigger_order': trg_index,
                        'trigger_id': trg.get('trigger_id'),
                        'event_code': trg.get('event_code'),
                    }
                    for trg_index, trg in enumerate(level_payload.get('triggers', []))
                ]
                objects_json = maps_dir / f'level_{level_index:02d}_objects.json'
                objects_csv = maps_dir / f'level_{level_index:02d}_objects.csv'
                triggers_json = maps_dir / f'level_{level_index:02d}_triggers.json'
                triggers_csv = maps_dir / f'level_{level_index:02d}_triggers.csv'
                write_json(objects_json, {'level_index': level_index, 'objects': object_rows})
                write_json(triggers_json, {'level_index': level_index, 'triggers': trigger_rows})
                _write_rows_csv(objects_csv, object_rows, ['level_index', 'object_order', 'object_id', 'x', 'y'])
                _write_rows_csv(triggers_csv, trigger_rows, ['level_index', 'trigger_order', 'trigger_id', 'event_code'])

                level_export = {
                    'level_index': level_index,
                    'tile_layers': level_payload.get('tile_layers', []),
                    'collision_layers': level_payload.get('collision_layers', []),
                    'triggers': level_payload.get('triggers', []),
                    'objects': level_payload.get('objects', []),
                    'trace': trace,
                    'chapter_mission_links': mission_by_script_chunk.get(trace.get('script_chunk'), []),
                    'source_chunks': {
                        'm9_script_chunk': trace.get('script_chunk'),
                        'm9_table_chunk': 0,
                        'm8_subchunk_index': sorted({link.get('subchunk_index') for link in level_payload.get('command_links', []) if link.get('target') == 'm8' and link.get('subchunk_index') is not None}),
                        'm6_pack': map_pack,
                        'm6_tile_chunk_index': map_subchunk if map_subchunk is not None else None,
                        'm6_collision_chunk_index': (map_subchunk + 1) if isinstance(map_subchunk, int) else None,
                    },
                    'objects_json': str(objects_json.relative_to(output)),
                    'objects_csv': str(objects_csv.relative_to(output)),
                    'triggers_json': str(triggers_json.relative_to(output)),
                    'triggers_csv': str(triggers_csv.relative_to(output)),
                }
                write_json(maps_dir / f'level_{level_index:02d}.json', level_export)
                level_rows.append(level_export)
                chapter_mission = next(
                    (
                        row for row in mission_by_script_chunk.get(trace.get('script_chunk'), [])
                        if row.get('level_index') == level_index
                    ),
                    None,
                )
                chapter_value = chapter_mission.get('chapter') if chapter_mission else trace.get('chapter')
                mission_value = chapter_mission.get('mission') if chapter_mission else level_index
                for layer in level_export['tile_layers']:
                    exported_tile_layers.append({
                        'container': layer.get('pack'),
                        'tile_chunk_index': layer.get('subchunk'),
                        'collision_chunk_index': (layer.get('subchunk') + 1) if isinstance(layer.get('subchunk'), int) else None,
                        'chapter': chapter_value,
                        'mission': mission_value,
                        'source': 'm9_semantic_level',
                        'level_index': level_index,
                    })
                for layer in level_export['collision_layers']:
                    exported_collision_layers.append({
                        'container': layer.get('pack'),
                        'tile_chunk_index': (layer.get('subchunk') - 1) if isinstance(layer.get('subchunk'), int) else None,
                        'collision_chunk_index': layer.get('subchunk'),
                        'chapter': chapter_value,
                        'mission': mission_value,
                        'source': 'm9_semantic_level',
                        'level_index': level_index,
                    })
                for trigger in level_export['triggers']:
                    exported_trigger_data.append({
                        **trigger,
                        'level_index': level_index,
                        'chapter': chapter_value,
                        'mission': mission_value,
                        'script_chunk': trace.get('script_chunk'),
                    })
                for obj in level_export['objects']:
                    exported_object_placements.append({
                        **obj,
                        'level_index': level_index,
                        'chapter': chapter_value,
                        'mission': mission_value,
                        'script_chunk': trace.get('script_chunk'),
                    })
                level_manifest_entries.append({
                    'level_index': level_index,
                    'map_pack': map_pack,
                    'source_chunks': level_export['source_chunks'],
                    'level_json': str((maps_dir / f'level_{level_index:02d}.json').relative_to(output)),
                })

            scripts['m9'] = {
                **table_chunks,
                'chapter_mission_links': chapter_mission_links,
                'chunk10_plus_scripts': script_packs,
                'semantic_levels': semantic_levels,
                'opcode_coverage': opcode_coverage,
                'level_exports': [
                    {
                        'level_index': row['level_index'],
                        'path': str((maps_dir / f'level_{row["level_index"]:02d}.json').relative_to(output)),
                    }
                    for row in level_rows
                ],
            }
        else:
            chunks = []
            for idx, chunk in enumerate(container.payloads):
                values = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
                path = docs_dir / f'm10_chunk_{idx:02d}.json'
                write_json(path, {'chunk_index': idx, 'size': len(chunk), 'u16_count': len(values), 'u16_preview': values[:128], 'nonzero_values': sum(1 for value in values if value), 'max_u16': max(values) if values else 0})
                chunks.append(
                    {
                        'chunk_index': idx,
                        'size': len(chunk),
                        'path': str(path.relative_to(output)),
                        'tile_layers': [],
                        'collision_layers': [],
                        'triggers': [],
                        'objects': [],
                    }
                )
            scripts['m10'] = {'chapter_chunks': chunks}

    write_json(maps_dir / 'maps_index.json', report)
    write_json(tiles_dir / 'tile_layers.json', {'tile_layers': exported_tile_layers})
    write_json(maps_dir / 'collision_layers.json', {'collision_layers': exported_collision_layers})
    write_json(maps_dir / 'trigger_data.json', {'triggers': exported_trigger_data})
    write_json(maps_dir / 'object_placement.json', {'objects': exported_object_placements})
    write_json(
        maps_dir / 'chapter_mission_cross_links.json',
        {
            'by_script_chunk': {str(key): value for key, value in sorted(mission_by_script_chunk.items())},
            'by_map_ref': {f'{key[0]}#{key[1]}': value for key, value in sorted(mission_by_map_ref.items())},
        },
    )
    write_json(meta_dir / 'maps_manifest.json', {
        'version': 1,
        'generated_by': 'tools.decode_maps',
        'm6_chunk_manifest': m6_chunk_manifest,
        'levels': sorted(level_manifest_entries, key=lambda row: row['level_index']),
        'script_containers': {
            'm8': scripts.get('m8', {}),
            'm9': {
                'chunk_count': len(scripts.get('m9', {}).get('chunk10_plus_scripts', [])),
                'chapter_mission_links': scripts.get('m9', {}).get('chapter_mission_links', {}),
                'level_exports': scripts.get('m9', {}).get('level_exports', []),
            },
            'm10': scripts.get('m10', {}),
        },
    })
    write_json(output / 'docs' / 'reverse_engineering' / 'scripts_index.json', scripts)
    return {'maps': report, 'scripts': scripts}


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode map/script packs (m6_*, m8, m9, m10)')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_maps(args.jar, args.output)


if __name__ == '__main__':
    main()
