import unittest
from pathlib import Path

from tools.common import JarProject, u16le
from tools.graphics_decoder import (
    PAL_FMT_ARGB8888,
    PAL_FMT_RGB4444,
    PAL_FMT_RGB565_ALPHA_KEY,
    decode_palette_entries,
    parse_atlas,
)


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


if __name__ == '__main__':
    unittest.main()
