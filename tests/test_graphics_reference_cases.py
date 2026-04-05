import json
import subprocess
from pathlib import Path

import pytest

from tools.decode_graphics import _render_frame_with_diagnostics
from tools.graphics_decoder import parse_atlas
from tools.reference_cases import _build_expected_case, load_reference_cases, verify_reference_cases


@pytest.mark.graphics
@pytest.mark.extractor
def test_graphics_reference_cases_are_consistent() -> None:
    mismatches = verify_reference_cases(Path('tests/reference_cases/graphics'))
    assert not mismatches, '\n'.join(mismatches)


@pytest.mark.graphics
@pytest.mark.extractor
def test_graphics_reference_cases_include_stable_render_metrics() -> None:
    for case in load_reference_cases(Path('tests/reference_cases/graphics')):
        expected = json.loads(case.expected_metadata.read_text(encoding='utf-8'))
        actual = _build_expected_case(case)
        assert expected['preview']['width'] == actual['preview']['width']
        assert expected['preview']['height'] == actual['preview']['height']
        assert expected['preview']['rgba_sha256'] == actual['preview']['rgba_sha256']
        assert expected['preview']['channel_sum'] == actual['preview']['channel_sum']


@pytest.mark.graphics
@pytest.mark.extractor
def test_reference_update_requires_explicit_confirmation(tmp_path: Path) -> None:
    case_dir = tmp_path / 'graphics'
    source = Path('tests/reference_cases/graphics/minimal_index8_external')
    target = case_dir / 'minimal_index8_external'
    target.mkdir(parents=True)
    for name in ('case.json', 'table_chunk.hex', 'external_02.hex', 'preview.png.b64', 'expected.json'):
        (target / name).write_bytes((source / name).read_bytes())

    denied = subprocess.run(
        ['python3', '-m', 'tools.reference_cases', '--cases-dir', str(case_dir), '--update'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert denied.returncode != 0
    assert '--confirm-update' in denied.stdout + denied.stderr

    allowed = subprocess.run(
        ['python3', '-m', 'tools.reference_cases', '--cases-dir', str(case_dir), '--update', '--confirm-update'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


@pytest.mark.graphics
@pytest.mark.extractor
def test_non_empty_raw_does_not_render_fully_transparent_without_status() -> None:
    case_dir = Path('tests/reference_cases/graphics/index8_inline_zero_alpha_palette')
    table_blob = bytes.fromhex((case_dir / 'table_chunk.hex').read_text(encoding='utf-8').strip())
    atlas = parse_atlas('index8_inline_zero_alpha_palette', table_blob, chunk_index=0, external_chunks=[])
    frame_index = 0
    frame_offset = atlas.sprite_data_offsets[frame_index]
    frame_size = atlas.sprite_lengths[frame_index]
    raw_block = atlas.sprite_data[frame_offset:frame_offset + frame_size]

    width, height, rgba, status, _diagnostics = _render_frame_with_diagnostics(atlas, frame_index, raw_block)
    assert (width, height) == (2, 2)
    assert raw_block
    opaque_pixels = sum(1 for px in rgba if ((px >> 24) & 0xFF) > 0)
    assert status in {'degraded_decode', 'failed_decode'} or opaque_pixels > 0
