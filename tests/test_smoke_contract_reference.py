from __future__ import annotations

from pathlib import Path

import pytest

from tools.decode_graphics import evaluate_graphics_quality_gate
from tools.decode_text_t0 import decode_text_chunk, export_strings
from tools.reference_cases import verify_reference_cases


@pytest.mark.smoke
@pytest.mark.extractor
def test_smoke_reference_cases_regression() -> None:
    mismatches = verify_reference_cases(Path('tests/reference_cases/graphics'))
    assert not mismatches, '\n'.join(mismatches)


@pytest.mark.smoke
@pytest.mark.decode
@pytest.mark.extractor
def test_smoke_text_contract_regression() -> None:
    payload = b'Line1\x85Line2\x00Line3\x1f'
    decoded = decode_text_chunk(payload)
    assert decoded['text'].splitlines() == ['Line1', 'Line2 Line3 ']
    segments = export_strings(b'AA\x00BBCC\x1fDD', [5])
    assert len(segments) == 2
    assert segments[0]['text'] == 'AA BB'
    assert segments[1]['text'] == 'CC DD'


@pytest.mark.smoke
@pytest.mark.decode
@pytest.mark.extractor
def test_smoke_graphics_quality_gate_contract() -> None:
    gate = evaluate_graphics_quality_gate(
        total_frames=10,
        decoded_frames=6,
        degraded_frames=2,
        failed_frames=1,
        skipped_frames=1,
        non_empty_raw_frames=8,
        non_empty_raw_with_alpha_nonzero=7,
        failed_non_empty_raw_frames=1,
        reference_cases_passed=True,
    )
    assert 'graphics_quality_gate' not in gate
    assert set(gate) == {
        'total_frames',
        'decoded_frames',
        'degraded_frames',
        'failed_frames',
        'skipped_frames',
        'non_empty_raw_frames',
        'non_empty_raw_with_alpha_nonzero',
        'reference_cases_passed',
        'gate_passed',
        'gate_reasons',
    }
    assert all(gate[key] >= 0 for key in (
        'total_frames',
        'decoded_frames',
        'degraded_frames',
        'failed_frames',
        'skipped_frames',
        'non_empty_raw_frames',
        'non_empty_raw_with_alpha_nonzero',
    ))
    assert gate['decoded_frames'] + gate['degraded_frames'] + gate['failed_frames'] + gate['skipped_frames'] == gate[
        'total_frames'
    ]
    assert gate['gate_passed'] is False
    assert 'non_empty_raw_failed_without_acceptable_degradation' in gate['gate_reasons']

    passed_gate = evaluate_graphics_quality_gate(
        total_frames=4,
        decoded_frames=3,
        degraded_frames=1,
        failed_frames=0,
        skipped_frames=0,
        non_empty_raw_frames=4,
        non_empty_raw_with_alpha_nonzero=4,
        failed_non_empty_raw_frames=0,
        reference_cases_passed=True,
    )
    assert passed_gate['gate_passed'] is True
    assert passed_gate['gate_reasons'] == []
