import unittest
from types import SimpleNamespace
from hashlib import sha256
from pathlib import Path

import pytest
from tools.common import JarProject, u16le
from tools.graphics_decoder import (
    PAL_FMT_ARGB8888,
    PAL_FMT_RGB4444,
    PAL_FMT_RGB565_ALPHA_KEY,
    decode_palette_entries,
    parse_atlas,
)
from tools.decode_graphics import _render_frame_with_diagnostics


@pytest.mark.graphics
@pytest.mark.extractor
class TestPaletteDecodingOnKnownChunks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = JarProject(Path('240x320-rus-zombie-infection.jar'), Path('.'))
        cls.project.load()

    def _find_palette_block(self, data: bytes, fmt: int) -> tuple[int, int, int]:
        for i in range(0, len(data) - 4):
            palette_format = u16le(data, i)
            palette_count = data[i + 2]
            palette_size = data[i + 3] or 256
            if palette_format == fmt and 1 <= palette_count <= 16 and 2 <= palette_size <= 256:
                return i, palette_count, palette_size
        raise AssertionError(f'Palette format {fmt} was not found in test chunk')

    def test_argb8888_palette_decode_from_m7(self):
        data = self.project.containers['m7'].payloads[0]
        offset, palette_count, palette_size = self._find_palette_block(data, PAL_FMT_ARGB8888)
        self.assertGreaterEqual(palette_count, 1)
        colors, _, has_alpha = decode_palette_entries(data, PAL_FMT_ARGB8888, 4, offset + 4)
        self.assertEqual(colors, [0xFF000000, 0x00FF00FF, 0xFF0C423D, 0xFF024135])
        self.assertTrue(has_alpha)
        self.assertGreaterEqual(palette_size, 4)

    def test_rgb4444_palette_decode_from_m3_0(self):
        data = self.project.containers['m3_0'].payloads[0]
        offset, _, _ = self._find_palette_block(data, PAL_FMT_RGB4444)
        colors, _, has_alpha = decode_palette_entries(data, PAL_FMT_RGB4444, 4, offset + 4)
        self.assertEqual(colors, [0xFF00FF, 0xFF000000, 0xFF112222, 0xFF001122])
        self.assertTrue(has_alpha)

    def test_rgb565_alpha_key_palette_decode_from_m2(self):
        data = self.project.containers['m2'].payloads[0]
        offset, _, _ = self._find_palette_block(data, PAL_FMT_RGB565_ALPHA_KEY)
        colors, _, has_alpha = decode_palette_entries(data, PAL_FMT_RGB565_ALPHA_KEY, 4, offset + 4)
        self.assertEqual(colors[:4], [0xFF006118, 0xFF2900CD, 0xFF290441, 0xFF0061D5])
        self.assertFalse(has_alpha)

        keyed_blob = bytes([0x1F, 0xF8, 0x00, 0x00, 0xFF, 0xFF])
        keyed_colors, _, keyed_has_alpha = decode_palette_entries(keyed_blob, PAL_FMT_RGB565_ALPHA_KEY, 3, 0)
        self.assertEqual(keyed_colors[0], 0)
        self.assertEqual(keyed_colors[1], 0xFF000000)
        self.assertEqual(keyed_colors[2], 0xFFFFFFFF)
        self.assertTrue(keyed_has_alpha)


@pytest.mark.graphics
@pytest.mark.extractor
class TestAtlasChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = JarProject(Path('240x320-rus-zombie-infection.jar'), Path('.'))
        cls.project.load()

    def test_chain_tables_exist_for_runtime_packs(self):
        for name in ('m3_0', 'm4_0', 'm11_0', 'm11_1', 'm7'):
            atlas = parse_atlas(name, self.project.containers[name].payloads[0])
            self.assertGreater(atlas.frame_count, 0)
            self.assertGreater(len(atlas.regions), 0)
            self.assertGreater(len(atlas.animations), 0)
            self.assertGreater(len(atlas.palettes), 0)

    def test_external_block_mapping_uses_following_chunks(self):
        # synthetic atlas: one 2x2 frame, palette(ARGB8888, 2 colors), pixel format INDEX_8, sprite size=4
        header = bytearray()
        header.extend(b'\x00\x00')  # marker
        header.extend((0).to_bytes(4, 'little'))  # flags
        header.extend((1).to_bytes(2, 'little'))  # frame_count
        header.extend(bytes([0]))  # record_type
        header.extend((0).to_bytes(2, 'little'))  # x
        header.extend((0).to_bytes(2, 'little'))  # y
        header.extend((2).to_bytes(2, 'little'))  # width
        header.extend((2).to_bytes(2, 'little'))  # height
        header.extend((0).to_bytes(2, 'little'))  # region_count
        header.extend((0).to_bytes(2, 'little'))  # animation_count
        header.extend((0).to_bytes(2, 'little'))  # anchor_count
        header.extend((PAL_FMT_ARGB8888).to_bytes(2, 'little'))
        header.extend(bytes([1, 2]))  # palette_count, palette_size
        header.extend((0xFF000000).to_bytes(4, 'little'))
        header.extend((0xFFFFFFFF).to_bytes(4, 'little'))
        header.extend((22018).to_bytes(2, 'little'))  # FMT_INDEX_8
        header.extend((4).to_bytes(2, 'little'))  # sprite size table entry

        atlas = parse_atlas('synthetic', bytes(header), chunk_index=1, external_chunks=[(2, b'\x00\x01\x01\x00')])
        decoded = atlas.rgba_for_frame(0, 0)
        self.assertIsNotNone(decoded)
        width, height, rgba = decoded
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(rgba, [0xFF000000, 0xFFFFFFFF, 0xFFFFFFFF, 0xFF000000])
        self.assertEqual(atlas.sprite_chunk_indices[0], 2)

    def test_packed2_indices_dimensions_and_hash_are_stable(self):
        header = bytearray()
        header.extend(b'\x00\x00')
        header.extend((0).to_bytes(4, 'little'))
        header.extend((1).to_bytes(2, 'little'))
        header.extend(bytes([0]))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((4).to_bytes(2, 'little'))
        header.extend((2).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((PAL_FMT_RGB4444).to_bytes(2, 'little'))
        header.extend(bytes([1, 4]))
        for word in (0xF000, 0xFF00, 0xF0F0, 0xF00F):
            header.extend(word.to_bytes(2, 'little'))
        header.extend((1024).to_bytes(2, 'little'))  # FMT_PACKED_2
        header.extend((2).to_bytes(2, 'little'))
        header.extend(bytes([0x1B, 0xE4]))  # indices: 0,1,2,3,3,2,1,0

        atlas = parse_atlas('synthetic-packed2', bytes(header))
        self.assertEqual((atlas.frames[0].width, atlas.frames[0].height), (4, 2))
        self.assertEqual(atlas.decode_frame_indices(0), [0, 1, 2, 3, 3, 2, 1, 0])
        width, height, rgba = atlas.rgba_for_frame(0, 0)
        self.assertEqual((width, height), (4, 2))
        packed = b''.join((px & 0xFFFFFFFF).to_bytes(4, 'little') for px in rgba)
        self.assertEqual(sha256(packed).hexdigest(), '3277a72649632e13772770d0473b7109849881aacdaac055a8ecd6b53950ae1e')

    def test_index8_external_palette_values_and_hash_are_stable(self):
        header = bytearray()
        header.extend(b'\x00\x00')
        header.extend((0).to_bytes(4, 'little'))
        header.extend((1).to_bytes(2, 'little'))
        header.extend(bytes([0]))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((3).to_bytes(2, 'little'))
        header.extend((2).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((0).to_bytes(2, 'little'))
        header.extend((PAL_FMT_RGB565_ALPHA_KEY).to_bytes(2, 'little'))
        header.extend(bytes([1, 3]))
        for word in (0xF81F, 0x0000, 0xFFFF):
            header.extend(word.to_bytes(2, 'little'))
        header.extend((22018).to_bytes(2, 'little'))  # FMT_INDEX_8
        header.extend((6).to_bytes(2, 'little'))

        atlas = parse_atlas(
            'synthetic-index8-external',
            bytes(header),
            chunk_index=1,
            external_chunks=[(2, b'\x00\x01\x02\x02\x01\x00')],
        )
        self.assertEqual(atlas.palettes[0].colors, [0, 0xFF000000, 0xFFFFFFFF])
        self.assertEqual(atlas.decode_frame_indices(0), [0, 1, 2, 2, 1, 0])
        width, height, rgba = atlas.rgba_for_frame(0, 0)
        self.assertEqual((width, height), (3, 2))
        packed = b''.join((px & 0xFFFFFFFF).to_bytes(4, 'little') for px in rgba)
        self.assertEqual(sha256(packed).hexdigest(), 'e4244de48ef27e59449f33ed15ac575b6e0e0ab62d72e1330e31ff8905aa2be4')


@pytest.mark.graphics
@pytest.mark.extractor
class TestDecodeDiagnosticsFallback(unittest.TestCase):
    class _FakeAtlas:
        def __init__(self, decoded, indices):
            self.frames = [SimpleNamespace(width=2, height=2)]
            self.pixel_format = 22018
            self._decoded = decoded
            self._indices = indices

        def rgba_for_frame(self, frame_index: int, palette_index: int):
            return self._decoded

        def decode_frame_indices(self, frame_index: int):
            return self._indices

    def test_non_empty_raw_uses_degraded_fallback_for_fully_transparent_decode(self):
        atlas = self._FakeAtlas(decoded=(2, 2, [0x00000000, 0x00000000, 0x00000000, 0x00000000]), indices=[1, 2, 3, 4])
        width, height, rgba, status, diagnostics = _render_frame_with_diagnostics(atlas, 0, b'\x01\x02\x03\x04')

        self.assertEqual((width, height), (2, 2))
        self.assertEqual(status, 'degraded_decode')
        self.assertGreater(diagnostics['alpha']['non_zero'], 0)
        self.assertTrue(all(((px >> 24) & 0xFF) == 0xFF for px in rgba))

    def test_failed_decode_requires_no_raw_payload(self):
        atlas = self._FakeAtlas(decoded=None, indices=None)
        _, _, rgba, status, diagnostics = _render_frame_with_diagnostics(atlas, 0, b'')

        self.assertEqual(status, 'failed_decode')
        self.assertEqual(diagnostics['raw_payload_size'], 0)
        self.assertEqual(rgba, [])


if __name__ == '__main__':
    unittest.main()
