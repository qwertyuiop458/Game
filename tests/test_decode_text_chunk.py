import pytest

from tools.decode_text_t0 import build_integrity_report, decode_text_chunk, export_strings, text_metrics


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_uses_utf8_when_valid():
    payload = 'Привет'.encode('utf-8')
    result = decode_text_chunk(payload)
    assert result['encoding_used'] == 'utf-8'
    assert result['raw_text'] == 'Привет'
    assert result['text'] == 'Привет'
    assert result['decode_quality']['replacement_count'] == 0


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_falls_back_to_cp1251():
    payload = 'Привет'.encode('cp1251')
    result = decode_text_chunk(payload)
    assert result['encoding_used'] == 'cp1251'
    assert result['raw_text'] == 'Привет'
    assert result['text'] == 'Привет'
    assert result['decode_quality']['replacement_count'] == 0


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_chunk_uses_forced_latin1():
    payload = b'\xff'
    result = decode_text_chunk(payload, forced_encoding='latin-1')
    assert result['encoding_used'] == 'latin-1'
    assert result['raw_text'] == 'ÿ'
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
            'raw_text': 'one',
            'encoding_used': 'utf-8',
            'replacement_stats': {'replacement_count': 0, 'replacement_ratio': 0.0},
            'decode_quality': {'replacement_count': 0, 'replacement_ratio': 0.0},
        },
        {
            'text': 'two',
            'raw_text': 'two',
            'encoding_used': 'utf-8',
            'replacement_stats': {'replacement_count': 0, 'replacement_ratio': 0.0},
            'decode_quality': {'replacement_count': 0, 'replacement_ratio': 0.0},
        },
    ]


@pytest.mark.decode
@pytest.mark.extractor
def test_integrity_report_flags_sharp_drop():
    before = text_metrics('ok\n\x01\n\x02\n\x03\n\x04\n', segment_count=1)
    after = text_metrics('ok\n \n \n \n \n', segment_count=1)
    report = build_integrity_report(before, after)
    assert report['status'] == 'error'
    assert any(check['code'] == 'non_empty_lines_drop' and check['severity'] == 'error' for check in report['checks'])
