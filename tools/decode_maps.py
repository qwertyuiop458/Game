from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from tools.common import COMMON_WIDTHS, JarProject, ensure_dir, pseudo_color, u16le, write_json, write_rgba_png
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
    for chapter in range(6):
        rows.append({
            'chapter': chapter,
            'mission': chapter_names[chapter],
            'map pack': f'm6_{chapter} ({map_counts.get(f"m6_{chapter}", 0)} maps)',
            'graphics pack': 'm3_0 + m4_0 + m7 + m11_0 + m11_1',
            'audio assets': 'm13_1/m13_2 MIDI + raw cues',
            'key enemies': enemy_hints[chapter],
            'key story events': story_hints[chapter],
            'script pack': f'm9#{10 + chapter}',
            'm8 linkage': f'm8#{chapter}',
        })
    md = output / 'docs' / 'reverse_engineering' / 'final_asset_table.md'
    ensure_dir(md.parent)
    headers = ['chapter', 'mission', 'map pack', 'graphics pack', 'audio assets', 'key enemies', 'key story events', 'script pack', 'm8 linkage']
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row[h]) for h in headers) + ' |')
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(output / 'docs' / 'reverse_engineering' / 'final_asset_table.json', rows)
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

    for name in [f'm6_{index}' for index in range(6) if f'm6_{index}' in project.containers]:
        container = project.containers[name]
        entries = []
        m6_chunk_manifest[name] = []
        for idx, chunk in enumerate(container.payloads):
            if idx % 2 == 1:
                continue
            parsed = parse_tile_chunk(chunk)
            width = parsed['width']
            height = parsed['height']
            rgba = [pseudo_color(value) for value in parsed['values']] + [0] * (width * height - len(parsed['values']))
            preview = maps_dir / name / f'{idx:02d}.png'
            write_rgba_png(preview, width, height, rgba)
            sidecar = container.payloads[idx + 1] if idx + 1 < len(container.payloads) else b''
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
                'chunk_index': idx + 1,
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
                'collision_chunk_index': idx + 1 if idx + 1 < len(container.payloads) else None,
                'tile_json': str(tile_json.relative_to(output)),
                'tile_csv': str(tile_csv.relative_to(output)),
                'collision_json': str(collision_json.relative_to(output)),
                'collision_csv': str(collision_csv.relative_to(output)),
                'preview_png': str(preview.relative_to(output)),
            })
        report[name] = {'map_count': len(entries), 'maps': entries}

    docs_dir = output / 'docs' / 'reverse_engineering'
    ensure_dir(docs_dir)
    scripts: dict[str, Any] = {}
    for name in ('m8', 'm9', 'm10'):
        container = project.containers.get(name)
        if not container:
            continue
        if name == 'm8':
            chunks = []
            for idx, chunk in enumerate(container.payloads):
                parsed = parse_m8_chunk_semantic(chunk)
                path = docs_dir / f'm8_chunk_{idx:02d}.json'
                write_json(path, parsed)
                chunks.append({'chunk_index': idx, 'size': len(chunk), 'path': str(path.relative_to(output)), 'opcode_histogram': parsed['opcode_histogram']})
            scripts['m8'] = {'chunk_count': len(chunks), 'chunks': chunks}
        elif name == 'm9':
            table_chunks = parse_m9_chunk_tables(container.payloads)
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
                    'opcode_histogram': parsed['opcode_histogram'],
                    'semantic_known_count': parsed['semantic_known_count'],
                    'semantic_unknown_count': parsed['semantic_unknown_count'],
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
                level_manifest_entries.append({
                    'level_index': level_index,
                    'map_pack': map_pack,
                    'source_chunks': level_export['source_chunks'],
                    'level_json': str((maps_dir / f'level_{level_index:02d}.json').relative_to(output)),
                })

            scripts['m9'] = {
                **table_chunks,
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
                chunks.append({'chunk_index': idx, 'size': len(chunk), 'path': str(path.relative_to(output))})
            scripts['m10'] = {'chapter_chunks': chunks}

    write_json(maps_dir / 'maps_index.json', report)
    write_json(meta_dir / 'maps_manifest.json', {
        'version': 1,
        'generated_by': 'tools.decode_maps',
        'm6_chunk_manifest': m6_chunk_manifest,
        'levels': sorted(level_manifest_entries, key=lambda row: row['level_index']),
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
