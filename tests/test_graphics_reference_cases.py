from pathlib import Path

import pytest

from tools.reference_cases import verify_reference_cases


@pytest.mark.graphics
@pytest.mark.extractor
def test_graphics_reference_cases_are_consistent() -> None:
    mismatches = verify_reference_cases(Path('tests/reference_cases/graphics'))
    assert not mismatches, '\n'.join(mismatches)
