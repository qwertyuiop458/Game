from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.decode_graphics import decode_graphics
from tools.graphics_decoder import Animation, Atlas, Frame, Palette, Region

_ALLOWED_DECODE_STATUS = {'decoded', 'degraded_decode', 'failed_decode', 'skipped'}


@pytest.mark.smoke
@pytest.mark.graphics
@pytest.mark.extractor
def test_smoke_frames_json_contract_for_deterministic_decode_statuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    atlas_chunk_00 = Atlas(
        name='m11_1',
        chunk_index=0,
        flags=0,
        frames=[
            Frame(index=0, record_type=0, x=0, y=0, width=1, height=1),
            Frame(index=1, record_type=0, x=0, y=0, width=1, height=1),
            Frame(index=2, record_type=0, x=0, y=0, width=1, height=1),
            Frame(index=3, record_type=0, x=0, y=0, width=1, height=1),
            Frame(index=4, record_type=0, x=0, y=0, width=1, height=1),
        ],
        regions=[Region(index=0, kind=0, x=0, y=0, extra=0)],
        animations=[Animation(index=0, kind=0, offset=0)],
        anchors=[],
        extra_quads=[],
        palettes=[Palette(index=0, fmt=17476, size=2, colors=[0xFF000000, 0xFFFFFFFF])],
        palette_format=17476,
        palette_size=2,
        pixel_format=22018,
        sprite_data_offsets=[0, 1, 2, 0, 0],
        sprite_chunk_indices=[0, 0, 0, -1, 0],
        sprite_chunk_offsets=[0, 1, 2, 3, 4],
        sprite_lengths=[1, 1, 1, 1, 0],
        sprite_data=b'\x10\x20\x30\x40',
        has_alpha=False,
    )
    atlas_chunk_01 = Atlas(
        name='m11_1',
        chunk_index=1,
        flags=0,
        frames=[Frame(index=0, record_type=0, x=0, y=0, width=1, height=1)],
        regions=[Region(index=0, kind=0, x=0, y=0, extra=0)],
        animations=[Animation(index=0, kind=0, offset=0)],
        anchors=[],
        extra_quads=[],
        palettes=[Palette(index=0, fmt=17476, size=2, colors=[0xFF000000, 0xFFFFFFFF])],
        palette_format=17476,
        palette_size=2,
        pixel_format=999,
        sprite_data_offsets=[0],
        sprite_chunk_indices=[1],
        sprite_chunk_offsets=[0],
        sprite_lengths=[1],
        sprite_data=b'\xAA',
        has_alpha=False,
    )

    class FakeJarProject:
        def __init__(self, _jar: Path, _output: Path) -> None:
            self.containers: dict[str, SimpleNamespace] = {}

        def load(self) -> None:
            self.containers = {'m11_1': SimpleNamespace(payloads=[b'\x00', b'\x01'])}

    def fake_parse_atlas(_name: str, _payload: bytes, *, chunk_index: int, external_chunks: list[tuple[int, bytes]]) -> Atlas:
        assert isinstance(external_chunks, list)
        return atlas_chunk_00 if chunk_index == 0 else atlas_chunk_01

    def fake_render_with_diagnostics(
        _atlas: Atlas,
        frame_index: int,
        raw_block: bytes,
    ) -> tuple[int, int, list[int], str, dict[str, object]]:
        base = {
            'raw_payload_size': len(raw_block),
            'codec_path': 'test_codec',
            'alpha': {'min': 255, 'max': 255, 'non_zero': 1 if raw_block else 0},
        }
        if frame_index == 0:
            return 1, 1, [0xFFFFFFFF], 'decoded', base
        if frame_index == 1:
            degraded = dict(base)
            degraded['fallback_reason'] = 'test_fallback'
            return 1, 1, [0xFF7F7F7F], 'degraded_decode', degraded
        if frame_index == 2:
            failed = dict(base)
            failed['alpha'] = {'min': 0, 'max': 0, 'non_zero': 0}
            return 1, 1, [], 'failed_decode', failed
        raise AssertionError(f'unexpected frame_index={frame_index}')

    monkeypatch.setattr('tools.decode_graphics.JarProject', FakeJarProject)
    monkeypatch.setattr('tools.decode_graphics.parse_atlas', fake_parse_atlas)
    monkeypatch.setattr('tools.decode_graphics._render_frame_with_diagnostics', fake_render_with_diagnostics)

    out_dir = tmp_path / 'out'
    decode_graphics(tmp_path / 'fake.jar', out_dir)

    frames_00 = json.loads((out_dir / 'extracted' / 'images' / 'm11_1' / 'chunk_00' / 'frames.json').read_text(encoding='utf-8'))
    frames_01 = json.loads((out_dir / 'extracted' / 'images' / 'm11_1' / 'chunk_01' / 'frames.json').read_text(encoding='utf-8'))

    for payload in (frames_00, frames_01):
        assert {'pack', 'chunk', 'frames', 'skipped_frames', 'payloads', 'palettes', 'pixel_format', 'hypothesis_id'} <= payload.keys()

        frame_indexes = [frame['frame'] for frame in payload['frames']]
        skipped_indexes = [frame['frame'] for frame in payload['skipped_frames']]
        payload_indexes = [entry['frame_index'] for entry in payload['payloads']]

        assert len(frame_indexes) == len(set(frame_indexes))
        assert len(skipped_indexes) == len(set(skipped_indexes))
        assert sorted(frame_indexes + skipped_indexes) == sorted(payload_indexes)

        for frame in payload['frames']:
            assert {'frame', 'path', 'raw_payload', 'decode_status', 'diagnostics', 'width', 'height'} <= frame.keys()
            assert frame['decode_status'] in _ALLOWED_DECODE_STATUS - {'skipped'}

        for skipped in payload['skipped_frames']:
            assert {'frame', 'raw_payload', 'decode_status', 'skipped_reason'} <= skipped.keys()
            assert skipped['decode_status'] in {'skipped', 'failed_decode'}
            assert skipped['skipped_reason']

        for entry in payload['payloads']:
            assert {
                'frame_index',
                'table_chunk',
                'data_chunk',
                'data_offset',
                'size',
                'raw_path',
                'png_path',
                'decode_status',
                'skipped_reason',
            } <= entry.keys()
            assert entry['decode_status'] in _ALLOWED_DECODE_STATUS
            if entry['decode_status'] in {'skipped', 'failed_decode'}:
                assert entry['skipped_reason']

    payload_by_frame_00 = {entry['frame_index']: entry for entry in frames_00['payloads']}
    assert payload_by_frame_00[0]['decode_status'] == 'decoded'
    assert payload_by_frame_00[1]['decode_status'] == 'degraded_decode'
    assert payload_by_frame_00[2]['decode_status'] == 'failed_decode'
    assert payload_by_frame_00[3]['decode_status'] == 'skipped'
    assert payload_by_frame_00[3]['skipped_reason'] == 'missing_data_chunk'
    assert payload_by_frame_00[4]['decode_status'] == 'skipped'
    assert payload_by_frame_00[4]['skipped_reason'] == 'empty_payload'

    payload_by_frame_01 = {entry['frame_index']: entry for entry in frames_01['payloads']}
    assert payload_by_frame_01[0]['decode_status'] == 'skipped'
    assert payload_by_frame_01[0]['skipped_reason'] == 'unsupported_pixel_format'
