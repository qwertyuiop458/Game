from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import tempfile
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


def _load_frame_raw_block(atlas: Any, frame_index: int) -> bytes:
    if frame_index >= len(atlas.sprite_data_offsets) or frame_index >= len(atlas.sprite_lengths):
        return b''
    frame_offset = atlas.sprite_data_offsets[frame_index]
    frame_size = atlas.sprite_lengths[frame_index]
    if frame_offset < 0 or frame_size <= 0:
        return b''
    return atlas.sprite_data[frame_offset:frame_offset + frame_size]


def _compose_atlas_preview(frames: list[dict[str, Any]]) -> tuple[int, int, list[int]]:
    if not frames:
        return 1, 1, [0x00000000]
    width = sum(frame['width'] for frame in frames)
    height = max(frame['height'] for frame in frames)
    atlas_rgba = [0x00000000] * (width * height)
    cursor_x = 0
    for frame in frames:
        frame_width = frame['width']
        frame_height = frame['height']
        frame_rgba = frame['rgba']
        for y in range(frame_height):
            dst_row = y * width
            src_row = y * frame_width
            for x in range(frame_width):
                src_index = src_row + x
                if src_index < len(frame_rgba):
                    atlas_rgba[dst_row + cursor_x + x] = frame_rgba[src_index]
        cursor_x += frame_width
    return width, height, atlas_rgba


def _frame_contract(frame_index: int, width: int, height: int, rgba: list[int], decode_status: str) -> dict[str, Any]:
    metrics = _metrics(width, height, rgba)
    return {
        'frame_index': frame_index,
        'width': metrics['width'],
        'height': metrics['height'],
        'rgba_sha256': metrics['rgba_sha256'],
        'channel_sum': metrics['channel_sum'],
        'opaque_pixels': metrics['opaque_pixels'],
        'decode_status': decode_status,
        'pixel_count': metrics['pixel_count'],
    }


def _build_case_frames(atlas: Any) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for frame_index in range(atlas.frame_count):
        raw_block = _load_frame_raw_block(atlas, frame_index)
        width, height, rgba, decode_status = _decode_frame_with_status(atlas, frame_index, raw_block)
        frames.append(
            {
                'frame_index': frame_index,
                'width': width,
                'height': height,
                'rgba': rgba,
                'decode_status': decode_status,
                'raw_payload_size': len(raw_block),
            }
        )
    return frames


def _alpha_stats(rgba: list[int]) -> dict[str, int]:
    if not rgba:
        return {'min': 0, 'max': 0, 'non_zero': 0}
    alphas = [((px >> 24) & 0xFF) for px in rgba]
    return {'min': min(alphas), 'max': max(alphas), 'non_zero': sum(1 for alpha in alphas if alpha > 0)}


def _opaque_grayscale_fallback(width: int, height: int, indices: list[int] | None, raw_block: bytes) -> list[int]:
    total = max(1, width * height)
    source: list[int]
    if indices:
        source = [value & 0xFF for value in indices]
    elif raw_block:
        source = list(raw_block)
    else:
        source = [0]
    rgba: list[int] = []
    for idx in range(total):
        gray = source[idx % len(source)]
        rgba.append(0xFF000000 | (gray << 16) | (gray << 8) | gray)
    return rgba


def _decode_frame_with_status(atlas: Any, frame_index: int, raw_block: bytes) -> tuple[int, int, list[int], str]:
    frame = atlas.frames[frame_index]
    width = max(1, frame.width)
    height = max(1, frame.height)
    decode_status = 'decoded'
    decoded = atlas.rgba_for_frame(frame_index, 0)
    if decoded is not None:
        width, height, rgba = decoded
    else:
        rgba = []
    raw_size = len(raw_block)
    initial_alpha = _alpha_stats(rgba)
    alpha_failed = decoded is None or initial_alpha['non_zero'] == 0
    if raw_size > 0 and alpha_failed:
        indices = atlas.decode_frame_indices(frame_index)
        rgba = _opaque_grayscale_fallback(width, height, indices, raw_block)
        decode_status = 'degraded_decode'
    elif decoded is None:
        decode_status = 'failed_decode'
    return width, height, rgba, decode_status


def _build_expected_case(case: ReferenceCase) -> dict[str, Any]:
    table_blob = _load_bytes(case.table_chunk, case.table_chunk_hex)
    external_data = [(idx, _load_bytes(raw_path, hex_path)) for idx, raw_path, hex_path in case.external_chunks]
    atlas = parse_atlas(case.case_id, table_blob, chunk_index=0, external_chunks=external_data)
    frame_entries = _build_case_frames(atlas)
    frames_contract = [
        _frame_contract(
            frame_index=frame['frame_index'],
            width=frame['width'],
            height=frame['height'],
            rgba=frame['rgba'],
            decode_status=frame['decode_status'],
        )
        for frame in frame_entries
    ]
    total_channel_sum = {'r': 0, 'g': 0, 'b': 0, 'a': 0}
    total_opaque_pixels = 0
    total_pixels = 0
    for item in frames_contract:
        total_opaque_pixels += item['opaque_pixels']
        total_pixels += item['pixel_count']
        for channel in ('r', 'g', 'b', 'a'):
            total_channel_sum[channel] += item['channel_sum'][channel]

    preview_width, preview_height, preview_rgba = _compose_atlas_preview(frame_entries)
    preview_rgba_hash = _metrics(preview_width, preview_height, preview_rgba)['rgba_sha256']
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
        'frames': frames_contract,
        'totals': {
            'frame_count': len(frames_contract),
            'decoded_frames': sum(1 for frame in frames_contract if frame['decode_status'] == 'decoded'),
            'degraded_frames': sum(1 for frame in frames_contract if frame['decode_status'] == 'degraded_decode'),
            'failed_frames': sum(1 for frame in frames_contract if frame['decode_status'] == 'failed_decode'),
            'pixel_count': total_pixels,
            'opaque_pixels': total_opaque_pixels,
            'channel_sum': total_channel_sum,
            'frames_rgba_sha256': _sha256_hex(
                ''.join(frame['rgba_sha256'] for frame in frames_contract).encode('ascii')
            ),
            'preview_width': preview_width,
            'preview_height': preview_height,
            'preview_rgba_sha256': preview_rgba_hash,
            'preview_png_sha256': preview_hash,
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
        expected_frames = expected.get('frames', [])
        actual_frames = actual.get('frames', [])
        expected_indexes = [item.get('frame_index') for item in expected_frames]
        actual_indexes = [item.get('frame_index') for item in actual_frames]
        if len(expected_frames) != len(actual_frames) or expected_indexes != actual_indexes:
            mismatches.append(
                f'[{case.case_id}] frame set mismatch: '
                f'expected count/indexes={len(expected_frames)}/{expected_indexes}, '
                f'actual count/indexes={len(actual_frames)}/{actual_indexes}'
            )
        preview_bytes = _load_preview_png(case)
        png_width, png_height, png_rgba = _read_png_rgba_bytes(preview_bytes, case.case_id)
        png_metrics = _metrics(png_width, png_height, png_rgba)
        if png_metrics['rgba_sha256'] != actual['totals']['preview_rgba_sha256']:
            mismatches.append(
                f'[{case.case_id}] preview PNG pixel hash mismatch: '
                f"{png_metrics['rgba_sha256']} != {actual['totals']['preview_rgba_sha256']}"
            )
        actual['totals']['preview_png_sha256'] = _sha256_hex(preview_bytes)
        if expected != actual:
            mismatches.append(
                f'[{case.case_id}] metadata mismatch:\n'
                f'expected={json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n'
                f'actual={json.dumps(actual, ensure_ascii=False, sort_keys=True)}'
            )
    return mismatches


def collect_reference_case_updates(base_dir: Path = DEFAULT_CASES_DIR) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for case in load_reference_cases(base_dir):
        expected = json.loads(case.expected_metadata.read_text(encoding='utf-8'))
        actual = _build_expected_case(case)
        preview_bytes = _load_preview_png(case)
        actual['totals']['preview_png_sha256'] = _sha256_hex(preview_bytes)
        if expected == actual:
            continue
        updates.append(
            {
                'case_id': case.case_id,
                'expected_preview_hash': expected.get('totals', {}).get('preview_rgba_sha256'),
                'actual_preview_hash': actual.get('totals', {}).get('preview_rgba_sha256'),
                'expected_frame_count': expected.get('atlas', {}).get('frame_count'),
                'actual_frame_count': actual.get('atlas', {}).get('frame_count'),
            }
        )
    return updates


def update_reference_cases(base_dir: Path = DEFAULT_CASES_DIR) -> None:
    for case in load_reference_cases(base_dir):
        table_blob = _load_bytes(case.table_chunk, case.table_chunk_hex)
        external_data = [(idx, _load_bytes(raw_path, hex_path)) for idx, raw_path, hex_path in case.external_chunks]
        atlas = parse_atlas(case.case_id, table_blob, chunk_index=0, external_chunks=external_data)
        frame_entries = _build_case_frames(atlas)
        preview_width, preview_height, preview_rgba = _compose_atlas_preview(frame_entries)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            write_rgba_png(tmp_path, preview_width, preview_height, preview_rgba)
            _write_preview_png(case, tmp_path.read_bytes())
        finally:
            tmp_path.unlink(missing_ok=True)
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
            pending = collect_reference_case_updates(args.cases_dir)
            if pending:
                print('Reference updates require explicit review. Pending differences:')
                for item in pending:
                    print(
                        f"- {item['case_id']}: frame_count {item['expected_frame_count']} -> "
                        f"{item['actual_frame_count']}, rgba_sha256 {item['expected_preview_hash']} -> "
                        f"{item['actual_preview_hash']}"
                    )
            else:
                print('No reference changes detected, update confirmation is still required by policy.')
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
