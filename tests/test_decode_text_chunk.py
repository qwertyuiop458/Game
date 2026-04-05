import pytest

from tools.decode_text_t0 import decode_text_chunk, export_strings


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_uses_utf8_when_valid():
    payload = 'Привет'.encode('utf-8')
    result = decode_text_chunk(payload)
    assert result['encoding_used'] == 'utf-8'
    assert result['text'] == 'Привет'
    assert result['decode_quality']['replacement_count'] == 0


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_falls_back_to_cp1251():
    payload = 'Привет'.encode('cp1251')
    result = decode_text_chunk(payload)
    assert result['encoding_used'] == 'cp1251'
    assert result['text'] == 'Привет'
    assert result['decode_quality']['replacement_count'] == 0


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_uses_forced_latin1():
    payload = b'\xff'
    result = decode_text_chunk(payload, forced_encoding='latin-1')
    assert result['encoding_used'] == 'latin-1'
    assert result['text'] == 'ÿ'
    assert result['decode_quality']['replacement_count'] == 0


@pytest.mark.decode
@pytest.mark.extractor
def test_export_strings_keeps_encoding_metadata():
    combined = b'one' + b'two'
    strings = export_strings(combined, [3])
    assert strings == [
        {
            'text': 'one',
            'encoding_used': 'utf-8',
            'replacement_stats': {'replacement_count': 0, 'replacement_ratio': 0.0},
            'decode_quality': {'replacement_count': 0, 'replacement_ratio': 0.0},
        },
        {
            'text': 'two',
            'encoding_used': 'utf-8',
            'replacement_stats': {'replacement_count': 0, 'replacement_ratio': 0.0},
            'decode_quality': {'replacement_count': 0, 'replacement_ratio': 0.0},
        },
    ]
