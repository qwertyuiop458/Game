from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOURCE_ORDER = [
    't0', 'm0', 'm1', 'm2', 'm3_0', 'm4_0', 'm5_0', 'm5_1', 'm5_2', 'm5_3', 'm5_4',
    'm5_5', 'm5_6', 'm5_7', 'm5_8', 'm5_9', 'm6_0', 'm6_1', 'm6_2', 'm6_3', 'm6_4',
    'm6_5', 'm7', 'm8', 'm9', 'm10', 'm11_0', 'm11_1', 'm12', 'm13_1', 'm13_2',
]

CHAPTER_COUNT = 6

COMMON_WIDTHS = [16, 20, 24, 25, 30, 32, 40, 48, 50, 60, 64, 72, 75, 80, 90, 96, 100, 120, 128]


def detect_m6_chapter_count(container_names: Any, fallback: int = CHAPTER_COUNT) -> int:
    if isinstance(container_names, dict):
        names = container_names.keys()
    else:
        names = container_names
    max_index = -1
    for name in names:
        match = re.fullmatch(r'm6_(\d+)', str(name))
        if not match:
            continue
        max_index = max(max_index, int(match.group(1)))
    return max_index + 1 if max_index >= 0 else fallback


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


def rgb565_to_rgba(word: int) -> int:
    r = ((word >> 11) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x3F) * 255 // 63
    b = (word & 0x1F) * 255 // 31
    return 0xFF000000 | (r << 16) | (g << 8) | b


def pseudo_color(value: int) -> int:
    value &= 0xFFFF
    r = (value * 53) & 0xFF
    g = (value * 97) & 0xFF
    b = (value * 193) & 0xFF
    return 0xFF000000 | (r << 16) | (g << 8) | b


def decode_game_text(blob: bytes) -> str:
    try:
        utf8 = blob.decode('utf-8')
        return utf8.encode('latin1', errors='replace').decode('cp1251', errors='replace')
    except UnicodeDecodeError:
        return blob.decode('cp1251', errors='replace')


def sanitize_text(text: str) -> str:
    return ''.join(ch if ch >= ' ' or ch in '\n\t' else ' ' for ch in text).replace('\x00', ' ')


@dataclass
class ChunkInfo:
    index: int
    relative_start: int
    relative_end: int
    absolute_start: int
    absolute_end: int
    size: int
    crc32_hex: str
    sha1: str


class ContainerValidationError(ValueError):
    def __init__(self, container_name: str, diagnostics: list[str], header_mode: str, chunk_count: int, data_length: int):
        self.container_name = container_name
        self.diagnostics = diagnostics
        self.header_mode = header_mode
        self.chunk_count = chunk_count
        self.data_length = data_length
        message = (
            f'Invalid container table for container_name="{container_name}" '
            f'(mode={header_mode}, chunk_count={chunk_count}, bytes={data_length}): '
            + '; '.join(diagnostics)
        )
        super().__init__(message)


def validate_container_layout(data: bytes, header_size: int, offsets: list[int]) -> list[str]:
    errors: list[str] = []
    total_size = len(data)
    if header_size > total_size:
        errors.append(f'header_size {header_size} exceeds data length {total_size}')
    payload_size = max(0, total_size - header_size)
    for idx, off in enumerate(offsets):
        if not (0 <= off <= total_size):
            errors.append(f'offset[{idx}]={off} out of bounds [0, {total_size}]')
    for idx in range(len(offsets) - 1):
        if offsets[idx] > offsets[idx + 1]:
            errors.append(f'offsets are not monotonic at {idx}->{idx + 1}: {offsets[idx]} > {offsets[idx + 1]}')
    for idx, start in enumerate(offsets):
        end = offsets[idx + 1] if idx + 1 < len(offsets) else payload_size
        size = end - start
        if size < 0:
            errors.append(f'chunk[{idx}] has negative size: {size}')
    return errors


class Container:
    """Gameloft container format used by m* and t0.

    g.class reads one byte chunk_count, then chunk_count little-endian u32 offsets.
    The offsets are relative to the payload area *after* the header, not to file start.
    """

    @staticmethod
    def parse_u32_header(data: bytes) -> dict[str, Any]:
        if not data:
            return {
                'header_mode': 'u32',
                'chunk_count': 0,
                'header_size': 0,
                'payload_base': 0,
                'payload_size': 0,
                'offsets': [],
                'valid': True,
                'validation_errors': [],
            }
        chunk_count = data[0]
        header_size = 1 + chunk_count * 4
        if header_size <= len(data):
            offsets = [u32le(data, 1 + i * 4) for i in range(chunk_count)]
        else:
            available = max(0, (len(data) - 1) // 4)
            offsets = [u32le(data, 1 + i * 4) for i in range(available)]
        errors = validate_container_layout(data, header_size, offsets)
        return {
            'header_mode': 'u32',
            'chunk_count': chunk_count,
            'header_size': header_size,
            'payload_base': header_size,
            'payload_size': max(0, len(data) - header_size),
            'offsets': offsets,
            'valid': len(errors) == 0,
            'validation_errors': errors,
        }

    @staticmethod
    def parse_u8_header(data: bytes) -> dict[str, Any]:
        if not data:
            return {
                'header_mode': 'u8',
                'chunk_count': 0,
                'header_size': 0,
                'payload_base': 0,
                'payload_size': 0,
                'offsets': [],
                'valid': True,
                'validation_errors': [],
            }
        chunk_count = data[0]
        header_size = 1 + chunk_count
        offsets = [data[1 + i] for i in range(min(chunk_count, max(0, len(data) - 1)))]
        errors = validate_container_layout(data, header_size, offsets)
        return {
            'header_mode': 'u8',
            'chunk_count': chunk_count,
            'header_size': header_size,
            'payload_base': header_size,
            'payload_size': max(0, len(data) - header_size),
            'offsets': offsets,
            'valid': len(errors) == 0,
            'validation_errors': errors,
        }

    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data
        parsed_u32 = self.parse_u32_header(data)
        parsed_u8 = self.parse_u8_header(data)
        if parsed_u32['valid'] and not parsed_u8['valid']:
            parsed = parsed_u32
        elif parsed_u8['valid'] and not parsed_u32['valid']:
            parsed = parsed_u8
        elif parsed_u32['valid'] and parsed_u8['valid']:
            parsed = parsed_u32
        elif len(parsed_u32['validation_errors']) <= len(parsed_u8['validation_errors']):
            parsed = parsed_u32
        else:
            parsed = parsed_u8

        self.header_mode = parsed['header_mode']
        self.chunk_count = parsed['chunk_count']
        self.header_size = parsed['header_size']
        self.payload_base = parsed['payload_base']
        self.offsets = parsed['offsets']
        self.payload_size = parsed['payload_size']
        self.valid = parsed['valid']
        self.validation_errors = parsed['validation_errors']
        if self.chunk_count == 0:
            self.offsets = []
        if len(data) < 5:
            self.validation_errors = [
                *self.validation_errors,
                f'data length {len(data)} is too small for stable container parsing (<5 bytes)',
            ]
            self.valid = False
        if not self.valid:
            raise ContainerValidationError(
                container_name=self.name,
                diagnostics=self.validation_errors,
                header_mode=self.header_mode,
                chunk_count=self.chunk_count,
                data_length=len(data),
            )
        self.payloads: list[bytes] = []
        self.relative_ranges: list[tuple[int, int]] = []
        self.absolute_ranges: list[tuple[int, int]] = []
        for index, start in enumerate(self.offsets):
            end = self.offsets[index + 1] if index + 1 < len(self.offsets) else self.payload_size
            start = max(0, min(start, self.payload_size))
            end = max(start, min(end, self.payload_size))
            self.relative_ranges.append((start, end))
            abs_start = self.payload_base + start
            abs_end = self.payload_base + end
            self.absolute_ranges.append((abs_start, abs_end))
            self.payloads.append(data[abs_start:abs_end])

    def describe(self) -> dict[str, Any]:
        chunks = []
        for idx, chunk in enumerate(self.payloads):
            rel_start, rel_end = self.relative_ranges[idx]
            abs_start, abs_end = self.absolute_ranges[idx]
            chunks.append(ChunkInfo(
                index=idx,
                relative_start=rel_start,
                relative_end=rel_end,
                absolute_start=abs_start,
                absolute_end=abs_end,
                size=len(chunk),
                crc32_hex=f'{zlib.crc32(chunk) & 0xFFFFFFFF:08x}',
                sha1=hashlib.sha1(chunk).hexdigest(),
            ).__dict__)
        return {
            'header_mode': self.header_mode,
            'validation': 'ok' if self.valid else 'errors',
            'valid': self.valid,
            'validation_errors': self.validation_errors,
            'chunk_count': self.chunk_count,
            'header_size': self.header_size,
            'payload_size': self.payload_size,
            'offsets': self.offsets,
            'chunks': chunks,
        }


class JarProject:
    def __init__(self, jar_path: Path, output_dir: Path):
        self.jar_path = jar_path
        self.output_dir = output_dir
        self.containers: dict[str, Container] = {}
        self.container_errors: dict[str, dict[str, Any]] = {}
        self.raw_entries: dict[str, bytes] = {}

    def load(self) -> None:
        with zipfile.ZipFile(self.jar_path) as zf:
            names = set(zf.namelist())
            for name in RESOURCE_ORDER:
                if name in names:
                    try:
                        self.containers[name] = Container(name, zf.read(name))
                    except ContainerValidationError as exc:
                        self.container_errors[name] = {
                            'header_mode': exc.header_mode,
                            'validation': 'errors',
                            'valid': False,
                            'validation_errors': exc.diagnostics,
                            'chunk_count': exc.chunk_count,
                            'data_length': exc.data_length,
                        }
            for name in ('icon.png', 'dataIGP', 'a.class', 'c.class', 'g.class', 'palettesAmount.bin'):
                if name in names:
                    self.raw_entries[name] = zf.read(name)
