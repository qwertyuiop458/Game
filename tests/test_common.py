from __future__ import annotations

from pathlib import Path

from tools.common import Container, ContainerValidationError
from tools.parse_packs import parse_packs


def test_container_parses_single_chunk(t0_container_blob: bytes, t0_payload: bytes) -> None:
    container = Container('t0', t0_container_blob)

    assert container.chunk_count == 1, 'Expected one chunk in synthetic t0 container.'
    assert container.payloads == [t0_payload], 'Container payload must match fixture bytes exactly.'
    assert container.header_mode in {'u32', 'u8'}, 'Container parser should report a known header mode.'


def test_container_rejects_too_small_payload() -> None:
    tiny_blob = b'\x01\x00\x00\x00'

    try:
        Container('broken', tiny_blob)
    except ContainerValidationError as exc:
        assert 'too small' in str(exc), 'Validation error should explain that payload is too small.'
    else:
        raise AssertionError('Container() must raise ContainerValidationError for payloads shorter than 5 bytes.')


def test_parse_packs_extracts_t0(tmp_path: Path, jar_with_t0: Path, t0_payload: bytes) -> None:
    output = tmp_path / 'out'
    parsed = parse_packs(jar_with_t0, output)

    assert 't0' in parsed, 'parse_packs() should discover t0 in the input JAR.'
    assert parsed['t0']['chunk_count'] == 1, 'Synthetic t0 fixture should produce exactly one parsed chunk.'

    chunk_file = output / 'chunks' / 't0' / '00.bin'
    assert chunk_file.exists(), 'parse_packs() must export chunk bytes to chunks/t0/00.bin.'
    assert chunk_file.read_bytes() == t0_payload, 'Exported chunk bytes must equal the original t0 payload.'
