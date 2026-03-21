#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from typing import Any

from tools.common import Container, ensure_dir, open_jar_resources, write_json


def classify_chunk(name: str, index: int, chunk: bytes) -> tuple[str, list[str]]:
    notes: list[str] = []
    if name == 't0':
        return 'string_table', notes
    if name in {'m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1'}:
        if index == 0:
            return 'graphics_descriptor', ['parsed by decode_graphics.py']
        return 'graphics_payload', notes
    if name.startswith('m6_'):
        return ('tile_layer' if index % 2 == 0 else 'collision_or_sidecar'), notes
    if name in {'m8', 'm9', 'm10'}:
        return 'map_or_script', notes
    if name.startswith('m13_'):
        return ('midi_or_audio', ['contains MThd header'] if b'MThd' in chunk else notes)
    return 'binary', notes


def parse_packs(jar_path: Path, output_dir: Path) -> dict[str, Any]:
    ensure_dir(output_dir)
    resources = open_jar_resources(jar_path)
    summary: dict[str, Any] = {}
    for name, data in resources.items():
        if not (name == 't0' or name.startswith('m')):
            continue
        container = Container(name, data)
        pack_dir = output_dir / name
        ensure_dir(pack_dir)
        chunk_rows = []
        for index, chunk in enumerate(container.payloads):
            raw_path = pack_dir / f'{index:02d}.bin'
            raw_path.write_bytes(chunk)
            kind, notes = classify_chunk(name, index, chunk)
            record = container.chunk_infos[index].__dict__ | {
                'kind': kind,
                'notes': notes,
                'path': str(raw_path),
            }
            chunk_rows.append(record)
        summary[name] = container.as_dict() | {'classified_chunks': chunk_rows}
    write_json(output_dir / 'pack_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Parse Zombie Infection m* containers')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out/chunks'))
    args = parser.parse_args()
    parse_packs(args.jar, args.output)


if __name__ == '__main__':
    main()
