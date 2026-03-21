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

from tools.common import Container, ensure_dir, open_jar_resources, write_json


def analyse_audio_blob(chunk: bytes) -> dict[str, Any]:
    return {
        'size': len(chunk),
        'head_hex': chunk[:32].hex(),
        'nonzero_bytes': sum(1 for b in chunk if b),
        'top_bytes': Counter(chunk).most_common(16),
    }


def decode_audio(jar_path: Path, output_dir: Path) -> dict[str, Any]:
    resources = open_jar_resources(jar_path)
    ensure_dir(output_dir)
    summary = {'midi': [], 'raw_audio': []}
    for name in ('m13_1', 'm13_2'):
        if name not in resources:
            continue
        container = Container(name, resources[name])
        pack_dir = output_dir / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            if not chunk:
                continue
            if b'MThd' in chunk:
                offset = chunk.index(b'MThd')
                midi_path = pack_dir / f'{idx:02d}.mid'
                midi_path.write_bytes(chunk[offset:])
                summary['midi'].append({'container': name, 'chunk_index': idx, 'path': str(midi_path)})
            else:
                raw_path = pack_dir / f'{idx:02d}.bin'
                raw_path.write_bytes(chunk)
                meta = analyse_audio_blob(chunk)
                meta_path = pack_dir / f'{idx:02d}.json'
                write_json(meta_path, meta)
                summary['raw_audio'].append({'container': name, 'chunk_index': idx, 'path': str(raw_path), 'meta_path': str(meta_path)})
    write_json(output_dir / 'audio_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode m13 audio resources')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out/extracted/audio'))
    args = parser.parse_args()
    decode_audio(args.jar, args.output)


if __name__ == '__main__':
    main()
