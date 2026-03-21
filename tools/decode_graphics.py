#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import math
from pathlib import Path
from typing import Any

from tools.common import (
    Container,
    argb4444_to_rgba,
    argb8888_to_rgba,
    ensure_dir,
    factor_grid,
    open_jar_resources,
    pseudo_color,
    rgb565_to_rgba,
    u8,
    u16le,
    u32le,
    write_json,
    write_rgba_png,
)

GRAPHICS_PACKS = ('m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1')


def unpack_nibbles(data: bytes) -> list[int]:
    out: list[int] = []
    for value in data:
        out.append((value >> 4) & 0xF)
        out.append(value & 0xF)
    return out


def make_palette_preview(colors: list[int], swatch: int = 16) -> tuple[int, int, list[int]]:
    width = max(1, len(colors))
    height = swatch
    rgba: list[int] = []
    for _ in range(height):
        rgba.extend(colors)
    return width, height, rgba


def render_indexed(indices: list[int], width: int, height: int, palette: list[int], transparent_index: int | None = None) -> list[int]:
    rgba: list[int] = []
    for index in indices[:width * height]:
        if transparent_index is not None and index == transparent_index:
            rgba.append(0)
        else:
            rgba.append(palette[index % len(palette)] if palette else pseudo_color(index))
    if len(rgba) < width * height:
        rgba.extend([0] * (width * height - len(rgba)))
    return rgba


def parse_sprite_bank_metadata(blob: bytes) -> dict[str, Any]:
    pos = 2
    flags = u32le(blob, pos)
    pos += 4
    region_count = u16le(blob, pos)
    pos += 2
    sprite_regions = []
    atlas_width = 0
    atlas_height = 0
    for index in range(region_count):
        kind = u8(blob, pos)
        pos += 1
        if kind in (254, 255):
            color = u32le(blob, pos)
            pos += 4
            width = u8(blob, pos)
            height = u8(blob, pos + 1)
            pos += 2
            sprite_regions.append({
                'index': index,
                'kind': kind,
                'color_argb': f'0x{color:08x}',
                'x': 0,
                'y': 0,
                'width': width,
                'height': height,
            })
        else:
            x = u16le(blob, pos)
            y = u16le(blob, pos + 2)
            width = u16le(blob, pos + 4)
            height = u16le(blob, pos + 6)
            pos += 8
            atlas_width = max(atlas_width, x + width)
            atlas_height = max(atlas_height, y + height)
            sprite_regions.append({
                'index': index,
                'kind': kind,
                'x': x,
                'y': y,
                'width': width,
                'height': height,
            })

    module_count = u16le(blob, pos)
    pos += 2
    modules = []
    for index in range(module_count):
        modules.append({
            'index': index,
            'module_type': u8(blob, pos),
            'x': u16le(blob, pos + 1),
            'y': u16le(blob, pos + 3),
            'flags': u8(blob, pos + 5),
        })
        pos += 6

    frame_tables = []
    if flags & 0x8000:
        frame_table_count = u16le(blob, pos)
        pos += 2
        for index in range(frame_table_count):
            frame_tables.append({'index': index, 'values': [u8(blob, pos + i) for i in range(4)]})
            pos += 4

    frame_count = u16le(blob, pos)
    pos += 2
    frames = []
    for index in range(frame_count):
        frame = {
            'index': index,
            'region_index': u8(blob, pos),
            'duration_or_flags': u16le(blob, pos + 1),
        }
        pos += 3
        if flags & 0x8000:
            frame['extra_run_length'] = u8(blob, pos)
            pos += 1
        frames.append(frame)

    composition_count = u16le(blob, pos)
    pos += 2
    compositions = []
    for index in range(composition_count):
        compositions.append({
            'index': index,
            'module_index': u8(blob, pos),
            'frame_index': u8(blob, pos + 1),
            'x': u16le(blob, pos + 2),
            'y': u16le(blob, pos + 4),
            'flags': u8(blob, pos + 6),
        })
        pos += 7

    sequence_count = u16le(blob, pos)
    pos += 2
    sequences = []
    for index in range(sequence_count):
        sequences.append({
            'index': index,
            'composition_index': u8(blob, pos),
            'unk0': u16le(blob, pos + 1),
        })
        pos += 3

    palette_format = u16le(blob, pos)
    pos += 2
    palette_bank_count = u8(blob, pos)
    pos += 1
    palette_size = u8(blob, pos)
    pos += 1
    if palette_size == 0:
        palette_size = 256

    palettes: list[list[int]] = []
    for _ in range(palette_bank_count):
        palette: list[int] = []
        if palette_format == 0x8888:
            for _ in range(palette_size):
                palette.append(argb8888_to_rgba(u32le(blob, pos)))
                pos += 4
        elif palette_format == 0x4444:
            for _ in range(palette_size):
                palette.append(argb4444_to_rgba(u16le(blob, pos)))
                pos += 2
        elif palette_format == 0x6505:
            for _ in range(palette_size):
                word = u16le(blob, pos)
                pos += 2
                palette.append(0 if word == 0xF81F else rgb565_to_rgba(word))
        else:
            break
        palettes.append(palette)

    power_hint = u16le(blob, pos)
    pos += 2
    sprite_stream_offsets = []
    running = 0
    stream_sizes = []
    for _ in range(region_count):
        size = u16le(blob, pos)
        pos += 2
        sprite_stream_offsets.append(running)
        stream_sizes.append(size)
        running += size
    sprite_payload = blob[pos:pos + running]
    sprite_streams = []
    for index, start in enumerate(sprite_stream_offsets):
        sprite_streams.append({
            'index': index,
            'offset': start,
            'size': stream_sizes[index],
            'data_preview_hex': sprite_payload[start:start + min(16, stream_sizes[index])].hex(),
        })

    return {
        'flags': f'0x{flags:08x}',
        'region_count': region_count,
        'module_count': module_count,
        'frame_table_count': len(frame_tables),
        'frame_count': frame_count,
        'composition_count': composition_count,
        'sequence_count': sequence_count,
        'palette_format': f'0x{palette_format:04x}',
        'palette_count': len(palettes),
        'palette_size': palette_size,
        'power_hint': power_hint,
        'atlas_extent': {'width': atlas_width, 'height': atlas_height},
        'sprite_regions': sprite_regions,
        'modules': modules,
        'frame_tables': frame_tables,
        'frames': frames,
        'compositions': compositions,
        'sequences': sequences,
        'sprite_streams': sprite_streams,
        'palettes': palettes,
    }


def render_region_map(sprite_regions: list[dict[str, Any]], width: int, height: int) -> list[int]:
    canvas = [0] * (max(1, width) * max(1, height))
    if width <= 0 or height <= 0:
        return [0xFF000000]
    for region in sprite_regions:
        if region['kind'] != 0:
            continue
        color = pseudo_color(region['index'] + 1)
        x0 = max(0, min(width, region['x']))
        y0 = max(0, min(height, region['y']))
        x1 = max(x0, min(width, region['x'] + region['width']))
        y1 = max(y0, min(height, region['y'] + region['height']))
        for y in range(y0, y1):
            row = y * width
            for x in range(x0, x1):
                border = x == x0 or x == x1 - 1 or y == y0 or y == y1 - 1
                canvas[row + x] = 0xFF000000 if border else color
    return canvas


def guess_atlas_decodes(pack_name: str, container: Container, meta: dict[str, Any], images_dir: Path) -> list[dict[str, Any]]:
    atlas_width = meta['atlas_extent']['width'] or 256
    atlas_height = meta['atlas_extent']['height'] or 256
    palettes = meta['palettes']
    palette0 = palettes[0] if palettes else [pseudo_color(i) for i in range(256)]
    reports = []
    for idx, chunk in enumerate(container.payloads[1:], start=1):
        chunk_dir = images_dir / pack_name
        ensure_dir(chunk_dir)
        report: dict[str, Any] = {'chunk_index': idx, 'size': len(chunk), 'outputs': []}
        if atlas_width * atlas_height and len(chunk) >= atlas_width * atlas_height:
            rgba = render_indexed(list(chunk[:atlas_width * atlas_height]), atlas_width, atlas_height, palette0, transparent_index=0)
            out_path = chunk_dir / f'chunk_{idx:02d}_atlas8.png'
            write_rgba_png(out_path, atlas_width, atlas_height, rgba)
            report['outputs'].append(str(out_path))
        if atlas_width * atlas_height and len(chunk) * 2 >= atlas_width * atlas_height:
            rgba = render_indexed(unpack_nibbles(chunk)[:atlas_width * atlas_height], atlas_width, atlas_height, palette0, transparent_index=0)
            out_path = chunk_dir / f'chunk_{idx:02d}_atlas4.png'
            write_rgba_png(out_path, atlas_width, atlas_height, rgba)
            report['outputs'].append(str(out_path))
        words = len(chunk) // 2
        if words:
            width, height = factor_grid(words)
            rgba = [rgb565_to_rgba(u16le(chunk, off)) for off in range(0, width * height * 2, 2) if off + 1 < len(chunk)]
            rgba.extend([0] * (width * height - len(rgba)))
            out_path = chunk_dir / f'chunk_{idx:02d}_rgb565.png'
            write_rgba_png(out_path, width, height, rgba)
            report['outputs'].append(str(out_path))
        if not report['outputs']:
            width = 256
            height = max(1, math.ceil(len(chunk) / width))
            pixels = list(chunk) + [0] * (width * height - len(chunk))
            rgba = [0xFF000000 | (value << 16) | (value << 8) | value for value in pixels]
            out_path = chunk_dir / f'chunk_{idx:02d}_gray.png'
            write_rgba_png(out_path, width, height, rgba)
            report['outputs'].append(str(out_path))
        reports.append(report)
    return reports


def decode_graphics(jar_path: Path, output_root: Path) -> dict[str, Any]:
    resources = open_jar_resources(jar_path)
    images_dir = output_root / 'images'
    sprites_dir = output_root / 'sprites'
    tiles_dir = output_root / 'tiles'
    ensure_dir(images_dir)
    ensure_dir(sprites_dir)
    ensure_dir(tiles_dir)
    summary: dict[str, Any] = {'packs': {}}

    for pack_name in GRAPHICS_PACKS:
        if pack_name not in resources:
            continue
        container = Container(pack_name, resources[pack_name])
        meta = parse_sprite_bank_metadata(container.payloads[0])
        pack_sprite_dir = sprites_dir / pack_name
        ensure_dir(pack_sprite_dir)
        pack_tile_dir = tiles_dir / pack_name
        ensure_dir(pack_tile_dir)

        atlas_width = max(1, meta['atlas_extent']['width'])
        atlas_height = max(1, meta['atlas_extent']['height'])
        region_map = render_region_map(meta['sprite_regions'], atlas_width, atlas_height)
        region_map_path = pack_sprite_dir / 'region_map.png'
        write_rgba_png(region_map_path, atlas_width, atlas_height, region_map)

        solid_regions = [r for r in meta['sprite_regions'] if r['kind'] in (254, 255) and r['width'] and r['height']]
        for region in solid_regions[:64]:
            color = int(region['color_argb'], 16)
            sprite_path = pack_sprite_dir / f"solid_{region['index']:03d}.png"
            write_rgba_png(sprite_path, region['width'], region['height'], [color] * (region['width'] * region['height']))

        for pal_index, palette in enumerate(meta['palettes'][:8]):
            width, height, rgba = make_palette_preview(palette)
            palette_path = pack_tile_dir / f'palette_{pal_index:02d}.png'
            write_rgba_png(palette_path, width, height, rgba)

        candidate_decodes = guess_atlas_decodes(pack_name, container, meta, images_dir)
        pack_summary = {
            'container': container.as_dict(),
            'metadata': {k: v for k, v in meta.items() if k != 'palettes'},
            'palette_paths': [str((pack_tile_dir / f'palette_{pal_index:02d}.png')) for pal_index in range(min(len(meta['palettes']), 8))],
            'region_map': str(region_map_path),
            'candidate_images': candidate_decodes,
            'notes': [
                'chunk0 matches the structure parsed from a.class::a(byte[], int)',
                'sprite_regions describe atlas rectangles and solid-color fill regions',
                'frame_tables / frames / compositions preserve the engine-level composition data for later refinement',
            ],
        }
        write_json(pack_sprite_dir / 'metadata.json', pack_summary)
        summary['packs'][pack_name] = pack_summary

    write_json(output_root / 'graphics_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode graphics packs (m3_0, m4_0, m7, m11_0, m11_1)')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out/extracted'))
    args = parser.parse_args()
    decode_graphics(args.jar, args.output)


if __name__ == '__main__':
    main()
