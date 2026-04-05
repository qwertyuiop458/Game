from __future__ import annotations

import argparse
import hashlib
import zipfile
import zlib
from pathlib import Path
from typing import Any

from tools.common import RESOURCE_ORDER, ensure_dir, u32le, write_json


def _validate_offsets(payload_size: int, offsets: list[int], chunk_count: int, header_size: int, data_length: int) -> list[str]:
    errors: list[str] = []
    if header_size > data_length:
        errors.append(f'header_size {header_size} exceeds data length {data_length}')
    if len(offsets) != chunk_count:
        errors.append(f'offset_count {len(offsets)} differs from chunk_count {chunk_count}')
    for idx, off in enumerate(offsets):
        if off < 0:
            errors.append(f'offset[{idx}]={off} is negative')
        if off > payload_size:
            errors.append(f'offset[{idx}]={off} exceeds payload_size {payload_size}')
    for idx in range(len(offsets) - 1):
        if offsets[idx] > offsets[idx + 1]:
            errors.append(f'offsets are not monotonic at {idx}->{idx + 1}: {offsets[idx]} > {offsets[idx + 1]}')
    for idx, start in enumerate(offsets):
        end = offsets[idx + 1] if idx + 1 < len(offsets) else payload_size
        size = end - start
        if size < 0:
            errors.append(f'chunk[{idx}] has negative size: {size}')
    return errors


def _parse_header(data: bytes, mode: str) -> dict[str, Any]:
    if not data:
        return {
            'header_mode': mode,
            'chunk_count': 0,
            'header_size': 0,
            'payload_size': 0,
            'offsets': [],
            'validation_errors': [],
        }

    chunk_count = data[0]
    if mode == 'u32':
        header_size = 1 + chunk_count * 4
        available = max(0, (len(data) - 1) // 4)
        offsets = [u32le(data, 1 + i * 4) for i in range(min(chunk_count, available))]
    else:
        header_size = 1 + chunk_count
        available = max(0, len(data) - 1)
        offsets = [data[1 + i] for i in range(min(chunk_count, available))]

    payload_size = max(0, len(data) - header_size)
    errors = _validate_offsets(
        payload_size=payload_size,
        offsets=offsets,
        chunk_count=chunk_count,
        header_size=header_size,
        data_length=len(data),
    )

    return {
        'header_mode': mode,
        'chunk_count': chunk_count,
        'header_size': header_size,
        'payload_size': payload_size,
        'offsets': offsets,
        'validation_errors': errors,
    }


def parse_container(data: bytes, name: str) -> dict[str, Any]:
    parsed_u32 = _parse_header(data, 'u32')
    parsed_u8 = _parse_header(data, 'u8')

    u32_ok = len(parsed_u32['validation_errors']) == 0
    u8_ok = len(parsed_u8['validation_errors']) == 0
    if u32_ok and not u8_ok:
        parsed = parsed_u32
    elif u8_ok and not u32_ok:
        parsed = parsed_u8
    elif u32_ok and u8_ok:
        parsed = parsed_u32
    elif len(parsed_u32['validation_errors']) <= len(parsed_u8['validation_errors']):
        parsed = parsed_u32
    else:
        parsed = parsed_u8

    payload_base = parsed['header_size']
    payload_size = parsed['payload_size']
    chunks = []
    for idx, start in enumerate(parsed['offsets']):
        end = parsed['offsets'][idx + 1] if idx + 1 < len(parsed['offsets']) else payload_size
        abs_start = payload_base + start
        abs_end = payload_base + end
        chunk = data[abs_start:abs_end]

        entry: dict[str, Any] = {
            'index': idx,
            'relative_start': start,
            'relative_end': end,
            'absolute_start': abs_start,
            'absolute_end': abs_end,
            'size': len(chunk),
            'crc32_hex': f'{zlib.crc32(chunk) & 0xFFFFFFFF:08x}',
            'sha1': hashlib.sha1(chunk).hexdigest(),
        }

        if name == 'm9':
            if idx == 0:
                entry['m9_kind'] = 'table_chunk0_levels'
            elif idx == 1:
                entry['m9_kind'] = 'table_chunk1_u16'
            elif idx == 2:
                entry['m9_kind'] = 'table_chunk2_u16'
            elif idx >= 10:
                entry['m9_kind'] = 'script_chunk'
                entry['script_level_index'] = idx - 10
            else:
                entry['m9_kind'] = 'reserved_or_unknown'

        chunks.append(entry)

    validation_errors = parsed['validation_errors']
    return {
        'header_mode': parsed['header_mode'],
        'validation': 'ok' if not validation_errors else 'errors',
        'valid': not validation_errors,
        'validation_errors': validation_errors,
        'chunk_count': parsed['chunk_count'],
        'header_size': parsed['header_size'],
        'payload_size': payload_size,
        'offsets': parsed['offsets'],
        'chunks': chunks,
    }


def parse_packs(jar: Path, output: Path) -> dict:
    out = {}
    validation_report = {}
    chunk_root = output / 'chunks'
    ensure_dir(chunk_root)

    with zipfile.ZipFile(jar) as zf:
        names = set(zf.namelist())
        for name in RESOURCE_ORDER:
            if name not in names:
                continue
            raw = zf.read(name)
            parsed = parse_container(raw, name)
            out[name] = parsed

            pack_dir = chunk_root / name
            ensure_dir(pack_dir)
            for idx, chunk in enumerate(parsed['chunks']):
                blob = raw[chunk['absolute_start']:chunk['absolute_end']]
                (pack_dir / f'{idx:02d}.bin').write_bytes(blob)

            chunk_sizes = [chunk['size'] for chunk in parsed['chunks']]
            suspicious_chunks = []
            for chunk in parsed['chunks']:
                reasons = []
                if chunk['relative_start'] > chunk['relative_end']:
                    reasons.append('start_greater_than_end')
                if chunk['relative_start'] < 0 or chunk['relative_end'] < 0:
                    reasons.append('negative_range')
                if chunk['relative_end'] > parsed['payload_size']:
                    reasons.append('range_exceeds_payload')
                if chunk['size'] == 0:
                    reasons.append('empty_chunk')
                if reasons:
                    suspicious_chunks.append({
                        'index': chunk['index'],
                        'start': chunk['relative_start'],
                        'end': chunk['relative_end'],
                        'size': chunk['size'],
                        'reasons': reasons,
                    })

            validation_report[name] = {
                'header_mode': parsed['header_mode'],
                'validation': parsed['validation'],
                'valid': parsed['valid'],
                'validation_errors': parsed['validation_errors'],
                'count': parsed['chunk_count'],
                'offsets': parsed['offsets'],
                'min_chunk_size': min(chunk_sizes) if chunk_sizes else 0,
                'max_chunk_size': max(chunk_sizes) if chunk_sizes else 0,
                'suspicious_chunks': suspicious_chunks,
            }

    write_json(output / 'chunks' / 'containers.json', out)
    write_json(output / 'chunks' / 'container_validation.json', validation_report)
    write_json(output / 'extracted' / 'meta' / 'containers.json', out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description='Parse Gameloft m* containers from Zombie Infection')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    parse_packs(args.jar, args.output)


if __name__ == '__main__':
    main()
