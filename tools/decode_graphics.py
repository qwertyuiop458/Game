from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from tools.common import JarProject, ensure_dir, write_json, write_rgba_png
from tools.graphics_decoder import Atlas, parse_atlas


def _export_palette_previews(output: Path, atlas: Atlas, pack_name: str) -> list[str]:
    previews: list[str] = []
    if not atlas.palettes:
        return previews

    cols = min(atlas.palette_size, 16)
    rows = (atlas.palette_size + cols - 1) // cols
    for palette in atlas.palettes[: min(4, len(atlas.palettes))]:
        rgba = list(palette.colors) + [0] * (cols * rows - len(palette.colors))
        pal_path = output / 'extracted' / 'images' / pack_name / f'palette_{palette.index:02d}.png'
        write_rgba_png(pal_path, cols, rows, rgba)
        previews.append(str(pal_path.relative_to(output)))
    return previews


def _export_frame_grid(output: Path, atlas: Atlas, frame_exports: list[dict[str, Any]], pack_name: str) -> str | None:
    if not frame_exports:
        return None
    atlas_frames = frame_exports[: min(64, len(frame_exports))]
    tile_w = max(item['width'] for item in atlas_frames)
    tile_h = max(item['height'] for item in atlas_frames)
    cols = 8
    rows = (len(atlas_frames) + cols - 1) // cols
    canvas = [0] * (cols * tile_w * rows * tile_h)

    def paste(px: list[int], fw: int, fh: int, dx: int, dy: int) -> None:
        if len(px) < fw * fh:
            px = px + [0] * (fw * fh - len(px))
        for yy in range(fh):
            for xx in range(fw):
                canvas[(dy + yy) * (cols * tile_w) + (dx + xx)] = px[yy * fw + xx]

    for idx, item in enumerate(atlas_frames):
        frame_index = item.get('frame_index', item.get('frame'))
        if frame_index is None:
            continue
        decoded = atlas.rgba_for_frame(frame_index, 0)
        if decoded is None:
            continue
        fw, fh, rgba = decoded
        paste(rgba, fw, fh, (idx % cols) * tile_w, (idx // cols) * tile_h)

    tile_path = output / 'extracted' / 'tiles' / f'{pack_name}_atlas_preview.png'
    write_rgba_png(tile_path, cols * tile_w, rows * tile_h, canvas)
    return str(tile_path.relative_to(output))


def _build_runtime_manifest(atlas: Atlas, png_paths: dict[int, str]) -> dict[str, Any]:
    frames = []
    for frame in atlas.frames:
        frames.append({
            'frame_id': frame.index,
            'x': frame.x,
            'y': frame.y,
            'width': frame.width,
            'height': frame.height,
            'pivot': {'x': frame.x, 'y': frame.y},
            'palette_index': 0,
            'palette_format': atlas.palette_format,
            'palette_size': atlas.palette_size,
            'source_chunk_index': (
                atlas.sprite_chunk_indices[frame.index]
                if frame.index < len(atlas.sprite_chunk_indices)
                else None
            ),
            'image': png_paths.get(frame.index),
        })

    return {
        'runtime_roles': {
            'atlas_core': 'a.class',
            'loader': 'g.class',
            'instance': 'c.class',
        },
        'palette_links': [
            {'palette_id': palette.index, 'format': palette.fmt, 'size': palette.size}
            for palette in atlas.palettes
        ],
        'frames': frames,
        'regions': [region.__dict__ for region in atlas.regions],
        'animations': [animation.__dict__ for animation in atlas.animations],
        'anchors': atlas.anchors,
    }


def _candidate_external_chunks(container_payloads: list[bytes], table_chunk_index: int) -> list[tuple[int, bytes]]:
    candidates: list[tuple[int, bytes]] = []
    for idx in range(table_chunk_index + 1, len(container_payloads)):
        payload = container_payloads[idx]
        if payload:
            candidates.append((idx, payload))
    return candidates


def decode_graphics(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()

    sprites_dir = output / 'extracted' / 'sprites'
    decoded_dir = output / 'images' / 'decoded'
    ensure_dir(sprites_dir)
    ensure_dir(decoded_dir)
    ensure_dir(output / 'extracted' / 'tiles')

    result: dict[str, Any] = {'containers': {}, 'images': []}
    for name in ('m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1'):
        container = project.containers.get(name)
        if not container or not container.payloads:
            continue

        container_manifest: dict[str, Any] = {'chunks': []}
        for chunk_index, payload in enumerate(container.payloads):
            if not payload:
                continue
            try:
                atlas = parse_atlas(
                    name,
                    payload,
                    chunk_index=chunk_index,
                    external_chunks=_candidate_external_chunks(container.payloads, chunk_index),
                )
            except (IndexError, ValueError):
                continue
            if not atlas.frames or not atlas.palettes:
                continue

            pack_dir = sprites_dir / name / f'chunk_{chunk_index:02d}'
            ensure_dir(pack_dir)

            metadata = atlas.to_metadata()
            exported_frames = []
            png_paths: dict[int, str] = {}

            for frame in atlas.frames:
                decoded = atlas.rgba_for_frame(frame.index, 0)
                if decoded is None:
                    continue
                width, height, rgba = decoded

                png_path = decoded_dir / f'{name}_chunk{chunk_index:02d}_frame{frame.index:03d}.png'
                write_rgba_png(png_path, width, height, rgba)
                rel = str(png_path.relative_to(output))
                png_paths[frame.index] = rel
                frame_export = {
                    'container': name,
                    'chunk': chunk_index,
                    'frame': frame.index,
                    'path': rel,
                    'width': width,
                    'height': height,
                }
                exported_frames.append(frame_export)
                result['images'].append(frame_export)

            metadata['exported_frames'] = exported_frames
            metadata['palette_previews'] = _export_palette_previews(output, atlas, f'{name}_chunk{chunk_index:02d}')
            metadata['tile_preview'] = _export_frame_grid(output, atlas, exported_frames, f'{name}_chunk{chunk_index:02d}')

            metadata_path = pack_dir / 'metadata.json'
            write_json(metadata_path, metadata)

            manifest = _build_runtime_manifest(atlas, png_paths)
            manifest_path = pack_dir / 'manifest.json'
            write_json(manifest_path, manifest)
            container_manifest['chunks'].append({
                'chunk': chunk_index,
                'metadata': str(metadata_path.relative_to(output)),
                'manifest': str(manifest_path.relative_to(output)),
                'decoded_frame_count': len(exported_frames),
            })

        if container_manifest['chunks']:
            result['containers'][name] = container_manifest

    write_json(decoded_dir / 'index.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode graphics packs (m3_0, m4_0, m7, m11_0, m11_1)')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_graphics(args.jar, args.output)


if __name__ == '__main__':
    main()
