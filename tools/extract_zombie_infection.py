#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from typing import Any

from tools.common import ensure_dir, open_jar_resources, write_json
from tools.decode_audio_m13 import decode_audio
from tools.decode_graphics import decode_graphics
from tools.decode_maps import decode_maps
from tools.decode_text_t0 import decode_text
from tools.parse_packs import parse_packs


def export_ui_assets(resources: dict[str, bytes], output_dir: Path) -> dict[str, Any]:
    ensure_dir(output_dir)
    summary: dict[str, Any] = {}
    if 'icon.png' in resources:
        icon_path = output_dir / 'icon.png'
        icon_path.write_bytes(resources['icon.png'])
        summary['icon_png'] = str(icon_path)
    if 'dataIGP' in resources:
        igp_path = output_dir / 'dataIGP.bin'
        igp_path.write_bytes(resources['dataIGP'])
        summary['dataIGP'] = str(igp_path)
    for cls_name in ('a.class', 'c.class', 'g.class'):
        if cls_name in resources:
            class_path = output_dir / cls_name
            class_path.write_bytes(resources[cls_name])
            summary.setdefault('engine_classes', []).append(str(class_path))
    write_json(output_dir / 'ui_summary.json', summary)
    return summary


def extract_all(jar_path: Path, output_root: Path) -> dict[str, Any]:
    resources = open_jar_resources(jar_path)
    ensure_dir(output_root)
    chunks = parse_packs(jar_path, output_root / 'chunks')
    text = decode_text(jar_path, output_root / 'extracted' / 'text')
    audio = decode_audio(jar_path, output_root / 'extracted' / 'audio')
    graphics = decode_graphics(jar_path, output_root / 'extracted')
    maps = decode_maps(jar_path, output_root / 'extracted')
    ui = export_ui_assets(resources, output_root / 'extracted' / 'ui')
    summary = {
        'jar': str(jar_path),
        'chunks': list(chunks),
        'text': text,
        'audio': audio,
        'graphics': {'packs': list(graphics.get('packs', {}))},
        'maps': maps,
        'ui': ui,
    }
    write_json(output_root / 'summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Full extractor for 240x320-rus-zombie-infection.jar')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    extract_all(args.jar, args.output)


if __name__ == '__main__':
    main()
