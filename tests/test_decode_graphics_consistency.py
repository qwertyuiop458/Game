import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.decode_graphics import decode_graphics
from tools.graphics_decoder import Animation, Atlas, Frame, Palette, Region


@pytest.mark.graphics
@pytest.mark.extractor
def test_decode_graphics_keeps_manifest_and_frames_json_in_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    atlas = Atlas(
        name='m11_1',
        chunk_index=0,
        flags=0,
        frames=[
            Frame(index=0, record_type=0xFE, x=0, y=0, width=1, height=1, direct_color=0xFF00FF00),
            Frame(index=1, record_type=0, x=0, y=0, width=1, height=1),
        ],
        regions=[Region(index=0, kind=0, x=0, y=0, extra=0)],
        animations=[Animation(index=0, kind=0, offset=0)],
        anchors=[],
        extra_quads=[],
        palettes=[Palette(index=0, fmt=17476, size=2, colors=[0xFF000000, 0xFFFFFFFF])],
        palette_format=17476,
        palette_size=2,
        pixel_format=22018,
        sprite_data_offsets=[0, 0],
        sprite_chunk_indices=[0, -1],
        sprite_chunk_offsets=[0, 0],
        sprite_lengths=[0, 1],
        sprite_data=b'',
        has_alpha=False,
    )

    class FakeJarProject:
        def __init__(self, _jar: Path, _output: Path) -> None:
            self.containers: dict[str, SimpleNamespace] = {}

        def load(self) -> None:
            self.containers = {'m11_1': SimpleNamespace(payloads=[b'\x00'])}

    monkeypatch.setattr('tools.decode_graphics.JarProject', FakeJarProject)
    monkeypatch.setattr('tools.decode_graphics.parse_atlas', lambda *_args, **_kwargs: atlas)

    out_dir = tmp_path / 'out'
    decode_graphics(tmp_path / 'fake.jar', out_dir)

    metadata = (out_dir / 'extracted' / 'sprites' / 'm11_1' / 'chunk_00' / 'metadata.json').read_text(encoding='utf-8')
    manifest = (out_dir / 'extracted' / 'sprites' / 'm11_1' / 'chunk_00' / 'manifest.json').read_text(encoding='utf-8')
    frames = (out_dir / 'extracted' / 'images' / 'm11_1' / 'chunk_00' / 'frames.json').read_text(encoding='utf-8')

    metadata_json = json.loads(metadata)
    manifest_json = json.loads(manifest)
    frames_json = json.loads(frames)

    assert metadata_json['frame_count'] == 1
    assert len(manifest_json['frames']) == 1
    assert len(frames_json['frames']) == 1
    assert metadata_json['frame_count'] == len(manifest_json['frames']) == len(frames_json['frames'])

    skipped_payload = next(payload for payload in frames_json['payloads'] if payload['frame_index'] == 1)
    assert skipped_payload['data_chunk'] == -1
    assert skipped_payload['skipped_reason'] == 'missing_data_chunk'
    assert frames_json['skipped_frames'][0]['skipped_reason'] == 'missing_data_chunk'
