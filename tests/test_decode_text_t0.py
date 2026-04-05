from __future__ import annotations

from pathlib import Path

from tools.decode_text_t0 import decode_text, decode_text_chunk


def test_decode_text_chunk_with_utf8_fixture(t0_payload: bytes) -> None:
    decoded = decode_text_chunk(t0_payload)

    assert decoded['encoding_used'] == 'utf-8', 'decode_text_chunk() should prefer UTF-8 for valid UTF-8 bytes.'
    assert decoded['text'] == 'Привет', 'Decoded text should match the fixture payload.'
    assert decoded['decode_quality']['replacement_count'] == 0, 'Valid UTF-8 input should decode without replacement characters.'


def test_decode_text_chunk_empty_input() -> None:
    decoded = decode_text_chunk(b'')

    assert decoded['text'] == '', 'Empty byte input should decode to an empty string.'
    assert decoded['decode_quality']['replacement_count'] == 0, 'Empty input should not produce replacement characters.'


def test_decode_text_reads_t0_from_same_jar_fixture(tmp_path: Path, jar_with_t0: Path) -> None:
    output = tmp_path / 'decode_out'
    result = decode_text(jar_with_t0, output)

    assert 'chunks' in result, 'decode_text() should return a mapping with the "chunks" key.'
    assert len(result['chunks']) == 1, 'Fixture JAR includes one t0 chunk, so decode_text() should return one chunk entry.'

    text_path = output / result['chunks'][0]['path']
    assert text_path.exists(), 'decode_text() must write decoded text file referenced by result["chunks"][0]["path"].'
    assert text_path.read_text(encoding='utf-8') == 'Привет', 'Decoded output text should match the fixture content.'
