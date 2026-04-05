import json
import subprocess
from pathlib import Path

import pytest

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
