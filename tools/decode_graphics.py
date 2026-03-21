from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common import JarProject, ensure_dir, s16le, u16le, u32le, write_json, write_rgba_png


FMT_RLE_ALPHA_8 = 25840
FMT_RLE_8_A = 10225
FMT_RLE_8_B = 22258
FMT_PACKED_4 = 5632
FMT_PACKED_3 = 2048
FMT_PACKED_2 = 1024
FMT_PACKED_1 = 512
FMT_INDEX_8 = 22018

PAL_FMT_RGBA8888 = -30584 & 0xFFFF
PAL_FMT_ARGB4444 = 17476
PAL_FMT_RGB565_KEY = 25861


def _read_u8(data: bytes, cursor: int) -> tuple[int, int]:
    return data[cursor], cursor + 1


def _read_u16(data: bytes, cursor: int) -> tuple[int, int]:
    return u16le(data, cursor), cursor + 2


def _read_s16(data: bytes, cursor: int) -> tuple[int, int]:
    return s16le(data, cursor), cursor + 2


def _rgba_from_argb4444(word: int) -> int:
    a = ((word >> 12) & 0xF) * 17
    r = ((word >> 8) & 0xF) * 17
    g = ((word >> 4) & 0xF) * 17
    b = (word & 0xF) * 17
    return (a << 24) | (r << 16) | (g << 8) | b


def _rgba_from_rgb565(word: int) -> int:
    if word == 0xF81F:
        return 0
    r = ((word >> 11) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x3F) * 255 // 63
    b = (word & 0x1F) * 255 // 31
    return 0xFF000000 | (r << 16) | (g << 8) | b


@dataclass
class FrameRecord:
    index: int
    record_type: int
    x: int
    y: int
    width: int
    height: int
    direct_color: int | None = None


class SpritePack:
    def __init__(self, chunk0: bytes, extra_chunks: list[bytes], pack_name: str):
        self.pack_name = pack_name
        self.chunk0 = chunk0
        self.extra_chunks = extra_chunks
        self.flags = 0
        self.frame_count = 0
        self.frames: list[FrameRecord] = []
        self.rect_table: list[dict[str, int]] = []
        self.sequence_table: list[dict[str, int]] = []
        self.anchor_table: list[dict[str, int]] = []
        self.extra_quad_table: list[list[int]] = []
        self.palette_map_len = 0
        self.sprite_data_offsets: list[int] = []
        self.sprite_data: bytes = b''
        self.palette_count = 0
        self.palette_size = 0
        self.palettes: list[list[int]] = []
        self.pixel_format = 0
        self.has_alpha = False
        self._parse()


    def _align_to_palette_section(self, data: bytes, cursor: int) -> int:
        known = {PAL_FMT_RGBA8888, PAL_FMT_ARGB4444, PAL_FMT_RGB565_KEY}
        for probe in range(cursor, min(len(data) - 4, cursor + 4096)):
            pal_fmt = u16le(data, probe)
            pal_count = data[probe + 2]
            pal_size = data[probe + 3] or 256
            if pal_fmt in known and 1 <= pal_count <= 16 and 2 <= pal_size <= 256:
                return probe
        return cursor

    def _parse(self) -> None:
        data = self.chunk0
        cursor = 0
        cursor += 2
        self.flags = u32le(data, cursor)
        cursor += 4
        self.frame_count = u16le(data, cursor)
        cursor += 2

        for index in range(self.frame_count):
            record_type = data[cursor]
            cursor += 1
            if record_type in (0xFF, 0xFE):
                direct_color = u32le(data, cursor)
                cursor += 4
                width = data[cursor]
                cursor += 1
                height = data[cursor]
                cursor += 1
                self.frames.append(FrameRecord(index, record_type, 0, 0, width, height, direct_color))
            else:
                x = s16le(data, cursor)
                cursor += 2
                y = s16le(data, cursor)
                cursor += 2
                width = u16le(data, cursor)
                cursor += 2
                height = u16le(data, cursor)
                cursor += 2
                self.frames.append(FrameRecord(index, record_type, x, y, width, height, None))

        rect_count, cursor = _read_u16(data, cursor)
        for _ in range(rect_count):
            kind, cursor = _read_u8(data, cursor)
            x, cursor = _read_u16(data, cursor)
            y, cursor = _read_u16(data, cursor)
            extra, cursor = _read_u8(data, cursor)
            self.rect_table.append({'kind': kind, 'x': x, 'y': y, 'extra': extra})

        if self.flags & 0x8000:
            quad_count, cursor = _read_u16(data, cursor)
            for _ in range(quad_count):
                quad = list(data[cursor:cursor + 4])
                cursor += 4
                self.extra_quad_table.append(quad)

        sequence_count, cursor = _read_u16(data, cursor)
        running = 0
        for _ in range(sequence_count):
            item = {'kind': data[cursor]}
            cursor += 1
            item['offset'] = u16le(data, cursor)
            cursor += 2
            if self.flags & 0x8000:
                item['extra_count'] = data[cursor]
                cursor += 1
                if item['extra_count'] > 0:
                    item['extra_offset'] = running
                    running += item['extra_count']
            self.sequence_table.append(item)

        anchor_count, cursor = _read_u16(data, cursor)
        for _ in range(anchor_count):
            item = {
                'a': data[cursor],
                'b': data[cursor + 1],
                'x': u16le(data, cursor + 2),
                'y': u16le(data, cursor + 4),
                'extra': data[cursor + 6],
            }
            cursor += 7
            self.anchor_table.append(item)

        cursor = self._align_to_palette_section(data, cursor)
        pal_fmt, cursor = _read_u16(data, cursor)
        self.palette_count, cursor = _read_u8(data, cursor)
        self.palette_size, cursor = _read_u8(data, cursor)
        if self.palette_size == 0:
            self.palette_size = 256

        for _ in range(self.palette_count):
            palette = []
            for __ in range(self.palette_size):
                if pal_fmt == PAL_FMT_RGBA8888:
                    color = u32le(data, cursor)
                    cursor += 4
                    if color & 0xFF000000 != 0xFF000000:
                        self.has_alpha = True
                    palette.append(color)
                elif pal_fmt == PAL_FMT_ARGB4444:
                    color = _rgba_from_argb4444(u16le(data, cursor))
                    cursor += 2
                    if color >> 24 != 0xFF:
                        self.has_alpha = True
                    palette.append(color)
                elif pal_fmt == PAL_FMT_RGB565_KEY:
                    color = _rgba_from_rgb565(u16le(data, cursor))
                    cursor += 2
                    if color == 0:
                        self.has_alpha = True
                    palette.append(color)
                else:
                    raise ValueError(f'Unsupported palette format {pal_fmt} in {self.pack_name}')
            self.palettes.append(palette)

        self.pixel_format, cursor = _read_u16(data, cursor)
        if self.pixel_format == FMT_RLE_ALPHA_8:
            bit_mask = 1
            shift = 0
            remaining = self.palette_size - 1
            while remaining:
                remaining >>= 1
                bit_mask <<= 1
                shift += 1
        else:
            bit_mask = 0
            shift = 0
        self._rle_bit_mask = bit_mask - 1 if bit_mask else 0
        self._rle_shift = shift

        if self.frame_count > 0:
            lengths = []
            scan = cursor
            total = 0
            for _ in range(self.frame_count):
                size = u16le(data, scan)
                scan += 2
                self.sprite_data_offsets.append(total)
                total += size
                lengths.append(size)
            self.sprite_data = bytearray(total)
            for frame_index, size in enumerate(lengths):
                chunk = data[cursor:cursor + size]
                cursor += size
                start = self.sprite_data_offsets[frame_index]
                self.sprite_data[start:start + size] = chunk
        self.sprite_data = bytes(self.sprite_data)

    def decode_frame_indices(self, frame_index: int) -> list[int] | None:
        frame = self.frames[frame_index]
        if frame.record_type in (0xFF, 0xFE):
            return None
        if not self.sprite_data_offsets or frame_index >= len(self.sprite_data_offsets):
            return None
        width = max(1, frame.width)
        height = max(1, frame.height)
        total = width * height
        cursor = self.sprite_data_offsets[frame_index]
        out: list[int] = []
        data = self.sprite_data
        if cursor >= len(data):
            return None

        if self.pixel_format == FMT_RLE_ALPHA_8:
            while len(out) < total and cursor < len(data):
                control = data[cursor]
                cursor += 1
                color_index = control & self._rle_bit_mask
                run = control >> self._rle_shift
                if run <= 0:
                    run = 1
                out.extend([color_index] * run)
        elif self.pixel_format == FMT_RLE_8_A:
            while len(out) < total and cursor < len(data):
                control = data[cursor]
                cursor += 1
                if control > 127:
                    run = control - 128
                    if cursor >= len(data):
                        break
                    value = data[cursor]
                    cursor += 1
                    out.extend([value] * run)
                else:
                    out.append(control)
        elif self.pixel_format == FMT_RLE_8_B:
            while len(out) < total and cursor < len(data):
                control = data[cursor]
                cursor += 1
                if control > 127:
                    run = control - 128
                    for _ in range(run):
                        if cursor >= len(data):
                            break
                        out.append(data[cursor])
                        cursor += 1
                else:
                    if cursor >= len(data):
                        break
                    value = data[cursor]
                    cursor += 1
                    out.extend([value] * control)
        elif self.pixel_format == FMT_PACKED_4:
            while len(out) < total and cursor < len(data):
                value = data[cursor]
                cursor += 1
                out.extend([(value >> 4) & 0xF, value & 0xF])
        elif self.pixel_format == FMT_PACKED_3:
            while len(out) < total and cursor + 2 < len(data):
                b0, b1, b2 = data[cursor], data[cursor + 1], data[cursor + 2]
                cursor += 3
                out.extend([
                    (b0 >> 5) & 0x7,
                    (b0 >> 2) & 0x7,
                    ((b0 << 1) & 0x6) | ((b1 >> 7) & 0x1),
                    (b1 >> 4) & 0x7,
                    (b1 >> 1) & 0x7,
                    ((b1 << 2) & 0x4) | ((b2 >> 6) & 0x3),
                    (b2 >> 3) & 0x7,
                    b2 & 0x7,
                ])
        elif self.pixel_format == FMT_PACKED_2:
            while len(out) < total and cursor < len(data):
                value = data[cursor]
                cursor += 1
                out.extend([(value >> 6) & 0x3, (value >> 4) & 0x3, (value >> 2) & 0x3, value & 0x3])
        elif self.pixel_format == FMT_PACKED_1:
            while len(out) < total and cursor < len(data):
                value = data[cursor]
                cursor += 1
                out.extend([(value >> shift) & 1 for shift in range(7, -1, -1)])
        elif self.pixel_format == FMT_INDEX_8:
            while len(out) < total and cursor < len(data):
                out.append(data[cursor])
                cursor += 1
        else:
            return None
        return out[:total]

    def rgba_for_frame(self, frame_index: int, palette_index: int = 0) -> tuple[int, int, list[int]] | None:
        frame = self.frames[frame_index]
        width = max(1, frame.width)
        height = max(1, frame.height)
        if frame.record_type in (0xFF, 0xFE) and frame.direct_color is not None:
            return width, height, [frame.direct_color] * (width * height)
        indices = self.decode_frame_indices(frame_index)
        if indices is None:
            return None
        palette = self.palettes[min(palette_index, len(self.palettes) - 1)] if self.palettes else [0xFF000000]
        rgba = [palette[index % len(palette)] for index in indices]
        return width, height, rgba

    def metadata(self) -> dict[str, Any]:
        return {
            'pack': self.pack_name,
            'flags': self.flags,
            'frame_count': self.frame_count,
            'palette_count': self.palette_count,
            'palette_size': self.palette_size,
            'pixel_format': self.pixel_format,
            'has_alpha': self.has_alpha,
            'rect_table_count': len(self.rect_table),
            'sequence_table_count': len(self.sequence_table),
            'anchor_table_count': len(self.anchor_table),
            'extra_quad_table_count': len(self.extra_quad_table),
            'frames': [frame.__dict__ for frame in self.frames],
            'rect_table': self.rect_table,
            'sequence_table': self.sequence_table,
            'anchor_table': self.anchor_table,
            'extra_quad_table': self.extra_quad_table,
        }


def decode_graphics(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    images_dir = output / 'extracted' / 'images'
    sprites_dir = output / 'extracted' / 'sprites'
    tiles_dir = output / 'extracted' / 'tiles'
    ensure_dir(images_dir)
    ensure_dir(sprites_dir)
    ensure_dir(tiles_dir)
    result: dict[str, Any] = {'containers': {}}
    for name in ('m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1'):
        container = project.containers.get(name)
        if not container or not container.payloads:
            continue
        pack = SpritePack(container.payloads[0], container.payloads[1:], name)
        pack_dir = sprites_dir / name
        ensure_dir(pack_dir)
        meta = pack.metadata()
        exported_frames = []
        for frame in pack.frames:
            decoded = pack.rgba_for_frame(frame.index, 0)
            if decoded is None:
                continue
            width, height, rgba = decoded
            png_path = pack_dir / f'frame_{frame.index:03d}.png'
            write_rgba_png(png_path, width, height, rgba)
            exported_frames.append({
                'frame_index': frame.index,
                'path': str(png_path.relative_to(output)),
                'width': width,
                'height': height,
            })
        palettes_preview = []
        if pack.palettes:
            cols = min(pack.palette_size, 16)
            rows = (pack.palette_size + cols - 1) // cols
            for palette_index, palette in enumerate(pack.palettes[: min(4, len(pack.palettes))]):
                rgba = list(palette) + [0] * (cols * rows - len(palette))
                pal_path = images_dir / name / f'palette_{palette_index:02d}.png'
                write_rgba_png(pal_path, cols, rows, rgba)
                palettes_preview.append(str(pal_path.relative_to(output)))
        tile_preview_path = None
        if exported_frames:
            atlas_frames = exported_frames[: min(64, len(exported_frames))]
            tile_w = max(item['width'] for item in atlas_frames)
            tile_h = max(item['height'] for item in atlas_frames)
            cols = 8
            rows = (len(atlas_frames) + cols - 1) // cols
            canvas = [0] * (cols * tile_w * rows * tile_h)
            def paste(px: list[int], fw: int, fh: int, dx: int, dy: int) -> None:
                for yy in range(fh):
                    for xx in range(fw):
                        canvas[(dy + yy) * (cols * tile_w) + (dx + xx)] = px[yy * fw + xx]
            for idx, item in enumerate(atlas_frames):
                decoded = pack.rgba_for_frame(item['frame_index'], 0)
                if decoded is None:
                    continue
                fw, fh, rgba = decoded
                paste(rgba, fw, fh, (idx % cols) * tile_w, (idx // cols) * tile_h)
            tile_preview_path = tiles_dir / f'{name}_atlas_preview.png'
            write_rgba_png(tile_preview_path, cols * tile_w, rows * tile_h, canvas)
        meta['exported_frames'] = exported_frames
        meta['palette_previews'] = palettes_preview
        meta['tile_preview'] = str(tile_preview_path.relative_to(output)) if tile_preview_path else None
        write_json(pack_dir / 'metadata.json', meta)
        result['containers'][name] = meta
    write_json(images_dir / 'graphics_index.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode graphics packs (m3_0, m4_0, m7, m11_0, m11_1)')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_graphics(args.jar, args.output)


if __name__ == '__main__':
    main()
