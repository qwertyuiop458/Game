from __future__ import annotations

import json
import math
import struct
import zipfile
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

RESOURCE_ORDER = [
    't0', 'm0', 'm1', 'm2', 'm3_0', 'm4_0', 'm5_0', 'm5_1', 'm5_2', 'm5_3', 'm5_4',
    'm5_5', 'm5_6', 'm5_7', 'm5_8', 'm5_9', 'm6_0', 'm6_1', 'm6_2', 'm6_3', 'm6_4',
    'm6_5', 'm7', 'm8', 'm9', 'm10', 'm11_0', 'm11_1', 'm12', 'm13_1', 'm13_2',
    'dataIGP', 'icon.png', 'a.class', 'c.class', 'g.class', 'palettesAmount.bin',
]
COMMON_WIDTHS = [16, 20, 24, 25, 30, 32, 40, 48, 50, 60, 64, 72, 75, 80, 90, 96, 100, 120, 128, 160, 176, 200, 240, 256, 320]


def u8(data: bytes, offset: int) -> int:
    return data[offset]


def u16le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def s16le(data: bytes, offset: int) -> int:
    value = u16le(data, offset)
    return value - 0x10000 if value & 0x8000 else value


def u32le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16) | (data[offset + 3] << 24)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def sanitize_name(value: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in value)


def png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF)


def write_rgba_png(path: Path, width: int, height: int, rgba: Iterable[int]) -> None:
    ensure_dir(path.parent)
    rgba_list = list(rgba)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = rgba_list[y * width:(y + 1) * width]
        for px in row:
            raw.extend(((px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF, (px >> 24) & 0xFF))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    payload = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + png_chunk(b'IEND', b'')
    path.write_bytes(payload)


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


def argb4444_to_rgba(word: int) -> int:
    a = ((word >> 12) & 0xF) * 17
    r = ((word >> 8) & 0xF) * 17
    g = ((word >> 4) & 0xF) * 17
    b = (word & 0xF) * 17
    return (a << 24) | (r << 16) | (g << 8) | b


def argb8888_to_rgba(dword: int) -> int:
    return dword & 0xFFFFFFFF


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


def decode_game_text(blob: bytes) -> str:
    try:
        utf8 = blob.decode('utf-8')
        return utf8.encode('latin1', errors='replace').decode('cp1251', errors='replace')
    except UnicodeDecodeError:
        return blob.decode('cp1251', errors='replace')


@dataclass
class ChunkInfo:
    index: int
    relative_start: int
    relative_end: int
    absolute_start: int
    absolute_end: int
    size: int
    crc32: str


class Container:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data
        self.header_mode, self.chunk_count, self.header_size, self.offsets = self._detect_header(data)
        self.payloads: list[bytes] = []
        self.ranges: list[tuple[int, int]] = []
        self.chunk_infos: list[ChunkInfo] = []
        for index, rel_start in enumerate(self.offsets):
            rel_end = self.offsets[index + 1] if index + 1 < self.chunk_count else len(data) - self.header_size
            abs_start = self.header_size + rel_start
            abs_end = self.header_size + rel_end if index + 1 < self.chunk_count else len(data)
            abs_start = max(self.header_size, min(abs_start, len(data)))
            abs_end = max(abs_start, min(abs_end, len(data)))
            chunk = data[abs_start:abs_end]
            self.ranges.append((abs_start, abs_end))
            self.payloads.append(chunk)
            self.chunk_infos.append(ChunkInfo(
                index=index,
                relative_start=rel_start,
                relative_end=rel_end,
                absolute_start=abs_start,
                absolute_end=abs_end,
                size=len(chunk),
                crc32=f'{zlib.crc32(chunk) & 0xFFFFFFFF:08x}',
            ))

    @staticmethod
    def _detect_header(data: bytes) -> tuple[str, int, int, list[int]]:
        candidates: list[tuple[int, str, int, int, list[int]]] = []
        if data:
            count8 = data[0]
            header8 = 1 + count8 * 4
            if count8 and header8 <= len(data):
                offsets8 = [u32le(data, 1 + i * 4) for i in range(count8)]
                if offsets8 == sorted(offsets8) and all(0 <= off <= len(data) - header8 for off in offsets8):
                    candidates.append((3, 'u8-relative', count8, header8, offsets8))
        if len(data) >= 4:
            count32 = u32le(data, 0)
            header32 = 4 + count32 * 4
            if 0 < count32 < 1024 and header32 <= len(data):
                offsets32 = [u32le(data, 4 + i * 4) for i in range(count32)]
                if offsets32 == sorted(offsets32) and all(0 <= off <= len(data) - header32 for off in offsets32):
                    candidates.append((2, 'u32-relative', count32, header32, offsets32))
                if offsets32 == sorted(offsets32) and all(header32 <= off <= len(data) for off in offsets32):
                    rel_offsets = [off - header32 for off in offsets32]
                    candidates.append((1, 'u32-absolute', count32, header32, rel_offsets))
        if not candidates:
            raise ValueError(f'Unable to detect container header for {len(data)} bytes')
        _, mode, count, header_size, offsets = max(candidates, key=lambda item: item[0])
        return mode, count, header_size, offsets

    def as_dict(self) -> dict[str, Any]:
        return {
            'header_mode': self.header_mode,
            'header_size': self.header_size,
            'chunk_count': self.chunk_count,
            'offsets': self.offsets,
            'chunks': [asdict(chunk) for chunk in self.chunk_infos],
        }


def open_jar_resources(jar_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(jar_path) as zf:
        names = set(zf.namelist())
        return {name: zf.read(name) for name in RESOURCE_ORDER if name in names}
