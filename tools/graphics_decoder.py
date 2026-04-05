from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.common import s16le, u16le, u32le

FMT_RLE_ALPHA_8 = 25840
FMT_RLE_8_A = 10225
FMT_RLE_8_B = 22258
FMT_PACKED_4 = 5632
FMT_PACKED_3 = 2048
FMT_PACKED_2 = 1024
FMT_PACKED_1 = 512
FMT_INDEX_8 = 22018

PAL_FMT_ARGB8888 = -30584 & 0xFFFF
PAL_FMT_RGB4444 = 17476
PAL_FMT_RGB565_ALPHA_KEY = 25861

KNOWN_PALETTE_FORMATS = {PAL_FMT_ARGB8888, PAL_FMT_RGB4444, PAL_FMT_RGB565_ALPHA_KEY}


@dataclass
class Palette:
    index: int
    fmt: int
    size: int
    colors: list[int]


@dataclass
class Frame:
    index: int
    record_type: int
    x: int
    y: int
    width: int
    height: int
    direct_color: int | None = None


@dataclass
class Region:
    index: int
    kind: int
    x: int
    y: int
    extra: int


@dataclass
class Animation:
    index: int
    kind: int
    offset: int
    extra_count: int = 0
    extra_offset: int | None = None


def rgba_from_rgb4444(word: int) -> int:
    a = ((word >> 12) & 0xF) * 17
    r = ((word >> 8) & 0xF) * 17
    g = ((word >> 4) & 0xF) * 17
    b = (word & 0xF) * 17
    return (a << 24) | (r << 16) | (g << 8) | b


def rgba_from_rgb565_alpha_key(word: int, alpha_key: int = 0xF81F) -> int:
    if word == alpha_key:
        return 0
    r = ((word >> 11) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x3F) * 255 // 63
    b = (word & 0x1F) * 255 // 31
    return 0xFF000000 | (r << 16) | (g << 8) | b


def decode_palette_entries(blob: bytes, fmt: int, size: int, cursor: int = 0) -> tuple[list[int], int, bool]:
    colors: list[int] = []
    has_alpha = False
    for _ in range(size):
        if fmt == PAL_FMT_ARGB8888:
            color = u32le(blob, cursor)
            cursor += 4
            has_alpha = has_alpha or (color >> 24) != 0xFF
        elif fmt == PAL_FMT_RGB4444:
            color = rgba_from_rgb4444(u16le(blob, cursor))
            cursor += 2
            has_alpha = has_alpha or (color >> 24) != 0xFF
        elif fmt == PAL_FMT_RGB565_ALPHA_KEY:
            color = rgba_from_rgb565_alpha_key(u16le(blob, cursor))
            cursor += 2
            has_alpha = has_alpha or color == 0
        else:
            raise ValueError(f'Unsupported palette format: {fmt}')
        colors.append(color)
    return colors, cursor, has_alpha


@dataclass
class Atlas:
    name: str
    flags: int
    frames: list[Frame]
    regions: list[Region]
    animations: list[Animation]
    anchors: list[dict[str, int]]
    extra_quads: list[list[int]]
    palettes: list[Palette]
    palette_format: int
    palette_size: int
    pixel_format: int
    sprite_data_offsets: list[int]
    sprite_data: bytes
    has_alpha: bool

    @property
    def frame_count(self) -> int:
        return len(self.frames)

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
            bit_mask = 1
            shift = 0
            remaining = self.palette_size - 1
            while remaining:
                remaining >>= 1
                bit_mask <<= 1
                shift += 1
            mask = bit_mask - 1
            while len(out) < total and cursor < len(data):
                control = data[cursor]
                cursor += 1
                color_index = control & mask
                run = control >> shift
                out.extend([color_index] * (run if run > 0 else 1))
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

        palette = self.palettes[min(palette_index, len(self.palettes) - 1)].colors if self.palettes else [0xFF000000]
        rgba = [palette[index % len(palette)] for index in indices]
        return width, height, rgba

    def to_metadata(self) -> dict[str, Any]:
        return {
            'atlas_name': self.name,
            'atlas_flags': self.flags,
            'frame_count': len(self.frames),
            'palette_count': len(self.palettes),
            'palette_size': self.palette_size,
            'palette_format': self.palette_format,
            'pixel_format': self.pixel_format,
            'has_alpha': self.has_alpha,
            'region_count': len(self.regions),
            'animation_count': len(self.animations),
            'anchor_count': len(self.anchors),
            'extra_quad_count': len(self.extra_quads),
            'frames': [frame.__dict__ for frame in self.frames],
            'regions': [region.__dict__ for region in self.regions],
            'animations': [animation.__dict__ for animation in self.animations],
            'anchors': self.anchors,
            'extra_quads': self.extra_quads,
        }


def _read_u8(data: bytes, cursor: int) -> tuple[int, int]:
    return data[cursor], cursor + 1


def _read_u16(data: bytes, cursor: int) -> tuple[int, int]:
    return u16le(data, cursor), cursor + 2


def parse_atlas(name: str, chunk0: bytes) -> Atlas:
    data = chunk0
    cursor = 2  # static marker/unused in current assets
    flags = u32le(data, cursor)
    cursor += 4
    frame_count, cursor = _read_u16(data, cursor)

    frames: list[Frame] = []
    for index in range(frame_count):
        record_type = data[cursor]
        cursor += 1
        if record_type in (0xFF, 0xFE):
            direct_color = u32le(data, cursor)
            cursor += 4
            width = data[cursor]
            cursor += 1
            height = data[cursor]
            cursor += 1
            frames.append(Frame(index=index, record_type=record_type, x=0, y=0, width=width, height=height, direct_color=direct_color))
        else:
            x = s16le(data, cursor)
            cursor += 2
            y = s16le(data, cursor)
            cursor += 2
            width = u16le(data, cursor)
            cursor += 2
            height = u16le(data, cursor)
            cursor += 2
            frames.append(Frame(index=index, record_type=record_type, x=x, y=y, width=width, height=height))

    region_count, cursor = _read_u16(data, cursor)
    regions: list[Region] = []
    for idx in range(region_count):
        kind, cursor = _read_u8(data, cursor)
        x, cursor = _read_u16(data, cursor)
        y, cursor = _read_u16(data, cursor)
        extra, cursor = _read_u8(data, cursor)
        regions.append(Region(index=idx, kind=kind, x=x, y=y, extra=extra))

    extra_quads: list[list[int]] = []
    if flags & 0x8000:
        quad_count, cursor = _read_u16(data, cursor)
        for _ in range(quad_count):
            extra_quads.append(list(data[cursor:cursor + 4]))
            cursor += 4

    animation_count, cursor = _read_u16(data, cursor)
    animations: list[Animation] = []
    running_extra = 0
    for idx in range(animation_count):
        kind = data[cursor]
        cursor += 1
        offset = u16le(data, cursor)
        cursor += 2
        animation = Animation(index=idx, kind=kind, offset=offset)
        if flags & 0x8000:
            animation.extra_count = data[cursor]
            cursor += 1
            if animation.extra_count > 0:
                animation.extra_offset = running_extra
                running_extra += animation.extra_count
        animations.append(animation)

    anchor_count, cursor = _read_u16(data, cursor)
    anchors: list[dict[str, int]] = []
    for _ in range(anchor_count):
        anchors.append({
            'a': data[cursor],
            'b': data[cursor + 1],
            'x': u16le(data, cursor + 2),
            'y': u16le(data, cursor + 4),
            'extra': data[cursor + 6],
        })
        cursor += 7

    aligned = cursor
    for probe in range(cursor, min(len(data) - 4, cursor + 4096)):
        palette_format = u16le(data, probe)
        palette_count = data[probe + 2]
        palette_size = data[probe + 3] or 256
        if palette_format in KNOWN_PALETTE_FORMATS and 1 <= palette_count <= 16 and 2 <= palette_size <= 256:
            aligned = probe
            break
    cursor = aligned

    palette_format, cursor = _read_u16(data, cursor)
    palette_count, cursor = _read_u8(data, cursor)
    palette_size, cursor = _read_u8(data, cursor)
    if palette_size == 0:
        palette_size = 256

    palettes: list[Palette] = []
    has_alpha = False
    for palette_index in range(palette_count):
        colors, cursor, palette_alpha = decode_palette_entries(data, palette_format, palette_size, cursor)
        has_alpha = has_alpha or palette_alpha
        palettes.append(Palette(index=palette_index, fmt=palette_format, size=palette_size, colors=colors))

    pixel_format, cursor = _read_u16(data, cursor)

    sprite_data_offsets: list[int] = []
    sprite_data = b''
    if frame_count > 0:
        lengths = []
        scan = cursor
        total = 0
        for _ in range(frame_count):
            size = u16le(data, scan)
            scan += 2
            sprite_data_offsets.append(total)
            total += size
            lengths.append(size)
        sprite_buf = bytearray(total)
        for frame_index, size in enumerate(lengths):
            chunk = data[cursor:cursor + size]
            cursor += size
            start = sprite_data_offsets[frame_index]
            sprite_buf[start:start + size] = chunk
        sprite_data = bytes(sprite_buf)

    return Atlas(
        name=name,
        flags=flags,
        frames=frames,
        regions=regions,
        animations=animations,
        anchors=anchors,
        extra_quads=extra_quads,
        palettes=palettes,
        palette_format=palette_format,
        palette_size=palette_size,
        pixel_format=pixel_format,
        sprite_data_offsets=sprite_data_offsets,
        sprite_data=sprite_data,
        has_alpha=has_alpha,
    )
