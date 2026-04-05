from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from tests.conftest import make_single_chunk_container
from tools.decode_text_t0 import decode_text


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_writes_integrity_sidecar(jar_with_t0: Path, tmp_path: Path):
    output = tmp_path / 'out'
    result = decode_text(jar_with_t0, output)

    chunk_entry = result['chunks'][0]
    integrity_path = output / chunk_entry['integrity_path']
    assert integrity_path.exists()

    integrity = json.loads(integrity_path.read_text(encoding='utf-8'))
    assert integrity['status'] == 'ok'
    assert integrity['before']['segment_count'] == 1
    assert integrity['after']['segment_count'] == 1
    assert integrity['before']['non_empty_line_count'] == 1
    assert integrity['after']['non_empty_line_count'] == 1
    assert integrity['before']['control_char_line_ratio'] == 0.0
    assert integrity['after']['control_char_line_ratio'] == 0.0


@pytest.mark.decode
@pytest.mark.extractor
def test_decode_text_integrity_reports_line_drop_anomaly(tmp_path: Path):
    # one chunk with 5 non-empty lines; four are pure control chars and are removed by sanitization
    payload = b'good\n\x01\n\x02\n\x03\n\x04\n'
    jar_path = tmp_path / 'anomaly.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        zf.writestr('t0', make_single_chunk_container(payload))

    output = tmp_path / 'out'
    result = decode_text(jar_path, output, strings_encoding='latin-1')
    integrity_path = output / result['chunks'][0]['integrity_path']
    integrity = json.loads(integrity_path.read_text(encoding='utf-8'))

    assert integrity['status'] == 'error'
    assert integrity['before']['non_empty_line_count'] == 5
    assert integrity['after']['non_empty_line_count'] == 1
    assert any(check['code'] == 'non_empty_lines_drop' and check['severity'] == 'error' for check in integrity['checks'])
