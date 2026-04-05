from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common import write_rgba_png
from tools.graphics_decoder import parse_atlas


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = ROOT / 'tests' / 'reference_cases' / 'graphics'


@dataclass
class ReferenceCase:
    case_id: str
    description: str
    table_chunk: Path | None
    table_chunk_hex: Path | None
    external_chunks: list[tuple[int, Path | None, Path | None]]
    expected_preview: Path | None
    expected_preview_b64: Path | None
    expected_metadata: Path


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _load_bytes(raw_path: Path | None, hex_path: Path | None) -> bytes:
    if raw_path is not None and raw_path.exists():
        return raw_path.read_bytes()
    if hex_path is not None and hex_path.exists():
        return bytes.fromhex(hex_path.read_text(encoding='utf-8').strip())
    raise FileNotFoundError(f'Cannot load bytes: raw={raw_path}, hex={hex_path}')


def _load_preview_png(case: ReferenceCase) -> bytes:
    if case.expected_preview is not None and case.expected_preview.exists():
        return case.expected_preview.read_bytes()
    if case.expected_preview_b64 is not None and case.expected_preview_b64.exists():
        return base64.b64decode(case.expected_preview_b64.read_text(encoding='utf-8').strip())
    raise FileNotFoundError(
        f'Case {case.case_id}: missing preview source '
        f'(preview={case.expected_preview}, preview_b64={case.expected_preview_b64})'
    )


def _write_preview_png(case: ReferenceCase, png_bytes: bytes) -> None:
    if case.expected_preview_b64 is not None:
        case.expected_preview_b64.write_text(base64.b64encode(png_bytes).decode('ascii') + '\n', encoding='utf-8')
        if case.expected_preview is not None and case.expected_preview.exists():
            case.expected_preview.unlink()
        return
    if case.expected_preview is None:
        raise ValueError(f'Case {case.case_id}: no target preview file configured')
    case.expected_preview.write_bytes(png_bytes)


def _read_png_rgba(path: Path) -> tuple[int, int, list[int]]:
    data = path.read_bytes()
    return _read_png_rgba_bytes(data, path.as_posix())


def _read_png_rgba_bytes(data: bytes, label: str = '<bytes>') -> tuple[int, int, list[int]]:
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'Invalid PNG signature: {label}')
    cursor = 8
    width = 0
    height = 0
    idat = bytearray()
    while cursor + 8 <= len(data):
        chunk_len = struct.unpack('>I', data[cursor:cursor + 4])[0]
        tag = data[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        payload_end = payload_start + chunk_len
        payload = data[payload_start:payload_end]
        if tag == b'IHDR':
            width = struct.unpack('>I', payload[0:4])[0]
            height = struct.unpack('>I', payload[4:8])[0]
            bit_depth = payload[8]
            color_type = payload[9]
            if bit_depth != 8 or color_type != 6:
                raise ValueError(f'Unsupported PNG format (expect RGBA8): {label}')
        elif tag == b'IDAT':
            idat.extend(payload)
        elif tag == b'IEND':
            break
        cursor = payload_end + 4  # skip crc
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    rgba: list[int] = []
    read = 0
    for _ in range(height):
        filter_type = raw[read]
        if filter_type != 0:
            raise ValueError(f'Unsupported PNG filter {filter_type} in {label}')
        read += 1
        row = raw[read:read + stride]
        read += stride
        for x in range(0, len(row), 4):
            r, g, b, a = row[x:x + 4]
            rgba.append((a << 24) | (r << 16) | (g << 8) | b)
    return width, height, rgba


def _metrics(width: int, height: int, rgba: list[int]) -> dict[str, Any]:
    total = max(1, len(rgba))
    channel_sum = {'r': 0, 'g': 0, 'b': 0, 'a': 0}
    opaque_pixels = 0
    for px in rgba:
        channel_sum['r'] += (px >> 16) & 0xFF
        channel_sum['g'] += (px >> 8) & 0xFF
        channel_sum['b'] += px & 0xFF
        alpha = (px >> 24) & 0xFF
        channel_sum['a'] += alpha
        if alpha > 0:
            opaque_pixels += 1
    packed = b''.join(struct.pack('<I', px & 0xFFFFFFFF) for px in rgba)
    return {
        'width': width,
        'height': height,
        'pixel_count': len(rgba),
        'opaque_pixels': opaque_pixels,
        'unique_colors': len(set(rgba)),
        'channel_sum': channel_sum,
        'channel_mean': {k: round(v / total, 4) for k, v in channel_sum.items()},
        'rgba_sha256': _sha256_hex(packed),
    }


def _build_expected_case(case: ReferenceCase) -> dict[str, Any]:
    table_blob = _load_bytes(case.table_chunk, case.table_chunk_hex)
    external_data = [(idx, _load_bytes(raw_path, hex_path)) for idx, raw_path, hex_path in case.external_chunks]
    atlas = parse_atlas(case.case_id, table_blob, chunk_index=0, external_chunks=external_data)
    decoded = atlas.rgba_for_frame(0, 0)
    if decoded is None:
        raise ValueError(f'Case {case.case_id}: frame 0 failed to decode')
    width, height, rgba = decoded
    preview_hash = _sha256_hex(_load_preview_png(case))
    table_hash = _sha256_hex(table_blob)
    external_hashes = {str(idx): _sha256_hex(payload) for idx, payload in external_data}
    return {
        'case_id': case.case_id,
        'description': case.description,
        'atlas': {
            'pixel_format': atlas.pixel_format,
            'palette_format': atlas.palette_format,
            'palette_size': atlas.palette_size,
            'palette_count': len(atlas.palettes),
            'frame_count': atlas.frame_count,
        },
        'inputs': {
            'table_sha256': table_hash,
            'external_sha256': external_hashes,
        },
        'preview': {
            **_metrics(width, height, rgba),
            'png_sha256': preview_hash,
        },
    }


def load_reference_cases(base_dir: Path = DEFAULT_CASES_DIR) -> list[ReferenceCase]:
    cases: list[ReferenceCase] = []
    for manifest_path in sorted(base_dir.glob('*/case.json')):
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        case_dir = manifest_path.parent
        external_chunks = []
        for item in payload.get('external_chunks', []):
            raw_path = case_dir / item['file'] if 'file' in item else None
            hex_path = case_dir / item['hex_file'] if 'hex_file' in item else None
            external_chunks.append((int(item['chunk_index']), raw_path, hex_path))
        cases.append(
            ReferenceCase(
                case_id=payload['case_id'],
                description=payload['description'],
                table_chunk=case_dir / payload['table_chunk'] if 'table_chunk' in payload else None,
                table_chunk_hex=case_dir / payload['table_chunk_hex'] if 'table_chunk_hex' in payload else None,
                external_chunks=external_chunks,
                expected_preview=case_dir / payload['preview_png'] if 'preview_png' in payload else None,
                expected_preview_b64=(
                    case_dir / payload['preview_png_base64'] if 'preview_png_base64' in payload else None
                ),
                expected_metadata=case_dir / payload['metadata_json'],
            )
        )
    return cases


def verify_reference_cases(base_dir: Path = DEFAULT_CASES_DIR) -> list[str]:
    mismatches: list[str] = []
    for case in load_reference_cases(base_dir):
        expected = json.loads(case.expected_metadata.read_text(encoding='utf-8'))
        actual = _build_expected_case(case)
        preview_bytes = _load_preview_png(case)
        png_width, png_height, png_rgba = _read_png_rgba_bytes(preview_bytes, case.case_id)
        png_metrics = _metrics(png_width, png_height, png_rgba)
        if png_metrics['rgba_sha256'] != actual['preview']['rgba_sha256']:
            mismatches.append(
                f'[{case.case_id}] preview PNG pixel hash mismatch: '
                f"{png_metrics['rgba_sha256']} != {actual['preview']['rgba_sha256']}"
            )
        actual['preview']['png_sha256'] = _sha256_hex(preview_bytes)
        if expected != actual:
            mismatches.append(
                f'[{case.case_id}] metadata mismatch:\n'
                f'expected={json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n'
                f'actual={json.dumps(actual, ensure_ascii=False, sort_keys=True)}'
            )
    return mismatches


def update_reference_cases(base_dir: Path = DEFAULT_CASES_DIR) -> None:
    for case in load_reference_cases(base_dir):
        table_blob = _load_bytes(case.table_chunk, case.table_chunk_hex)
        external_data = [(idx, _load_bytes(raw_path, hex_path)) for idx, raw_path, hex_path in case.external_chunks]
        atlas = parse_atlas(case.case_id, table_blob, chunk_index=0, external_chunks=external_data)
        decoded = atlas.rgba_for_frame(0, 0)
        if decoded is None:
            raise ValueError(f'Case {case.case_id}: frame 0 failed to decode')
        width, height, rgba = decoded
        tmp_png_path = case.expected_metadata.parent / '.tmp_preview.png'
        write_rgba_png(tmp_png_path, width, height, rgba)
        _write_preview_png(case, tmp_png_path.read_bytes())
        tmp_png_path.unlink(missing_ok=True)
        payload = _build_expected_case(case)
        case.expected_metadata.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
            encoding='utf-8',
        )


def main() -> None:
    parser = argparse.ArgumentParser(description='Validate or update graphics reference cases.')
    parser.add_argument('--cases-dir', type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument('--update', action='store_true', help='Regenerate preview images and metadata.')
    parser.add_argument(
        '--confirm-update',
        action='store_true',
        help='Explicitly confirm that expected reference files should be rewritten.',
    )
    args = parser.parse_args()

    if args.update:
        if not args.confirm_update:
            raise SystemExit('Refusing to update reference cases without --confirm-update')
        update_reference_cases(args.cases_dir)
        print(f'Updated reference cases in {args.cases_dir}')
        return

    mismatches = verify_reference_cases(args.cases_dir)
    if mismatches:
        for line in mismatches:
            print(line)
        raise SystemExit(1)
    print(f'All reference cases are consistent ({args.cases_dir})')


if __name__ == '__main__':
    main()
