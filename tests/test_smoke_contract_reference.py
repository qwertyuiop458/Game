from __future__ import annotations

from pathlib import Path

import pytest

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
