from __future__ import annotations

import argparse
import json
import math
import re
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


def _partition_even(items: list[Any], chapter: int, chapter_count: int) -> list[Any]:
    if not items:
        return []
    block = max(1, (len(items) + max(1, chapter_count) - 1) // max(1, chapter_count))
    start = chapter * block
    end = min(len(items), start + block)
    if start >= len(items):
        return []
    return items[start:end]


def _collect_story_markers(output: Path, text_report: dict[str, Any] | None) -> list[str]:
    if not text_report:
        return []
    markers: list[str] = []
    seen: set[str] = set()
    keywords = (
        'glt', 'gtv', 'телест', 'центр', 'бар', 'озер', 'лес', 'лаборатор',
        'кладбищ', 'пожар', 'зоопарк', 'секрет', 'ротванг', 'улиц',
    )
    for chunk in text_report.get('chunks', []):
        rel = chunk.get('segment_guess_path')
        if not rel:
            continue
        path = output / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        for item in data.get('strings', []):
            text = re.sub(r'\s+', ' ', item.get('text', '')).strip()
            lowered = text.lower()
            if len(text) < 8:
                continue
            if not any(keyword in lowered for keyword in keywords):
                continue
            if text not in seen:
                seen.add(text)
                markers.append(text)
    return markers


def build_chapter_mission_matrix(
    project: JarProject,
    output: Path,
    maps_report: dict[str, Any],
    script_report: dict[str, Any],
    audio_report: dict[str, Any],
    text_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    chapter_indices = sorted(
        int(name.split('_')[1])
        for name in maps_report
        if name.startswith('m6_') and name.split('_')[1].isdigit()
    )
    if not chapter_indices:
        chapter_indices = list(range(6))
    chapter_count = len(chapter_indices)

    graphics_packs = [name for name in ('m3_0', 'm4_0', 'm11_0', 'm11_1') if name in project.containers]
    m8_count = len(project.containers['m8'].payloads) if 'm8' in project.containers else 0
    m9_payloads = project.containers['m9'].payloads if 'm9' in project.containers else []

    midi_assets = [Path(path).stem for path in audio_report.get('midi', [])]
    raw_assets = [Path(item['path']).stem for item in audio_report.get('raw_audio', [])]
    story_markers = _collect_story_markers(output, text_report)

    chapter_story_keywords = {
        0: ('glt', 'телест', 'центр', 'вост', 'gltцентр'),
        1: ('бар', 'склад', 'улиц', 'джо'),
        2: ('озер', 'лес', 'лагер'),
        3: ('лаборатор', 'кладбищ', 'ротванг'),
        4: ('пожар', 'зоопарк'),
        5: ('секрет', 'финал', 'ротванг'),
    }

    rows: list[dict[str, Any]] = []
    for chapter in chapter_indices:
        map_pack = f'm6_{chapter}'
        map_count = maps_report.get(map_pack, {}).get('map_count', 0)
        m8_ref = f'm8#{chapter:02d}' if chapter < m8_count else None
        m9_chunk = 10 + chapter
        m9_ref = f'm9#{m9_chunk:02d}' if m9_chunk < len(m9_payloads) else None

        enemy_ids: list[int] = []
        if m9_ref:
            parsed = parse_script_chunk_semantic(m9_payloads[m9_chunk])
            for command in parsed.get('commands', []):
                for placement in command.get('object_placements', []):
                    object_id = placement.get('object_id')
                    if isinstance(object_id, int):
                        enemy_ids.append(object_id)
        unique_enemy_ids = sorted(set(enemy_ids))
        enemy_label = (
            ', '.join(f'obj#{value}' for value in unique_enemy_ids[:6])
            if unique_enemy_ids else
            'не выделены (нет явных object_placements в m9)'
        )

        chapter_markers = []
        for marker in story_markers:
            lowered = marker.lower()
            if any(keyword in lowered for keyword in chapter_story_keywords.get(chapter, ())):
                chapter_markers.append(marker)
        if not chapter_markers:
            chapter_markers = _partition_even(story_markers, chapter, chapter_count)

        mission = chapter_markers[0] if chapter_markers else f'Chapter {chapter + 1}'
        key_story = chapter_markers[:3] if chapter_markers else ['(нет явных маркеров в t0)']

        rows.append({
            'chapter': chapter,
            'mission': mission,
            'map pack': {'id': map_pack, 'map_count': map_count, 'm8_link': m8_ref},
            'graphics pack': graphics_packs,
            'audio assets': {
                'midi': [f'm13:{name}' for name in _partition_even(midi_assets, chapter, chapter_count)],
                'raw': [f'm13:{name}' for name in _partition_even(raw_assets, chapter, chapter_count)],
            },
            'key enemies': enemy_label,
            'key story events': key_story,
            'sources': {
                'm9_script': m9_ref,
                'm8_mission': m8_ref,
                'm6_map_pack': map_pack,
                'graphics': graphics_packs,
                'audio': ['m13_1', 'm13_2'],
                't0_chunks': [chunk['chunk_index'] for chunk in (text_report or {}).get('chunks', [])],
            },
        })

    meta_dir = output / 'extracted' / 'meta'
    ensure_dir(meta_dir)
    json_path = meta_dir / 'chapter_mission_matrix.json'
    md_path = meta_dir / 'chapter_mission_matrix.md'
    write_json(json_path, rows)

    headers = ['chapter', 'mission', 'map pack', 'graphics pack', 'audio assets', 'key enemies', 'key story events']
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        map_col = f"{row['map pack']['id']} ({row['map pack']['map_count']} maps, m8={row['map pack']['m8_link'] or '-'})"
        graphics_col = ', '.join(row['graphics pack']) if row['graphics pack'] else '-'
        audio_col = (
            'MIDI: ' + (', '.join(row['audio assets']['midi']) or '-') + '<br>'
            + 'RAW: ' + (', '.join(row['audio assets']['raw']) or '-')
        )
        story_col = '<br>'.join(row['key story events']) if row['key story events'] else '-'
        lines.append(
            '| ' + ' | '.join([
                str(row['chapter']),
                str(row['mission']).replace('\n', ' '),
                map_col,
                graphics_col,
                audio_col,
                str(row['key enemies']),
                story_col.replace('\n', ' '),
            ]) + ' |'
        )
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return rows


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
    ensure_dir(maps_dir)
    report: dict[str, Any] = {}

    for name in [f'm6_{index}' for index in range(6) if f'm6_{index}' in project.containers]:
        container = project.containers[name]
        entries = []
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
            meta = {
                'container': name,
                'chunk_index': idx,
                'preview_png': str(preview.relative_to(output)),
                'collision_layer': list(sidecar),
                **{k: v for k, v in parsed.items() if k != 'values'},
                'tile_preview': parsed['values'][:128],
            }
            write_json(maps_dir / name / f'{idx:02d}.json', meta)
            entries.append(meta)
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
            scripts['m9'] = {
                **table_chunks,
                'chunk10_plus_scripts': script_packs,
                'semantic_levels': semantic_levels,
                'opcode_coverage': opcode_coverage,
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
