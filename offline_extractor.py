#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import struct
import zipfile
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

RESOURCE_ORDER = [
    't0', 'm0', 'm1', 'm2', 'm3_0', 'm4_0', 'm5_0', 'm5_1', 'm5_2', 'm5_3', 'm5_4',
    'm5_5', 'm5_6', 'm5_7', 'm5_8', 'm5_9', 'm6_0', 'm6_1', 'm6_2', 'm6_3', 'm6_4',
    'm6_5', 'm7', 'm8', 'm9', 'm10', 'm11_0', 'm11_1', 'm12', 'm13_1', 'm13_2',
]


def u16le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def u32le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16) | (data[offset + 3] << 24)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF)


def write_rgba_png(path: Path, width: int, height: int, rgba: list[int]) -> None:
    ensure_dir(path.parent)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = rgba[y * width:(y + 1) * width]
        for px in row:
            raw.extend(((px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF, (px >> 24) & 0xFF))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    data = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + png_chunk(b'IEND', b'')
    path.write_bytes(data)


def pseudo_color(value: int) -> int:
    value &= 0xFFFF
    r = (value * 53) & 0xFF
    g = (value * 97) & 0xFF
    b = (value * 193) & 0xFF
    return 0xFF000000 | (r << 16) | (g << 8) | b


def factor_grid(cells: int) -> tuple[int, int]:
    if cells <= 0:
        return 1, 1
    best = (cells, 1)
    best_score = 10**18
    for w in range(1, int(math.sqrt(cells)) + 1):
        if cells % w:
            continue
        h = cells // w
        score = abs(h - w)
        if score < best_score:
            best = (w, h)
            best_score = score
    return best[1], best[0]


@dataclass
class ChunkInfo:
    index: int
    start: int
    end: int
    size: int
    sha1_prefix: str
    kind: str
    notes: list[str]


class Container:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data

        count_u32 = u32le(data, 0) if len(data) >= 4 else 0
        plausible_u32 = count_u32 > 0 and 4 + count_u32 * 4 <= len(data)
        if plausible_u32:
            offsets_u32 = [u32le(data, 4 + i * 4) for i in range(count_u32)]
            plausible_u32 = offsets_u32 == sorted(offsets_u32) and all(0 <= off <= len(data) for off in offsets_u32)
        if plausible_u32:
            self.chunk_count = count_u32
            self.header_mode = 'u32-count'
            self.offsets = offsets_u32
        else:
            self.chunk_count = data[0]
            self.header_mode = 'u8-count'
            self.offsets = [u32le(data, 1 + i * 4) for i in range(self.chunk_count)]

        self.chunks = []
        for i, start in enumerate(self.offsets):
            end = self.offsets[i + 1] if i + 1 < self.chunk_count else len(self.data)
            self.chunks.append(self.data[start:end])


class Extractor:
    def __init__(self, jar_path: Path, output_dir: Path):
        self.jar_path = jar_path
        self.output_dir = output_dir
        self.containers: dict[str, Container] = {}
        self.chapter_rows: list[dict[str, Any]] = []

    def load(self) -> None:
        with zipfile.ZipFile(self.jar_path) as zf:
            for name in RESOURCE_ORDER:
                if name in zf.namelist():
                    self.containers[name] = Container(name, zf.read(name))

    def classify_chunk(self, name: str, index: int, chunk: bytes) -> tuple[str, list[str]]:
        notes: list[str] = []
        kind = 'binary'
        if name == 't0':
            kind = 'string_table'
        elif name.startswith('m13_'):
            if b'MThd' in chunk:
                kind = 'midi'
                notes.append('contains MThd header')
            elif chunk.startswith(b'RIFF') and b'WAVE' in chunk[:16]:
                kind = 'wav'
            else:
                kind = 'audio_or_blob'
        elif name.startswith('m6_') and len(chunk) > 8 and len(chunk) % 2 == 0:
            kind = 'tile_or_layer'
        elif name == 'm9':
            kind = 'script_or_table'
        elif name == 'm8':
            kind = 'map_script_or_region_table'
        elif name in {'m3_0', 'm4_0', 'm11_0', 'm11_1', 'm7'}:
            kind = 'graphics_or_palette_blob'
        if index == 0:
            notes.append('chunk 0 includes container header/table in this format')
        return kind, notes

    def export_chunks(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for name, container in self.containers.items():
            container_dir = self.output_dir / 'chunks' / name
            ensure_dir(container_dir)
            infos: list[ChunkInfo] = []
            for index, chunk in enumerate(container.chunks):
                kind, notes = self.classify_chunk(name, index, chunk)
                raw_path = container_dir / f'{index:02d}.bin'
                raw_path.write_bytes(chunk)
                infos.append(ChunkInfo(
                    index=index,
                    start=container.offsets[index],
                    end=container.offsets[index] + len(chunk),
                    size=len(chunk),
                    sha1_prefix=zlib.crc32(chunk).to_bytes(4, 'big').hex(),
                    kind=kind,
                    notes=notes,
                ))
                if kind == 'tile_or_layer':
                    self.export_tile_preview(name, index, chunk)
            summary[name] = {
                'chunk_count': container.chunk_count,
                'offsets': container.offsets,
                'chunks': [asdict(info) for info in infos],
            }
        return summary

    def export_tile_preview(self, name: str, index: int, chunk: bytes) -> None:
        cells = len(chunk) // 2
        width, height = factor_grid(cells)
        rgba = []
        for i in range(cells):
            value = u16le(chunk, i * 2)
            rgba.append(pseudo_color(value))
        base = self.output_dir / 'maps' / name
        ensure_dir(base)
        write_rgba_png(base / f'{index:02d}.png', width, height, rgba)
        write_json(base / f'{index:02d}.json', {
            'container': name,
            'chunk_index': index,
            'cells': cells,
            'width_guess': width,
            'height_guess': height,
            'tile_values_preview': [u16le(chunk, i * 2) for i in range(min(cells, 64))],
        })

    def export_strings(self) -> dict[str, Any]:
        container = self.containers.get('t0')
        if not container:
            return {}
        strings_dir = self.output_dir / 'strings'
        ensure_dir(strings_dir)
        payload: dict[str, Any] = {'chunks': []}
        for idx, chunk in enumerate(container.chunks[1:], 1):
            decoded = chunk.decode('utf-8', errors='replace').replace('\\n', '\n')
            path = strings_dir / f'{idx:02d}.txt'
            path.write_text(decoded, encoding='utf-8')
            payload['chunks'].append({'chunk_index': idx, 'path': str(path.relative_to(self.output_dir)), 'length': len(decoded)})
        return payload

    def export_audio(self) -> dict[str, Any]:
        out = {'midi': [], 'wav': [], 'raw_audio': []}
        for name in ('m13_1', 'm13_2'):
            container = self.containers.get(name)
            if not container:
                continue
            for idx, chunk in enumerate(container.chunks):
                audio_dir = self.output_dir / 'audio' / name
                ensure_dir(audio_dir)
                if b'MThd' in chunk:
                    pos = chunk.index(b'MThd')
                    path = audio_dir / f'{idx:02d}.mid'
                    path.write_bytes(chunk[pos:])
                    out['midi'].append(str(path.relative_to(self.output_dir)))
                elif chunk.startswith(b'RIFF') and b'WAVE' in chunk[:16]:
                    path = audio_dir / f'{idx:02d}.wav'
                    path.write_bytes(chunk)
                    out['wav'].append(str(path.relative_to(self.output_dir)))
                elif len(chunk) > 32:
                    path = audio_dir / f'{idx:02d}.bin'
                    path.write_bytes(chunk)
                    out['raw_audio'].append(str(path.relative_to(self.output_dir)))
        return out

    def parse_script_chunk(self, chunk: bytes) -> dict[str, Any]:
        cursor = 0
        commands = []
        scene_markers = []
        m8_refs = []
        while cursor < len(chunk):
            opcode = chunk[cursor]
            start = cursor
            cursor += 1
            if opcode == 99 and cursor + 5 <= len(chunk):
                ref = {
                    'offset': start,
                    'opcode': opcode,
                    'm8_pack_index': chunk[cursor],
                    'm8_subchunk_index': chunk[cursor + 1],
                    'raw_tail': list(chunk[cursor + 2:cursor + 5]),
                }
                m8_refs.append(ref)
                commands.append(ref)
                cursor += 5
                continue
            if opcode == 200 and cursor < len(chunk):
                size = chunk[cursor]
                cursor += 1
                payload = list(chunk[cursor:cursor + size])
                scene_markers.append({'offset': start, 'size': size, 'payload_preview': payload[:16]})
                commands.append({'offset': start, 'opcode': opcode, 'payload_size': size})
                cursor += size
                continue
            if cursor + 7 > len(chunk):
                commands.append({'offset': start, 'opcode': opcode, 'truncated': True})
                break
            meta = list(chunk[cursor:cursor + 6])
            cursor += 6
            pairs = chunk[cursor]
            cursor += 1
            params = []
            for _ in range(pairs):
                if cursor + 2 > len(chunk):
                    break
                params.append(u16le(chunk, cursor))
                cursor += 2
            commands.append({'offset': start, 'opcode': opcode, 'meta': meta, 'pair_count': pairs, 'params_preview': params[:12]})
        return {'commands': commands, 'scene_markers': scene_markers, 'm8_references': m8_refs}

    def script_pack_index_for_level(self, level_index: int) -> int:
        chunk0 = self.containers['m9'].chunks[0]
        total = 0
        pos = 0
        while pos < len(chunk0) and total <= level_index:
            total += chunk0[pos]
            pos += 1
        return max(0, pos - 1)

    def export_scripts(self) -> dict[str, Any]:
        container = self.containers.get('m9')
        if not container:
            return {}
        scripts_dir = self.output_dir / 'scripts'
        ensure_dir(scripts_dir)
        summary = {'levels': [], 'chunks': {}}
        for idx, chunk in enumerate(container.chunks):
            summary['chunks'][str(idx)] = {'size': len(chunk)}
            if idx >= 10:
                parsed = self.parse_script_chunk(chunk)
                write_json(scripts_dir / f'chunk_{idx:02d}.json', parsed)
                summary['chunks'][str(idx)].update({
                    'command_count': len(parsed['commands']),
                    'm8_reference_count': len(parsed['m8_references']),
                    'path': str((scripts_dir / f'chunk_{idx:02d}.json').relative_to(self.output_dir)),
                })
        level_count = sum(self.containers['m9'].chunks[0])
        for level_index in range(level_count):
            script_pack = self.script_pack_index_for_level(level_index)
            summary['levels'].append({
                'level_index': level_index,
                'chapter': script_pack,
                'script_chunk_index': 10 + script_pack,
            })
        return summary

    def export_m8_analysis(self) -> dict[str, Any]:
        container = self.containers.get('m8')
        if not container:
            return {}
        out = {'chunks': []}
        for idx, chunk in enumerate(container.chunks):
            sections = []
            cursor = 0
            while cursor < len(chunk):
                opcode = chunk[cursor]
                start = cursor
                cursor += 1
                if opcode == 200 and cursor < len(chunk):
                    size = chunk[cursor]
                    cursor += 1 + size
                    sections.append({'offset': start, 'opcode': 200, 'size': size})
                    continue
                if cursor + 7 > len(chunk):
                    break
                cursor += 6
                pairs = chunk[cursor]
                cursor += 1 + pairs * 2
                sections.append({'offset': start, 'opcode': opcode, 'pairs': pairs})
            out['chunks'].append({'chunk_index': idx, 'size': len(chunk), 'records': sections[:64]})
        write_json(self.output_dir / 'maps' / 'm8_analysis.json', out)
        return out

    def build_chapter_matrix(self, scripts: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for level in scripts.get('levels', []):
            chapter = level['chapter']
            script_chunk_index = level['script_chunk_index']
            parsed_path = self.output_dir / 'scripts' / f'chunk_{script_chunk_index:02d}.json'
            m8_refs = []
            if parsed_path.exists():
                parsed = json.loads(parsed_path.read_text(encoding='utf-8'))
                m8_refs = parsed.get('m8_references', [])
            row = {
                'chapter': chapter,
                'level_index': level['level_index'],
                'script_pack': {'container': 'm9', 'chunk_index': script_chunk_index},
                'map_pack_candidates': sorted({f"m6_{ref['m8_pack_index']}" for ref in m8_refs if ref['m8_pack_index'] < 6}),
                'graphics_pack_candidates': sorted({ref['m8_pack_index'] for ref in m8_refs}),
                'm8_subchunks': sorted({ref['m8_subchunk_index'] for ref in m8_refs}),
                'audio_cues': [],
            }
            rows.append(row)
        write_json(self.output_dir / 'chapter_matrix.json', rows)
        return rows

    def export_graphics_research(self) -> dict[str, Any]:
        report = {'containers': {}}
        for name in ('m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1'):
            container = self.containers.get(name)
            if not container:
                continue
            report['containers'][name] = {
                'chunk_count': container.chunk_count,
                'chunk_sizes': [len(c) for c in container.chunks],
                'observations': [
                    'm3_0/m4_0 likely store atlas/runtime data used by class a/g',
                    'm11_0/m11_1 contain palette-like and graphics-like support blocks',
                    'chunk 0 retains the container table and should not be treated as a pure payload chunk',
                ],
            }
        visuals_dir = self.output_dir / 'images' / 'research'
        ensure_dir(visuals_dir)
        for name in ('m3_0', 'm4_0', 'm11_0', 'm11_1'):
            container = self.containers.get(name)
            if not container:
                continue
            for idx, chunk in enumerate(container.chunks[1:], 1):
                width = 256
                height = math.ceil(len(chunk) / width)
                rgba = [0xFF000000 | (b << 16) | (b << 8) | b for b in chunk] + [0x00000000] * (width * height - len(chunk))
                write_rgba_png(visuals_dir / f'{name}_{idx:02d}.png', width, height, rgba)
        write_json(self.output_dir / 'images' / 'graphics_research.json', report)
        return report

    def run(self) -> None:
        self.load()
        ensure_dir(self.output_dir)
        chunks = self.export_chunks()
        strings = self.export_strings()
        audio = self.export_audio()
        scripts = self.export_scripts()
        maps = self.export_m8_analysis()
        graphics = self.export_graphics_research()
        chapter_matrix = self.build_chapter_matrix(scripts)
        write_json(self.output_dir / 'summary.json', {
            'jar': str(self.jar_path),
            'containers': chunks,
            'strings': strings,
            'audio': audio,
            'scripts': scripts,
            'maps': {'m8': maps},
            'graphics': graphics,
            'chapter_matrix_size': len(chapter_matrix),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline extractor for 240x320-rus-zombie-infection.jar')
    parser.add_argument('jar', type=Path, help='Path to JAR file')
    parser.add_argument('-o', '--output', type=Path, default=Path('extractor_out'), help='Output directory')
    args = parser.parse_args()
    Extractor(args.jar, args.output).run()


if __name__ == '__main__':
    main()
