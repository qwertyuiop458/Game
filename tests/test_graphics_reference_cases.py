import json
import subprocess
from pathlib import Path

import pytest

from tools.decode_graphics import _render_frame_with_diagnostics
from tools.decode_graphics import decode_graphics
from tools.graphics_decoder import parse_atlas
from tools.reference_cases import _build_expected_case, load_reference_cases, verify_reference_cases


@pytest.mark.graphics
@pytest.mark.extractor
def test_graphics_reference_cases_are_consistent() -> None:
    mismatches = verify_reference_cases(Path('tests/reference_cases/graphics'))
    assert not mismatches, '\n'.join(mismatches)


@pytest.mark.graphics
@pytest.mark.extractor
@pytest.mark.smoke
def test_graphics_reference_cases_include_stable_render_metrics() -> None:
    for case in load_reference_cases(Path('tests/reference_cases/graphics')):
        expected = json.loads(case.expected_metadata.read_text(encoding='utf-8'))
        actual = _build_expected_case(case)
        assert isinstance(expected['frames'], list)
        assert isinstance(actual['frames'], list)
        assert expected['totals']['frame_count'] == len(expected['frames'])
        assert actual['totals']['frame_count'] == len(actual['frames'])
        assert [frame['frame_index'] for frame in expected['frames']] == list(range(len(expected['frames'])))
        assert [frame['frame_index'] for frame in actual['frames']] == list(range(len(actual['frames'])))

        assert expected['totals']['preview_rgba_sha256'] == actual['totals']['preview_rgba_sha256']
        assert expected['totals']['channel_sum'] == actual['totals']['channel_sum']
        assert expected['totals']['opaque_pixels'] == actual['totals']['opaque_pixels']

        expected_frames = {frame['frame_index']: frame for frame in expected['frames']}
        actual_frames = {frame['frame_index']: frame for frame in actual['frames']}
        assert expected_frames.keys() == actual_frames.keys()
        for frame_index, expected_frame in expected_frames.items():
            actual_frame = actual_frames[frame_index]
            assert expected_frame['width'] == actual_frame['width']
            assert expected_frame['height'] == actual_frame['height']
            assert expected_frame['rgba_sha256'] == actual_frame['rgba_sha256']
            assert expected_frame['channel_sum'] == actual_frame['channel_sum']
            assert expected_frame['opaque_pixels'] == actual_frame['opaque_pixels']
            assert expected_frame['decode_status'] == actual_frame['decode_status']


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
    assert (
        'Pending differences' in denied.stdout + denied.stderr
        or 'No reference changes detected' in denied.stdout + denied.stderr
    )

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


@pytest.mark.graphics
@pytest.mark.extractor
def test_problematic_runtime_packs_have_reference_cases() -> None:
    expected_case_ids = {'m3_0_chunk_03', 'm4_0_chunk_01', 'm11_0_chunk_05', 'm11_1_chunk_06'}
    case_ids = {case.case_id for case in load_reference_cases(Path('tests/reference_cases/graphics'))}
    assert expected_case_ids.issubset(case_ids)


@pytest.mark.graphics
@pytest.mark.extractor
def test_problematic_runtime_packs_frames_json_contract(tmp_path: Path) -> None:
    output = tmp_path / 'out'
    report = decode_graphics(Path('240x320-rus-zombie-infection.jar'), output)

    for pack, chunk in (('m3_0', 3), ('m4_0', 1), ('m11_0', 5), ('m11_1', 6)):
        assert pack in report['containers']
        chunk_entry = next(item for item in report['containers'][pack]['chunks'] if item['chunk'] == chunk)
        frames_json_path = output / chunk_entry['images_metadata']
        frames_payload = json.loads(frames_json_path.read_text(encoding='utf-8'))

        assert frames_payload['pack'] == pack
        assert frames_payload['chunk'] == chunk
        assert isinstance(frames_payload['frames'], list)
        assert isinstance(frames_payload['payloads'], list)
        assert len(frames_payload['frames']) > 0

        assert len(frames_payload['frames']) == chunk_entry['decoded_frame_count']
        frame_indexes = {frame['frame'] for frame in frames_payload['frames']}
        payload_indexes = {payload['frame_index'] for payload in frames_payload['payloads']}
        assert frame_indexes.issubset(payload_indexes)

        for frame in frames_payload['frames']:
            diagnostics = frame['diagnostics']
            raw_payload = Path(output / frame['raw_payload']).read_bytes()
            assert diagnostics['raw_payload_size'] == len(raw_payload)
            if diagnostics['raw_payload_size'] > 0:
                assert frame['decode_status'] in {'decoded', 'degraded_decode', 'failed_decode'}
                if frame['decode_status'] != 'failed_decode':
                    assert diagnostics['alpha']['non_zero'] > 0
