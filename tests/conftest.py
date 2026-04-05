from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


def make_single_chunk_container(chunk: bytes) -> bytes:
    """Build a minimal u32-header container with exactly one chunk."""
    # header: [chunk_count=1][offset0=0], then payload bytes
    return bytes([1]) + (0).to_bytes(4, 'little') + chunk


@pytest.fixture
def t0_payload() -> bytes:
    return 'Привет'.encode('utf-8')


@pytest.fixture
def t0_container_blob(t0_payload: bytes) -> bytes:
    return make_single_chunk_container(t0_payload)


@pytest.fixture
def jar_with_t0(tmp_path: Path, t0_container_blob: bytes) -> Path:
    jar_path = tmp_path / 'sample.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('t0', t0_container_blob)
    return jar_path
