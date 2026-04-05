from __future__ import annotations

import argparse
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json
from tools.decode_audio_m13 import decode_audio
from tools.decode_graphics import decode_graphics
from tools.decode_maps import build_final_table, decode_maps
from tools.decode_text_t0 import ENCODING_CHAIN, decode_text
from tools.linker import build_chapter_matrix
from tools.parse_packs import parse_packs


def export_ui(project: JarProject, output: Path) -> dict:
    ui_dir = output / 'extracted' / 'ui'
    ensure_dir(ui_dir)
    result = {}
    icon = project.raw_entries.get('icon.png')
    if icon:
        path = ui_dir / 'icon.png'
        path.write_bytes(icon)
        result['icon.png'] = str(path.relative_to(output))
    data_igp = project.raw_entries.get('dataIGP')
    if data_igp:
        path = ui_dir / 'dataIGP'
        path.write_bytes(data_igp)
        result['dataIGP'] = str(path.relative_to(output))
    write_json(ui_dir / 'index.json', result)
    return result


def run_extractor(jar: Path, output: Path, strings_encoding: str | None = None) -> dict:
    project = JarProject(jar, output)
    project.load()
    ensure_dir(output)
    chunks = parse_packs(jar, output)
    text = decode_text(jar, output, strings_encoding=strings_encoding)
    audio = decode_audio(jar, output)
    maps_bundle = decode_maps(jar, output)
    graphics = decode_graphics(jar, output)
    ui = export_ui(project, output)
    final_table = build_final_table(project, output, maps_bundle['maps'], maps_bundle['scripts'], audio, text)
    chapter_matrix = build_chapter_matrix(jar, output)
    container_quality = {
        name: {
            'header_mode': info.get('header_mode'),
            'validation': info.get('validation', 'errors'),
        }
        for name, info in chunks.items()
    }
    summary = {
        'jar': str(jar),
        'containers': chunks,
        'container_quality': container_quality,
        'text': text,
        'audio': audio,
        'maps': maps_bundle['maps'],
        'scripts': maps_bundle['scripts'],
        'graphics': graphics,
        'ui': ui,
        'final_table_rows': len(final_table),
        'chapter_matrix_rows': len(chapter_matrix.get('chapters', [])),
        'chapter_matrix_cross_check': chapter_matrix.get('cross_check', {}),
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
