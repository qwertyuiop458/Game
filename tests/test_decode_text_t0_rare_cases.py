from __future__ import annotations

import pytest

from tools.common import sanitize_text
from tools.decode_text_t0 import decode_text_chunk, export_strings, guess_offset_table, u32le


@pytest.fixture
def noisy_text_cases() -> list[tuple[str, bytes, str]]:
    return [
        (
            'controls_inside_line',
            b'AB\x01CD\x1fEF\tGH\nIJ',
            'AB CD EF\tGH\nIJ',
        ),
        (
            'nul_bytes_inside_line',
            b'Hello\x00World\x00!',
            'Hello World !',
        ),
        (
            'mixed_utf8_cp1251_noise',
            b'Hi, ' + 'Привет'.encode('cp1251') + b'\x00\x02',
            'Hi, Привет  ',
        ),
        (
            'windows_and_legacy_separators',
            b'row1\r\nrow2\x85row3\x1erow4',
            'row1\nrow2\nrow3\nrow4',
        ),
        (
            'rare_control_bytes_kept_stable',
            b'A\x7fB\x00C\x1dD\x02E',
            'A\x7fB C D E',
        ),
    ]


@pytest.fixture
def partially_broken_offset_chunk() -> bytes:
    # 4 valid monotonic offsets, then one broken (decreasing) entry.
    offsets = [5, 10, 15, 20, 3]
    table = b''.join(value.to_bytes(4, 'little') for value in offsets)
    blob = b'ABCDE12345xx\x00yy\tQ R\x00END'
    return table + blob


@pytest.fixture
def rare_segment_blob() -> tuple[bytes, list[int], list[str], str]:
    combined = (
        b'HP:\x0010'
        + b'Name:\x85Boss'
        + b'Raw:' + 'Привет'.encode('cp1251') + b'\x00\x02'
    )
    offsets = [6, 16]
    expected_segments = ['HP: 10', 'Name:\nBoss', 'Raw:Привет  ']
    expected_reconstructed = 'HP: 10\nName:\nBoss\nRaw:Привет  \n'
    return combined, offsets, expected_segments, expected_reconstructed


@pytest.mark.decode
@pytest.mark.extractor
def test_noisy_cases_do_not_crash_and_are_deterministic(noisy_text_cases: list[tuple[str, bytes, str]]):
    for case_name, payload, expected_text in noisy_text_cases:
        result = decode_text_chunk(payload)
        assert result['text'] == expected_text, case_name
        assert result['decode_quality']['replacement_count'] >= 0, case_name


@pytest.mark.decode
@pytest.mark.extractor
@pytest.mark.smoke
def test_sanitize_text_is_predictable_for_controls_and_nulls():
    raw = 'A\x00B\x01C\x1fD\tE\nF'
    assert sanitize_text(raw) == 'A B C D\tE\nF'


@pytest.mark.decode
@pytest.mark.extractor
def test_export_strings_has_explicit_reconstruction_for_rare_sequences(
    rare_segment_blob: tuple[bytes, list[int], list[str], str],
):
    combined, offsets, expected_segments, expected_reconstructed = rare_segment_blob

    strings = export_strings(combined, offsets)
    actual_segments = [item['text'] for item in strings]
    reconstructed = ''.join(f'{text}\n' for text in actual_segments)

    assert actual_segments == expected_segments
    assert reconstructed == expected_reconstructed


@pytest.mark.decode
@pytest.mark.extractor
def test_partially_broken_offset_table_keeps_segment_count_stable(partially_broken_offset_chunk: bytes):
    guess = guess_offset_table(partially_broken_offset_chunk)
    assert guess is not None
    assert guess['count'] >= 4

    offsets = [u32le(partially_broken_offset_chunk, guess['start'] + i * 4) for i in range(guess['count'])]
    combined = partially_broken_offset_chunk[: guess['start']] + partially_broken_offset_chunk[guess['blob_start'] :]
    segments = export_strings(combined, offsets)

    reconstructed = '\n'.join(item['text'] for item in segments)
    reconstructed_segments = [line for line in reconstructed.split('\n') if line.strip()]

    assert len(segments) == len(reconstructed_segments)
    assert len(segments) > 0


@pytest.mark.decode
@pytest.mark.extractor
def test_export_strings_with_rare_offsets_preserves_count_and_fallback_symbols() -> None:
    combined = b'AA\x00BB' + b'CC\x01DD' + b'EE\x85FF' + b'GG\x1fHH'
    offsets = [5, 10, 15]
    segments = export_strings(combined, offsets)

    assert len(segments) == 4
    assert [entry['text'] for entry in segments] == ['AA BB', 'CC DD', 'EE\nFF', 'GG HH']
    assert all('�' not in entry['text'] for entry in segments)
    assert '\n'.join(entry['text'] for entry in segments).count('\n') == 4
