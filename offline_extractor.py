#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import struct
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

RESOURCE_ORDER = [
    't0', 'm0', 'm1', 'm2', 'm3_0', 'm4_0', 'm5_0', 'm5_1', 'm5_2', 'm5_3', 'm5_4',
    'm5_5', 'm5_6', 'm5_7', 'm5_8', 'm5_9', 'm6_0', 'm6_1', 'm6_2', 'm6_3', 'm6_4',
    'm6_5', 'm7', 'm8', 'm9', 'm10', 'm11_0', 'm11_1', 'm12', 'm13_1', 'm13_2',
]
COMMON_WIDTHS = [16, 20, 24, 25, 30, 32, 40, 48, 50, 60, 64, 72, 75, 80, 90, 96, 100, 120, 128]


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


def rgb565_to_rgba(word: int) -> int:
    r = ((word >> 11) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x3F) * 255 // 63
    b = (word & 0x1F) * 255 // 31
    return 0xFF000000 | (r << 16) | (g << 8) | b


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


def sanitize_text(text: str) -> str:
    return ''.join(ch if ch >= ' ' or ch in '\n\t' else ' ' for ch in text).replace('\x00', ' ')


def decode_game_text(blob: bytes) -> str:
    """Game strings are usually UTF-8 bytes containing mojibaked cp1251 text."""
    try:
        utf8 = blob.decode('utf-8')
        return utf8.encode('latin1', errors='replace').decode('cp1251', errors='replace')
    except UnicodeDecodeError:
        return blob.decode('cp1251', errors='replace')


@dataclass
class ChunkInfo:
    index: int
    start: int
    end: int
    size: int
    crc32: str
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
            self.header_size = 4 + count_u32 * 4
            self.offsets = offsets_u32
        else:
            self.chunk_count = data[0]
            self.header_mode = 'u8-count'
            self.header_size = 1 + self.chunk_count * 4
            self.offsets = [u32le(data, 1 + i * 4) for i in range(self.chunk_count)]

        self.payloads: list[bytes] = []
        self.ranges: list[tuple[int, int]] = []
        for i, start in enumerate(self.offsets):
            actual_start = max(start, self.header_size if i == 0 else start)
            end = self.offsets[i + 1] if i + 1 < self.chunk_count else len(self.data)
            self.ranges.append((actual_start, end))
            self.payloads.append(self.data[actual_start:end])


class Extractor:
    def __init__(self, jar_path: Path, output_dir: Path):
        self.jar_path = jar_path
        self.output_dir = output_dir
        self.containers: dict[str, Container] = {}
        self.text_chunks: dict[int, str] = {}

    def load(self) -> None:
        with zipfile.ZipFile(self.jar_path) as zf:
            for name in RESOURCE_ORDER:
                if name in zf.namelist():
                    self.containers[name] = Container(name, zf.read(name))

    def classify_chunk(self, name: str, index: int, chunk: bytes) -> tuple[str, list[str]]:
        notes: list[str] = []
        if name == 't0':
            return 'string_table', notes
        if name.startswith('m13_'):
            if b'MThd' in chunk:
                return 'midi', ['contains MThd header']
            return 'audio_blob', notes
        if name.startswith('m6_') and index % 2 == 0 and len(chunk) >= 16:
            return 'tile_or_collision_grid', notes
        if name.startswith('m6_'):
            return 'map_sidecar', notes
        if name in {'m8', 'm9', 'm10'}:
            return 'script_or_level_pack', notes
        if name in {'m3_0', 'm4_0', 'm11_0', 'm11_1'}:
            return 'graphics_research_blob', notes
        return 'binary', notes

    def export_chunks(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for name, container in self.containers.items():
            container_dir = self.output_dir / 'chunks' / name
            ensure_dir(container_dir)
            infos: list[ChunkInfo] = []
            for index, chunk in enumerate(container.payloads):
                kind, notes = self.classify_chunk(name, index, chunk)
                raw_path = container_dir / f'{index:02d}.bin'
                raw_path.write_bytes(chunk)
                start, end = container.ranges[index]
                infos.append(ChunkInfo(
                    index=index,
                    start=start,
                    end=end,
                    size=len(chunk),
                    crc32=f'{zlib.crc32(chunk) & 0xFFFFFFFF:08x}',
                    kind=kind,
                    notes=notes,
                ))
            summary[name] = {
                'header_mode': container.header_mode,
                'header_size': container.header_size,
                'chunk_count': container.chunk_count,
                'offsets': container.offsets,
                'chunks': [asdict(info) for info in infos],
            }
        return summary

    def guess_offset_table(self, chunk: bytes) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        limit = min(len(chunk), 512)
        for start in range(limit):
            if start + 8 > len(chunk):
                break
            offsets: list[int] = []
            pos = start
            while pos + 4 <= len(chunk):
                value = u32le(chunk, pos)
                if value >= len(chunk):
                    break
                if offsets and value < offsets[-1]:
                    break
                offsets.append(value)
                pos += 4
                remaining = len(chunk) - pos
                if offsets and offsets[-1] <= remaining:
                    candidate = {
                        'start': start,
                        'count': len(offsets),
                        'blob_start': pos,
                        'max_offset': offsets[-1],
                    }
                    if best is None or (candidate['count'], candidate['max_offset']) > (best['count'], best['max_offset']):
                        best = candidate
        return best if best and best['count'] >= 8 else None

    def export_strings(self) -> dict[str, Any]:
        container = self.containers.get('t0')
        if not container:
            return {}
        text_dir = self.output_dir / 'extracted' / 'text'
        ensure_dir(text_dir)
        summary: dict[str, Any] = {'chunks': []}
        for idx, chunk in enumerate(container.payloads):
            decoded = sanitize_text(decode_game_text(chunk))
            self.text_chunks[idx] = decoded
            full_path = text_dir / f't0_{idx:02d}_full.txt'
            full_path.write_text(decoded, encoding='utf-8')
            entry: dict[str, Any] = {
                'chunk_index': idx,
                'path': str(full_path.relative_to(self.output_dir)),
                'char_length': len(decoded),
            }
            table_guess = self.guess_offset_table(chunk)
            if table_guess:
                start = table_guess['start']
                count = table_guess['count']
                blob_start = table_guess['blob_start']
                offsets = [u32le(chunk, start + i * 4) for i in range(count)]
                combined = chunk[:start] + chunk[blob_start:]
                last = 0
                strings: list[str] = []
                for end in offsets:
                    if 0 <= last <= end <= len(combined):
                        strings.append(sanitize_text(decode_game_text(combined[last:end])))
                    last = end
                if last < len(combined):
                    strings.append(sanitize_text(decode_game_text(combined[last:])))
                clean_strings = [s for s in strings if s.strip()]
                guess_path = text_dir / f't0_{idx:02d}_segments_guess.json'
                write_json(guess_path, {
                    'chunk_index': idx,
                    'offset_table_guess': table_guess,
                    'strings': clean_strings,
                })
                reconstructed_path = text_dir / f't0_{idx:02d}_reconstructed.txt'
                reconstructed_path.write_text('\n'.join(clean_strings) + '\n', encoding='utf-8')
                entry['segment_guess_path'] = str(guess_path.relative_to(self.output_dir))
                entry['reconstructed_path'] = str(reconstructed_path.relative_to(self.output_dir))
                entry['segment_guess_count'] = len(clean_strings)
            summary['chunks'].append(entry)
        return summary

    def analyse_audio_blob(self, chunk: bytes) -> dict[str, Any]:
        return {
            'size': len(chunk),
            'head_hex': chunk[:32].hex(),
            'nonzero_bytes': sum(1 for b in chunk if b),
            'top_bytes': Counter(chunk).most_common(8),
        }

    def export_audio(self) -> dict[str, Any]:
        out = {'midi': [], 'raw_audio': []}
        audio_dir = self.output_dir / 'extracted' / 'audio'
        for name in ('m13_1', 'm13_2'):
            container = self.containers.get(name)
            if not container:
                continue
            pack_dir = audio_dir / name
            ensure_dir(pack_dir)
            for idx, chunk in enumerate(container.payloads):
                if not chunk:
                    continue
                if b'MThd' in chunk:
                    pos = chunk.index(b'MThd')
                    path = pack_dir / f'{idx:02d}.mid'
                    path.write_bytes(chunk[pos:])
                    out['midi'].append(str(path.relative_to(self.output_dir)))
                else:
                    path = pack_dir / f'{idx:02d}.bin'
                    path.write_bytes(chunk)
                    meta_path = pack_dir / f'{idx:02d}.json'
                    write_json(meta_path, self.analyse_audio_blob(chunk))
                    out['raw_audio'].append({
                        'path': str(path.relative_to(self.output_dir)),
                        'meta': str(meta_path.relative_to(self.output_dir)),
                    })
        return out

    def parse_script_stream(self, chunk: bytes) -> dict[str, Any]:
        cursor = 0
        commands = []
        opcode_hist = Counter()
        ref_candidates = []
        while cursor < len(chunk):
            opcode = chunk[cursor]
            opcode_hist[opcode] += 1
            start = cursor
            cursor += 1
            if opcode in {101, 102} and cursor + 7 <= len(chunk):
                size = chunk[cursor]
                cursor += 1
                payload = chunk[cursor:cursor + size * 2 + 6]
                ref_candidates.append({'offset': start, 'opcode': opcode, 'payload_preview': list(payload[:16])})
                cursor += len(payload)
                continue
            if opcode == 99 and cursor + 5 <= len(chunk):
                ref_candidates.append({
                    'offset': start,
                    'opcode': opcode,
                    'm8_pack_index': chunk[cursor],
                    'm8_subchunk_index': chunk[cursor + 1],
                    'raw_tail': list(chunk[cursor + 2:cursor + 5]),
                })
                commands.append(ref_candidates[-1])
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
                'params_preview': params[:12],
            })
        return {
            'command_count': len(commands),
            'opcode_histogram': dict(sorted(opcode_hist.items())),
            'commands_preview': commands[:96],
            'm8_reference_candidates': ref_candidates,
        }

    def export_script_and_level_packs(self) -> dict[str, Any]:
        docs_dir = self.output_dir / 'docs' / 'reverse_engineering'
        ensure_dir(docs_dir)
        summary: dict[str, Any] = {}

        m8 = self.containers.get('m8')
        if m8:
            chunks = []
            for idx, chunk in enumerate(m8.payloads):
                parsed = self.parse_script_stream(chunk)
                path = docs_dir / f'm8_chunk_{idx:02d}.json'
                write_json(path, parsed)
                chunks.append({'chunk_index': idx, 'size': len(chunk), 'path': str(path.relative_to(self.output_dir)), 'opcode_histogram': parsed['opcode_histogram']})
            summary['m8'] = {'chunk_count': len(chunks), 'chunks': chunks}

        m9 = self.containers.get('m9')
        if m9:
            script_chunks = []
            table_chunks = []
            for idx, chunk in enumerate(m9.payloads):
                record = {'chunk_index': idx, 'size': len(chunk)}
                if idx >= 10:
                    parsed = self.parse_script_stream(chunk)
                    path = docs_dir / f'm9_script_{idx:02d}.json'
                    write_json(path, parsed)
                    record.update({'role': 'script_pack', 'path': str(path.relative_to(self.output_dir)), 'opcode_histogram': parsed['opcode_histogram']})
                    script_chunks.append(record)
                else:
                    record['role'] = 'table_or_lookup'
                    record['u16_preview'] = [u16le(chunk, i) for i in range(0, min(len(chunk), 32), 2)]
                    table_chunks.append(record)
            summary['m9'] = {'tables': table_chunks, 'script_packs': script_chunks}

        m10 = self.containers.get('m10')
        if m10:
            chapter_chunks = []
            for idx, chunk in enumerate(m10.payloads):
                u16_values = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
                path = docs_dir / f'm10_chunk_{idx:02d}.json'
                write_json(path, {
                    'chunk_index': idx,
                    'size': len(chunk),
                    'u16_count': len(u16_values),
                    'u16_preview': u16_values[:128],
                    'nonzero_values': sum(1 for value in u16_values if value),
                    'max_u16': max(u16_values) if u16_values else 0,
                })
                chapter_chunks.append({'chunk_index': idx, 'size': len(chunk), 'path': str(path.relative_to(self.output_dir))})
            summary['m10'] = {'chapter_chunks': chapter_chunks}
        return summary

    def export_tile_maps(self) -> dict[str, Any]:
        maps_dir = self.output_dir / 'extracted' / 'maps'
        ensure_dir(maps_dir)
        report: dict[str, Any] = {}
        for name in [f'm6_{index}' for index in range(6) if f'm6_{index}' in self.containers]:
            container = self.containers[name]
            entries = []
            for idx, chunk in enumerate(container.payloads):
                if idx % 2 == 1:
                    continue
                values = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
                width, height = factor_grid(len(values))
                png_path = maps_dir / name / f'{idx:02d}.png'
                write_rgba_png(png_path, width, height, [pseudo_color(value) for value in values] + [0x00000000] * (width * height - len(values)))
                rgb565_path = maps_dir / name / f'{idx:02d}_rgb565.png'
                write_rgba_png(rgb565_path, width, height, [rgb565_to_rgba(value) for value in values] + [0x00000000] * (width * height - len(values)))
                meta = {
                    'container': name,
                    'chunk_index': idx,
                    'cells': len(values),
                    'width_guess': width,
                    'height_guess': height,
                    'tile_range': [min(values) if values else 0, max(values) if values else 0],
                    'nonzero_cells': sum(1 for value in values if value),
                    'sidecar_hex': container.payloads[idx + 1].hex() if idx + 1 < len(container.payloads) else None,
                    'tile_preview': values[:128],
                    'preview_png': str(png_path.relative_to(self.output_dir)),
                    'preview_rgb565_png': str(rgb565_path.relative_to(self.output_dir)),
                }
                write_json(maps_dir / name / f'{idx:02d}.json', meta)
                entries.append(meta)
            report[name] = {
                'map_count': len(entries),
                'maps': entries,
            }
        return report

    def export_graphics_research(self) -> dict[str, Any]:
        images_dir = self.output_dir / 'extracted' / 'images'
        ensure_dir(images_dir)
        report = {'containers': {}}
        for name in ('m3_0', 'm4_0', 'm11_0', 'm11_1'):
            container = self.containers.get(name)
            if not container:
                continue
            chunks = []
            for idx, chunk in enumerate(container.payloads):
                width = 256
                height = max(1, math.ceil(len(chunk) / width))
                padded = list(chunk) + [0] * (width * height - len(chunk))
                gray_rgba = [0xFF000000 | (b << 16) | (b << 8) | b for b in padded]
                gray_path = images_dir / 'research' / f'{name}_{idx:02d}_gray.png'
                write_rgba_png(gray_path, width, height, gray_rgba)
                rgb565_path = None
                if len(chunk) >= 2:
                    words = [u16le(chunk, pos) for pos in range(0, len(chunk) - (len(chunk) % 2), 2)]
                    gw, gh = factor_grid(len(words))
                    rgb565_rgba = [rgb565_to_rgba(word) for word in words] + [0x00000000] * (gw * gh - len(words))
                    rgb565_path = images_dir / 'research' / f'{name}_{idx:02d}_rgb565.png'
                    write_rgba_png(rgb565_path, gw, gh, rgb565_rgba)
                chunks.append({
                    'chunk_index': idx,
                    'size': len(chunk),
                    'grayscale_preview': str(gray_path.relative_to(self.output_dir)),
                    'rgb565_preview': str(rgb565_path.relative_to(self.output_dir)) if rgb565_path else None,
                })
            report['containers'][name] = {
                'chunk_count': len(container.payloads),
                'chunks': chunks,
                'observations': [
                    'All four packs behave like atlas/palette support blobs rather than self-describing images.',
                    'Grayscale and RGB565 previews are exploratory only and should be treated as reverse-engineering aids.',
                ],
            }
        write_json(images_dir / 'graphics_research.json', report)
        return report

    def build_final_table(self, maps: dict[str, Any], scripts: dict[str, Any], audio: dict[str, Any]) -> list[dict[str, Any]]:
        map_counts = {name: info.get('map_count', 0) for name, info in maps.items()}
        inferred_rows = [
            {
                'chapter': 0,
                'mission': 'GLT телестанция / вводный инцидент',
                'script pack': 'm9#10',
                'map pack': f"m6_0 ({map_counts.get('m6_0', 0)} карт)",
                'graphics pack': 'shared m3_0 + m4_0 + m11_0 + m11_1',
                'audio cues': 'm13_1#00 intro MIDI; m13_2 assorted cues',
                'major enemies': 'зомби, полицейские-зомби',
                'key story events': 'ТВ-группа прибывает на массовое убийство и фиксирует начало вспышки.',
            },
            {
                'chapter': 1,
                'mission': 'Центр / бар Джо / улицы',
                'script pack': 'm9#11',
                'map pack': f"m6_1 ({map_counts.get('m6_1', 0)} карт)",
                'graphics pack': 'shared atlases + chapter sidecars from m8#1',
                'audio cues': 'm13_2 MIDI/SFX bank',
                'major enemies': 'зомби, заражённые собаки',
                'key story events': 'Игрок продвигается через центр и связанные интерьеры, собирая первые ключи и цели.',
            },
            {
                'chapter': 2,
                'mission': 'Озеро / лес / Манхэттенская окраина',
                'script pack': 'm9#12',
                'map pack': f"m6_2 ({map_counts.get('m6_2', 0)} карт)",
                'graphics pack': 'shared atlases + chapter sidecars from m8#2',
                'audio cues': 'm13_2 MIDI/SFX bank',
                'major enemies': 'зомби, военные противники, мутанты',
                'key story events': 'Маршрут уводит из городского центра к лесу и лагерю борцов за свободу.',
            },
            {
                'chapter': 3,
                'mission': 'Лаборатория Ротванга / кладбище',
                'script pack': 'm9#13',
                'map pack': f"m6_3 ({map_counts.get('m6_3', 0)} карт)",
                'graphics pack': 'shared atlases + chapter sidecars from m8#3',
                'audio cues': 'm13_2 MIDI/SFX bank',
                'major enemies': 'зомби, лабораторные мутанты, мини-боссы',
                'key story events': 'По текстам t0 в этом блоке фигурируют ключи Ротванга, отключение питания и проход через кладбище.',
            },
            {
                'chapter': 4,
                'mission': 'Пожарная станция / зоопарк / городские узлы',
                'script pack': 'm9#14',
                'map pack': f"m6_4 ({map_counts.get('m6_4', 0)} карт)",
                'graphics pack': 'shared atlases + chapter sidecars from m8#4',
                'audio cues': 'm13_2 MIDI/SFX bank',
                'major enemies': 'зомби, животные-мутанты, тяжёлые противники',
                'key story events': 'Судя по строкам локаций, игра переходит к более экзотическим площадкам и усиливает давление на игрока.',
            },
            {
                'chapter': 5,
                'mission': 'Секретный этаж / финальная развязка',
                'script pack': 'm9#15',
                'map pack': f"m6_5 ({map_counts.get('m6_5', 0)} карт)",
                'graphics pack': 'shared atlases + chapter sidecars from m8#5',
                'audio cues': 'late m13_2 cues + finale MIDI',
                'major enemies': 'элитные мутанты, босс Ротванга',
                'key story events': 'Финальный набор строк указывает на секретный этаж, кульминацию заговора и boss/finale сцены.',
            },
        ]
        md_path = self.output_dir / 'docs' / 'reverse_engineering' / 'final_asset_table.md'
        ensure_dir(md_path.parent)
        headers = ['chapter', 'mission', 'script pack', 'map pack', 'graphics pack', 'audio cues', 'major enemies', 'key story events']
        lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
        for row in inferred_rows:
            lines.append('| ' + ' | '.join(str(row[h]) for h in headers) + ' |')
        md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        write_json(self.output_dir / 'docs' / 'reverse_engineering' / 'final_asset_table.json', inferred_rows)
        return inferred_rows

    def write_research_notes(self, chunks: dict[str, Any], strings: dict[str, Any], audio: dict[str, Any], maps: dict[str, Any], graphics: dict[str, Any], scripts: dict[str, Any], final_table: list[dict[str, Any]]) -> None:
        notes = self.output_dir / 'docs' / 'reverse_engineering' / 'pack_notes.md'
        map_counts = ', '.join(f'{name}: {info["map_count"]}' for name, info in maps.items())
        text_note = 'центр, восток; на телестанцию GLT; плаза; бар Джо; офисы; крыша; переулок; озеро; лес; лаборатория Ротванга; кладбище'
        body = f'''# Reverse-engineering notes

## Implemented in iteration 1

- Generic parser for `m*` / `t0` containers with header trimming for payload 0.
- `t0` text extraction into `extracted/text/` with corrected cp1251 decoding and guessed offset-table JSON sidecars.
- `m13_1` / `m13_2` audio extraction into `extracted/audio/`, preserving MIDI payloads and documenting unknown cue blobs.
- Research previews for `m3_0`, `m4_0`, `m11_0`, `m11_1` in `extracted/images/research/` using grayscale and RGB565 guesses.
- First-pass parsers for `m8`, `m9`, `m10` written to `docs/reverse_engineering/`.
- Tile/collision pack summaries for `m6_0..m6_5` written to `extracted/maps/`.

## Current findings

- `m6_*` behaves like six chapter-local map packs. Even-numbered payloads are large u16 grids; odd-numbered payloads are 2-byte sidecars/flags.
- `m9` contains six large script packs in payloads `10..15`, plus smaller table/lookup payloads before them.
- `m10` exposes six chapter-scale metadata blobs, which is consistent with the six `m6_*` map packs.
- `m13_1` contains the intro BGM MIDI, while `m13_2` mixes multiple MIDI cues with many non-MIDI effect blobs.
- Graphics packs remain exploratory: the current previews are good for spotting tiling/palette structure, but not yet for shipping-grade sprite export.

## Useful extracted evidence

- Location-string sample from `t0`: `{text_note}`
- Map counts by chapter pack: {map_counts}
- MIDI cues recovered: {len(audio['midi'])}
- Raw audio blobs documented: {len(audio['raw_audio'])}
- Final table rows: {len(final_table)}
'''
        notes.write_text(body, encoding='utf-8')

    def run(self) -> None:
        self.load()
        ensure_dir(self.output_dir)
        chunks = self.export_chunks()
        strings = self.export_strings()
        audio = self.export_audio()
        scripts = self.export_script_and_level_packs()
        maps = self.export_tile_maps()
        graphics = self.export_graphics_research()
        final_table = self.build_final_table(maps, scripts, audio)
        self.write_research_notes(chunks, strings, audio, maps, graphics, scripts, final_table)
        write_json(self.output_dir / 'summary.json', {
            'jar': str(self.jar_path),
            'containers': chunks,
            'strings': strings,
            'audio': audio,
            'scripts': scripts,
            'maps': maps,
            'graphics': graphics,
            'final_table_rows': len(final_table),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline extractor for 240x320-rus-zombie-infection.jar')
    parser.add_argument('jar', type=Path, help='Path to JAR file')
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'), help='Output directory (defaults to a gitignored path)')
    args = parser.parse_args()
    Extractor(args.jar, args.output).run()


if __name__ == '__main__':
    main()
