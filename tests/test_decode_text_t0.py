import pytest


@pytest.mark.decode
@pytest.mark.extractor
@pytest.mark.xfail(
    reason='Legacy placeholder tests for decode_text API; будет включено после финализации контракта.',
    strict=False,
)
class TestDecodeText:
    def test_valid_encoded_text(self):
        pytest.fail('Placeholder: decode_text contract is not finalized yet.')

    def test_empty_string(self):
        pytest.fail('Placeholder: decode_text contract is not finalized yet.')

    def test_invalid_encoded_text(self):
        pytest.fail('Placeholder: decode_text contract is not finalized yet.')

    def test_edge_cases(self):
        pytest.fail('Placeholder: decode_text contract is not finalized yet.')
