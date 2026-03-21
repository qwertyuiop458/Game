#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from tools.common import Container, ensure_dir, factor_grid, open_jar_resources, pseudo_color, rgb565_to_rgba, u16le, write_json, write_rgba_png


def parse_script_stream(chunk: bytes) -> dict[str, Any]:
    cursor = 0
    commands = []
    opcode_hist = Counter()
    refs = []
    while cursor < len(chunk):
        opcode = chunk[cursor]
        opcode_hist[opcode] += 1
        start = cursor
        cursor += 1
        if opcode in {101, 102} and cursor + 1 <= len(chunk):
            size = chunk[cursor]
            cursor += 1
            payload = chunk[cursor:cursor + size * 2 + 6]
            refs.append({'offset': start, 'opcode': opcode, 'payload_preview': list(payload[:16])})
            commands.append({'offset': start, 'opcode': opcode, 'payload_size': len(payload)})
            cursor += len(payload)
            continue
        if opcode == 99 and cursor + 5 <= len(chunk):
            ref = {
                'offset': start,
                'opcode': opcode,
                'map_pack': chunk[cursor],
                'subchunk': chunk[cursor + 1],
                'tail': list(chunk[cursor + 2:cursor + 5]),
            }
            refs.append(ref)
            commands.append(ref)
            cursor += 5
            continue
        if opcode == 200 and cursor < len(chunk):
            size = chunk[cursor]
            cursor += 1
            commands.append({'offset': start, 'opcode': opcode, 'payload_size': size})
            cursor += size
            continue
        if cursor + 7 > len(chunk):
            commands.append({'offset': start, 'opcode': opcode, 'truncated': True})
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
        commands.append({
            'offset': start,
            'opcode': opcode,
            'meta': meta,
            'pair_count': pair_count,
            'params_preview': params[:24],
        })
    return {
        'command_count': len(commands),
        'opcode_histogram': dict(sorted(opcode_hist.items())),
        'commands_preview': commands[:128],
        'map_references': refs,
    }


def decode_tile_packs(resources: dict[str, bytes], maps_dir: Path) -> dict[str, Any]:
    ensure_dir(maps_dir)
    report: dict[str, Any] = {}
    for name in [f'm6_{idx}' for idx in range(6) if f'm6_{idx}' in resources]:
        container = Container(name, resources[name])
        entries = []
        for idx, chunk in enumerate(container.payloads):
            if idx % 2 == 1:
                continue
            values = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
            width, height = factor_grid(len(values))
            pseudo_path = maps_dir / name / f'{idx:02d}_tiles.png'
            rgb565_path = maps_dir / name / f'{idx:02d}_rgb565.png'
            write_rgba_png(pseudo_path, width, height, [pseudo_color(v) for v in values] + [0] * (width * height - len(values)))
            write_rgba_png(rgb565_path, width, height, [rgb565_to_rgba(v) for v in values] + [0] * (width * height - len(values)))
            entry = {
                'chunk_index': idx,
                'cells': len(values),
                'width_guess': width,
                'height_guess': height,
                'tile_range': [min(values) if values else 0, max(values) if values else 0],
                'nonzero_cells': sum(1 for value in values if value),
                'collision_sidecar_hex': container.payloads[idx + 1].hex() if idx + 1 < len(container.payloads) else '',
                'tile_preview': values[:128],
                'tile_layer_png': str(pseudo_path),
                'collision_layer_png': str(rgb565_path),
            }
            write_json(maps_dir / name / f'{idx:02d}.json', entry)
            entries.append(entry)
        report[name] = {'map_count': len(entries), 'maps': entries}
    return report


def decode_script_packs(resources: dict[str, bytes], docs_dir: Path) -> dict[str, Any]:
    ensure_dir(docs_dir)
    summary: dict[str, Any] = {}
    if 'm8' in resources:
        container = Container('m8', resources['m8'])
        chunks = []
        for idx, chunk in enumerate(container.payloads):
            parsed = parse_script_stream(chunk)
            path = docs_dir / f'm8_{idx:02d}.json'
            write_json(path, parsed)
            chunks.append({'chunk_index': idx, 'path': str(path), 'opcode_histogram': parsed['opcode_histogram']})
        summary['m8'] = {'chunk_count': len(chunks), 'chunks': chunks}

    if 'm9' in resources:
        container = Container('m9', resources['m9'])
        tables = []
        scripts = []
        for idx, chunk in enumerate(container.payloads):
            if idx >= 10:
                parsed = parse_script_stream(chunk)
                path = docs_dir / f'm9_script_{idx:02d}.json'
                write_json(path, parsed)
                scripts.append({'chunk_index': idx, 'path': str(path), 'opcode_histogram': parsed['opcode_histogram']})
            else:
                tables.append({
                    'chunk_index': idx,
                    'size': len(chunk),
                    'u16_preview': [u16le(chunk, pos) for pos in range(0, min(len(chunk) - (len(chunk) % 2), 64), 2)],
                })
        summary['m9'] = {'lookup_chunks': tables, 'script_chunks': scripts}

    if 'm10' in resources:
        container = Container('m10', resources['m10'])
        chapters = []
        for idx, chunk in enumerate(container.payloads):
            path = docs_dir / f'm10_{idx:02d}.json'
            values = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
            write_json(path, {
                'chunk_index': idx,
                'u16_preview': values[:128],
                'nonzero_values': sum(1 for value in values if value),
                'max_u16': max(values) if values else 0,
            })
            chapters.append({'chapter': idx, 'path': str(path)})
        summary['m10'] = {'chapter_chunks': chapters}
    return summary


def build_final_table(map_summary: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for chapter in range(6):
        map_pack = f'm6_{chapter}'
        rows.append({
            'chapter': chapter,
            'mission': f'Chapter {chapter}',
            'map_pack': map_pack,
            'graphics_pack': 'm3_0 + m4_0 + m7 + m11_0 + m11_1',
            'audio_assets': 'm13_1 / m13_2',
            'key_enemies': 'zombies / mutants (from shared art + scripts)',
            'key_story_events': 'see m8/m9 script JSON previews for chapter-specific flow',
            'map_count': map_summary.get(map_pack, {}).get('map_count', 0),
            'mission_index_hint': chapter,
        })
    md = output_dir / 'final_asset_table.md'
    headers = ['chapter', 'mission', 'map_pack', 'graphics_pack', 'audio_assets', 'key_enemies', 'key_story_events', 'map_count', 'mission_index_hint']
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row[key]) for key in headers) + ' |')
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(output_dir / 'final_asset_table.json', rows)
    return rows


def decode_maps(jar_path: Path, output_root: Path) -> dict[str, Any]:
    resources = open_jar_resources(jar_path)
    maps_dir = output_root / 'maps'
    docs_dir = output_root / 'maps' / 'script_docs'
    ensure_dir(maps_dir)
    tile_summary = decode_tile_packs(resources, maps_dir)
    script_summary = decode_script_packs(resources, docs_dir)
    final_table = build_final_table(tile_summary, output_root / 'maps')
    summary = {'tile_packs': tile_summary, 'script_packs': script_summary, 'final_table_rows': len(final_table)}
    write_json(output_root / 'maps' / 'maps_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode map/script packs')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out/extracted'))
    args = parser.parse_args()
    decode_maps(args.jar, args.output)


if __name__ == '__main__':
    main()
