from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tools.common import JarProject, ensure_dir, write_json, write_rgba_png
from tools.graphics_decoder import Atlas, parse_atlas


@dataclass
class Palette:
    index: int
    fmt: int
    size: int
    has_alpha: bool


@dataclass
class ImagePayload:
    frame_index: int
    table_chunk: int
    data_chunk: int | None
    data_offset: int | None
    size: int
    raw_path: str | None = None
    png_path: str | None = None
    decode_status: str = 'decoded'


@dataclass
class Frame:
    frame_id: int
    record_type: int
    x: int
    y: int
    width: int
    height: int
    pivot_x: int
    pivot_y: int
    palette_index: int
    palette_binding: str
    image_payload: ImagePayload | None = None


@dataclass
class Region:
    region_id: int
    kind: int
    x: int
    y: int
    extra: int


@dataclass
class Sprite:
    container: str
    chunk: int
    runtime_roles: dict[str, str]
    pixel_format: int
    palettes: list[Palette]
    frames: list[Frame]
    regions: list[Region]
    payloads: list[ImagePayload]
    composition_rules: dict[str, Any]
    metadata_path: str
    manifest_path: str


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


def _build_sprite_model(
    container: str,
    chunk_index: int,
    atlas: Atlas,
    raw_paths: dict[int, str],
    png_paths: dict[int, str],
    metadata_path: str,
    manifest_path: str,
) -> Sprite:
    payloads: list[ImagePayload] = []
    payload_by_frame: dict[int, ImagePayload] = {}
    for frame in atlas.frames:
        data_chunk = (
            atlas.sprite_chunk_indices[frame.index]
            if frame.index < len(atlas.sprite_chunk_indices)
            else None
        )
        data_offset = (
            atlas.sprite_chunk_offsets[frame.index]
            if frame.index < len(atlas.sprite_chunk_offsets)
            else None
        )
        payload = ImagePayload(
            frame_index=frame.index,
            table_chunk=chunk_index,
            data_chunk=data_chunk,
            data_offset=data_offset,
            size=atlas.sprite_lengths[frame.index] if frame.index < len(atlas.sprite_lengths) else 0,
            raw_path=raw_paths.get(frame.index),
            png_path=png_paths.get(frame.index),
        )
        payloads.append(payload)
        payload_by_frame[frame.index] = payload

    sprite_frames = [
        Frame(
            frame_id=frame.index,
            record_type=frame.record_type,
            x=frame.x,
            y=frame.y,
            width=frame.width,
            height=frame.height,
            pivot_x=frame.x,
            pivot_y=frame.y,
            palette_index=0,
            palette_binding='runtime-selected',
            image_payload=payload_by_frame.get(frame.index),
        )
        for frame in atlas.frames
    ]
    sprite_regions = [
        Region(region_id=region.index, kind=region.kind, x=region.x, y=region.y, extra=region.extra)
        for region in atlas.regions
    ]
    sprite_palettes = [
        Palette(
            index=palette.index,
            fmt=palette.fmt,
            size=palette.size,
            has_alpha=any((color >> 24) != 0xFF for color in palette.colors),
        )
        for palette in atlas.palettes
    ]
    composition_rules = {
        'reconstruction_source': {
            'atlas_core': 'a.class',
            'container_loader': 'g.class',
            'sprite_instance': 'c.class',
        },
        'image_payload_decode': {
            'payload_layout': 'frame-length table in atlas chunk, raw payload stream may continue in following chunks',
            'codec_switch': {
                '25840': 'RLE_ALPHA_8',
                '10225': 'RLE_8_A',
                '22258': 'RLE_8_B',
                '5632': 'PACKED_4',
                '2048': 'PACKED_3',
                '1024': 'PACKED_2',
                '512': 'PACKED_1',
                '22018': 'INDEX_8',
            },
        },
        'palette_binding': {
            'runtime_mode': 'selected by runtime sprite instance (c.class) via active palette slot in atlas core (a.class)',
            'default_palette': 0,
            'available_palettes': len(atlas.palettes),
            'per_frame_remap': 'optional remap table supported by a.class; metadata exposes palette index stream without mutating source data',
        },
    }
    return Sprite(
        container=container,
        chunk=chunk_index,
        runtime_roles={'atlas_core': 'a.class', 'loader': 'g.class', 'instance': 'c.class'},
        pixel_format=atlas.pixel_format,
        palettes=sprite_palettes,
        frames=sprite_frames,
        regions=sprite_regions,
        payloads=payloads,
        composition_rules=composition_rules,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
    )


def _build_runtime_manifest(sprite: Sprite, atlas: Atlas) -> dict[str, Any]:
    return {
        'runtime_roles': sprite.runtime_roles,
        'composition_rules': sprite.composition_rules,
        'format_reconstruction': {
            'image_payload_blocks': [asdict(payload) for payload in sprite.payloads],
            'frame_table': [asdict(frame) for frame in sprite.frames],
            'region_table': [asdict(region) for region in sprite.regions],
            'palette_table': [asdict(palette) for palette in sprite.palettes],
        },
        'frames': [asdict(frame) for frame in sprite.frames],
        'regions': [asdict(region) for region in sprite.regions],
        'palettes': [asdict(palette) for palette in sprite.palettes],
        'animations': [animation.__dict__ for animation in atlas.animations],
        'anchors': atlas.anchors,
    }


def _build_chunk_trace(pack: str, chunk_index: int, sprite: Sprite, atlas: Atlas) -> dict[str, Any]:
    frame_trace = []
    for frame in sprite.frames:
        payload = frame.image_payload
        frame_trace.append(
            {
                'frame': frame.frame_id,
                'record_type': frame.record_type,
                'size': {'width': frame.width, 'height': frame.height},
                'origin': {'x': frame.x, 'y': frame.y},
                'pivot': {'x': frame.pivot_x, 'y': frame.pivot_y},
                'palette': {
                    'index': frame.palette_index,
                    'binding': frame.palette_binding,
                },
                'payload': asdict(payload) if payload is not None else None,
            }
        )
    palette_trace = [asdict(palette) for palette in sprite.palettes]
    return {
        'pack': pack,
        'chunk': chunk_index,
        'pixel_format': atlas.pixel_format,
        'frame_count': len(sprite.frames),
        'palette_count': len(sprite.palettes),
        'region_count': len(sprite.regions),
        'frame_trace': frame_trace,
        'palette_trace': palette_trace,
        'region_trace': [asdict(region) for region in sprite.regions],
    }


def _candidate_external_chunks(container_payloads: list[bytes], table_chunk_index: int) -> list[tuple[int, bytes]]:
    candidates: list[tuple[int, bytes]] = []
    for idx in range(table_chunk_index + 1, len(container_payloads)):
        payload = container_payloads[idx]
        if payload:
            candidates.append((idx, payload))
    return candidates


def _hypothesis_id(pack_name: str, chunk_index: int) -> str:
    return f'HYP-{pack_name}-{chunk_index:02d}-01'


def _codec_path(pixel_format: int) -> str:
    mapping = {
        25840: 'RLE_ALPHA_8',
        10225: 'RLE_8_A',
        22258: 'RLE_8_B',
        5632: 'PACKED_4',
        2048: 'PACKED_3',
        1024: 'PACKED_2',
        512: 'PACKED_1',
        22018: 'INDEX_8',
    }
    return mapping.get(pixel_format, f'UNKNOWN_{pixel_format}')


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


def _render_frame_with_diagnostics(atlas: Atlas, frame_index: int, raw_block: bytes) -> tuple[int, int, list[int], str, dict[str, Any]]:
    frame = atlas.frames[frame_index]
    width = max(1, frame.width)
    height = max(1, frame.height)
    codec_path = _codec_path(atlas.pixel_format)
    decode_status = 'decoded'

    decoded = atlas.rgba_for_frame(frame_index, 0)
    if decoded is not None:
        width, height, rgba = decoded
    else:
        rgba = []

    raw_size = len(raw_block)
    initial_alpha = _alpha_stats(rgba)
    diagnostics: dict[str, Any] = {
        'raw_payload_size': raw_size,
        'codec_path': codec_path,
        'alpha': initial_alpha,
    }

    alpha_failed = decoded is None or (bool(rgba) and initial_alpha['non_zero'] == 0)
    if raw_size > 0 and alpha_failed:
        indices = atlas.decode_frame_indices(frame_index)
        rgba = _opaque_grayscale_fallback(width, height, indices, raw_block)
        decode_status = 'degraded_decode'
        diagnostics['fallback_reason'] = 'raw_non_empty_alpha_unusable'
        diagnostics['alpha'] = _alpha_stats(rgba)
    elif decoded is None:
        decode_status = 'failed_decode'

    return width, height, rgba, decode_status, diagnostics


def decode_graphics(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()

    sprites_dir = output / 'extracted' / 'sprites'
    extracted_images_dir = output / 'extracted' / 'images'
    extracted_meta_dir = output / 'extracted' / 'meta'
    ensure_dir(sprites_dir)
    ensure_dir(extracted_images_dir)
    ensure_dir(output / 'extracted' / 'tiles')
    ensure_dir(extracted_meta_dir)

    result: dict[str, Any] = {'containers': {}, 'images': []}
    graphics_manifest: dict[str, Any] = {'sprites': [], 'trace': []}
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

            hypothesis_id = _hypothesis_id(name, chunk_index)
            pack_dir = sprites_dir / name / f'chunk_{chunk_index:02d}'
            ensure_dir(pack_dir)

            metadata = atlas.to_metadata()
            exported_frames = []
            png_paths: dict[int, str] = {}
            raw_paths: dict[int, str] = {}

            for frame in atlas.frames:
                raw_block_path = extracted_images_dir / name / f'chunk_{chunk_index:02d}' / f'frame_{frame.index:03d}.bin'
                ensure_dir(raw_block_path.parent)
                frame_offset = atlas.sprite_data_offsets[frame.index] if frame.index < len(atlas.sprite_data_offsets) else None
                frame_size = atlas.sprite_lengths[frame.index] if frame.index < len(atlas.sprite_lengths) else 0
                if frame_offset is not None and frame_size > 0 and frame_offset + frame_size <= len(atlas.sprite_data):
                    raw_block = atlas.sprite_data[frame_offset:frame_offset + frame_size]
                else:
                    raw_block = b''
                raw_block_path.write_bytes(raw_block)
                raw_paths[frame.index] = str(raw_block_path.relative_to(output))
                width, height, rgba, decode_status, diagnostics = _render_frame_with_diagnostics(atlas, frame.index, raw_block)

                png_path = extracted_images_dir / name / f'chunk_{chunk_index:02d}' / f'frame_{frame.index:03d}.png'
                write_rgba_png(png_path, width, height, rgba)
                rel = str(png_path.relative_to(output))
                png_paths[frame.index] = rel
                frame_export = {
                    'container': name,
                    'chunk': chunk_index,
                    'frame': frame.index,
                    'raw_payload': raw_paths[frame.index],
                    'path': rel,
                    'width': width,
                    'height': height,
                    'decode_status': decode_status,
                    'diagnostics': diagnostics,
                }
                exported_frames.append(frame_export)
                result['images'].append(frame_export)

            metadata['exported_frames'] = exported_frames
            metadata['palette_previews'] = _export_palette_previews(output, atlas, f'{name}_chunk{chunk_index:02d}')
            metadata['tile_preview'] = _export_frame_grid(output, atlas, exported_frames, f'{name}_chunk{chunk_index:02d}')
            metadata['hypothesis_id'] = hypothesis_id

            metadata_path = pack_dir / 'metadata.json'
            write_json(metadata_path, metadata)

            sprite = _build_sprite_model(
                container=name,
                chunk_index=chunk_index,
                atlas=atlas,
                raw_paths=raw_paths,
                png_paths=png_paths,
                metadata_path=str(metadata_path.relative_to(output)),
                manifest_path=str((pack_dir / 'manifest.json').relative_to(output)),
            )
            for payload in sprite.payloads:
                matching = next(
                    (item for item in exported_frames if item['frame'] == payload.frame_index),
                    None,
                )
                if matching is not None:
                    payload.decode_status = matching.get('decode_status', 'decoded')
                else:
                    payload.decode_status = 'failed_decode'
            manifest = _build_runtime_manifest(sprite, atlas)
            manifest_path = pack_dir / 'manifest.json'
            write_json(manifest_path, manifest)

            image_chunk_metadata_path = extracted_images_dir / name / f'chunk_{chunk_index:02d}' / 'frames.json'
            write_json(
                image_chunk_metadata_path,
                {
                    'pack': name,
                    'chunk': chunk_index,
                    'hypothesis_id': hypothesis_id,
                    'pixel_format': atlas.pixel_format,
                    'frames': exported_frames,
                    'payloads': [asdict(payload) for payload in sprite.payloads],
                    'palettes': [asdict(palette) for palette in sprite.palettes],
                },
            )
            container_manifest['chunks'].append({
                'chunk': chunk_index,
                'hypothesis_id': hypothesis_id,
                'metadata': str(metadata_path.relative_to(output)),
                'manifest': str(manifest_path.relative_to(output)),
                'images_metadata': str(image_chunk_metadata_path.relative_to(output)),
                'decoded_frame_count': len(exported_frames),
            })
            graphics_manifest['sprites'].append(
                {
                    'pack': name,
                    'chunk': chunk_index,
                    'hypothesis_id': hypothesis_id,
                    'sprite_manifest': str(manifest_path.relative_to(output)),
                    'sprite_metadata': str(metadata_path.relative_to(output)),
                    'frame_links': [
                        {
                            'frame': payload.frame_index,
                            'raw_payload': payload.raw_path,
                            'png': payload.png_path,
                            'data_chunk': payload.data_chunk,
                            'data_offset': payload.data_offset,
                        }
                        for payload in sprite.payloads
                    ],
                }
            )
            trace = _build_chunk_trace(name, chunk_index, sprite, atlas)
            trace['hypothesis_id'] = hypothesis_id
            graphics_manifest['trace'].append(trace)

        if container_manifest['chunks']:
            result['containers'][name] = container_manifest

    write_json(extracted_images_dir / 'index.json', result)
    write_json(extracted_meta_dir / 'graphics_manifest.json', graphics_manifest)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode graphics packs (m3_0, m4_0, m7, m11_0, m11_1)')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_graphics(args.jar, args.output)


if __name__ == '__main__':
    main()
