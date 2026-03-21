#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from typing import Any

from tools.common import Container, decode_game_text, ensure_dir, open_jar_resources, sanitize_name, u32le, write_json


def sanitize_text(text: str) -> str:
    return ''.join(ch if ch >= ' ' or ch in '\n\t' else ' ' for ch in text).replace('\x00', ' ')


def guess_offset_table(chunk: bytes) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    limit = min(len(chunk), 1024)
    for start in range(0, limit, 2):
        offsets: list[int] = []
        pos = start
        while pos + 4 <= len(chunk):
            value = u32le(chunk, pos)
            if value > len(chunk):
                break
            if offsets and value < offsets[-1]:
                break
            offsets.append(value)
            pos += 4
            payload_remaining = len(chunk) - pos
            if offsets and offsets[-1] <= payload_remaining:
                candidate = {
                    'table_start': start,
                    'count': len(offsets),
                    'blob_start': pos,
                    'max_offset': offsets[-1],
                }
                if best is None or (candidate['count'], candidate['max_offset']) > (best['count'], best['max_offset']):
                    best = candidate
    return best if best and best['count'] >= 4 else None


def decode_text(jar_path: Path, output_dir: Path) -> dict[str, Any]:
    resources = open_jar_resources(jar_path)
    if 't0' not in resources:
        return {}
    container = Container('t0', resources['t0'])
    ensure_dir(output_dir)
    summary: dict[str, Any] = {'chunk_count': container.chunk_count, 'chunks': []}
    for idx, chunk in enumerate(container.payloads):
        decoded = sanitize_text(decode_game_text(chunk))
        stem = f't0_{idx:02d}'
        full_path = output_dir / f'{stem}_full.txt'
        full_path.write_text(decoded, encoding='utf-8')
        row: dict[str, Any] = {
            'chunk_index': idx,
            'char_length': len(decoded),
            'full_path': str(full_path),
        }
        table = guess_offset_table(chunk)
        if table:
            offsets = [u32le(chunk, table['table_start'] + i * 4) for i in range(table['count'])]
            combined = chunk[:table['table_start']] + chunk[table['blob_start']:]
            last = 0
            segments = []
            for end in offsets:
                if 0 <= last <= end <= len(combined):
                    text = sanitize_text(decode_game_text(combined[last:end]))
                    if text.strip():
                        segments.append(text)
                last = end
            if last < len(combined):
                tail = sanitize_text(decode_game_text(combined[last:]))
                if tail.strip():
                    segments.append(tail)
            seg_json = output_dir / f'{stem}_segments.json'
            seg_txt = output_dir / f'{stem}_segments.txt'
            write_json(seg_json, {'chunk_index': idx, 'offset_table': table, 'segments': segments})
            seg_txt.write_text('\n'.join(segments) + ('\n' if segments else ''), encoding='utf-8')
            row |= {
                'segment_count': len(segments),
                'segments_json': str(seg_json),
                'segments_text': str(seg_txt),
            }
            named_dir = output_dir / f'{stem}_named'
            ensure_dir(named_dir)
            for seg_index, text in enumerate(segments[:256]):
                label = sanitize_name(text.splitlines()[0][:48] or f'segment_{seg_index:03d}')
                (named_dir / f'{seg_index:03d}_{label}.txt').write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
        summary['chunks'].append(row)
    write_json(output_dir / 'text_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode t0 text resources')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out/extracted/text'))
    args = parser.parse_args()
    decode_text(args.jar, args.output)


if __name__ == '__main__':
    main()
