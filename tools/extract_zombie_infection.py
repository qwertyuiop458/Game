from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import zlib
from pathlib import Path
from typing import Any

if __package__ in {None, ''}:
    # Allow direct script run: `python tools/extract_zombie_infection.py ...`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common import JarProject, ensure_dir, write_json
from tools.decode_audio_m13 import decode_audio
from tools.decode_graphics import decode_graphics
from tools.decode_maps import build_chapter_mission_matrix, build_final_table, decode_maps
from tools.decode_text_t0 import ENCODING_CHAIN, decode_text
from tools.linker import build_chapter_matrix
from tools.parse_packs import parse_packs


def extract_ui_assets(project: JarProject, output: Path) -> dict:
    ui_dir = output / 'extracted' / 'ui'
    meta_dir = output / 'extracted' / 'meta'
    ensure_dir(ui_dir)
    ensure_dir(meta_dir)
    expected_assets = ('icon.png', 'dataIGP')
    copied_assets: dict[str, str] = {}
    missing_assets: list[str] = []
    manifest_files: list[dict[str, str | int]] = []

    for asset_name in expected_assets:
        payload = project.raw_entries.get(asset_name)
        if payload is None:
            missing_assets.append(asset_name)
            continue

        target_path = ui_dir / asset_name
        target_path.write_bytes(payload)
        copied_assets[asset_name] = str(target_path.relative_to(output))
        manifest_files.append({
            'name': asset_name,
            'path': copied_assets[asset_name],
            'size_bytes': len(payload),
            'crc32_hex': f'{zlib.crc32(payload) & 0xFFFFFFFF:08x}',
            'sha1': hashlib.sha1(payload).hexdigest(),
        })

    if missing_assets:
        logging.warning(
            'UI assets are missing in %s: %s',
            project.jar_path,
            ', '.join(missing_assets),
        )

    manifest = {
        'source_jar': project.jar_path.name,
        'files': manifest_files,
        'missing_files': missing_assets,
    }
    write_json(meta_dir / 'ui_manifest.json', manifest)
    return {
        'copied': copied_assets,
        'missing': missing_assets,
        'manifest': str((meta_dir / 'ui_manifest.json').relative_to(output)),
    }


def run_extractor(jar: Path, output: Path, strings_encoding: str | None = None) -> dict:
    project = JarProject(jar, output)
    project.load()
    ensure_dir(output)
    chunks = parse_packs(jar, output)
    text = decode_text(jar, output, strings_encoding=strings_encoding)
    audio = decode_audio(jar, output)
    maps_bundle = decode_maps(jar, output)
    graphics = decode_graphics(jar, output)
    ui = extract_ui_assets(project, output)
    final_table = build_final_table(project, output, maps_bundle['maps'], maps_bundle['scripts'], audio, text)
    chapter_mission_matrix = build_chapter_mission_matrix(
        project,
        output,
        maps_bundle['maps'],
        maps_bundle['scripts'],
        graphics,
        audio,
        text,
    )
    chapter_matrix = build_chapter_matrix(jar, output)
    container_quality: dict[str, dict[str, Any]] = {}
    for name, info in chunks.items():
        validation_errors = info.get('validation_errors')
        if validation_errors is None:
            normalized_errors: list[str] = []
        else:
            normalized_errors = [str(error) for error in validation_errors]

        details: dict[str, Any] = {
            'header_mode': info.get('header_mode'),
            'validation': info.get('validation', 'errors'),
            'validation_errors': normalized_errors,
            'chunk_count': info.get('chunk_count'),
            'header_size': info.get('header_size'),
        }
        if 'payload_size' in info:
            details['payload_size'] = info.get('payload_size')

        container_quality[name] = details
    summary = {
        'jar': str(jar),
        'containers': chunks,
        'container_quality': container_quality,
        'text': text,
        'audio': audio,
        'maps': maps_bundle['maps'],
        'scripts': maps_bundle['scripts'],
        'map_mismatch_summary': maps_bundle.get('map_mismatch_summary', {}),
        'audio_coverage': audio.get('audio_coverage', {}),
        'graphics': graphics,
        'ui': ui,
        'final_table_rows': len(final_table),
        'chapter_mission_matrix_rows': len(chapter_mission_matrix),
        'chapter_matrix_rows': len(chapter_matrix.get('chapters', [])),
        'chapter_matrix_cross_check': chapter_matrix.get('cross_check', {}),
        'linker_conflicts_summary': chapter_matrix.get('linker_conflicts_summary', {}),
    }
    write_json(output / 'summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Full extractor for 240x320-rus-zombie-infection.jar')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    parser.add_argument('--strings-encoding', choices=ENCODING_CHAIN, help='Force encoding for t0 text chunks')
    args = parser.parse_args()
    run_extractor(args.jar, args.output, strings_encoding=args.strings_encoding)


if __name__ == '__main__':
    main()
