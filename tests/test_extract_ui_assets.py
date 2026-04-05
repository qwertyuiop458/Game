from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from tools.common import JarProject
from tools.extract_zombie_infection import extract_ui_assets


def _build_jar(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_extract_ui_assets_copies_files_and_writes_manifest(tmp_path: Path) -> None:
    jar_path = tmp_path / 'game.jar'
    output = tmp_path / 'out'
    _build_jar(jar_path, {'icon.png': b'ICON', 'dataIGP': b'DATA'})

    project = JarProject(jar_path, output)
    project.load()

    result = extract_ui_assets(project, output)

    assert result['copied'] == {
        'icon.png': 'extracted/ui/icon.png',
        'dataIGP': 'extracted/ui/dataIGP',
    }
    assert result['missing'] == []
    assert (output / 'extracted' / 'ui' / 'icon.png').read_bytes() == b'ICON'
    assert (output / 'extracted' / 'ui' / 'dataIGP').read_bytes() == b'DATA'

    manifest = json.loads((output / 'extracted' / 'meta' / 'ui_manifest.json').read_text(encoding='utf-8'))
    assert manifest['source_jar'] == 'game.jar'
    assert manifest['missing_files'] == []
    assert [item['name'] for item in manifest['files']] == ['icon.png', 'dataIGP']
    assert manifest['files'][0]['size_bytes'] == 4
    assert manifest['files'][1]['size_bytes'] == 4


def test_extract_ui_assets_warns_when_assets_are_missing(tmp_path: Path, caplog) -> None:
    jar_path = tmp_path / 'game.jar'
    output = tmp_path / 'out'
    _build_jar(jar_path, {'icon.png': b'ICON'})

    project = JarProject(jar_path, output)
    project.load()

    caplog.set_level(logging.WARNING)
    result = extract_ui_assets(project, output)

    assert result['missing'] == ['dataIGP']
    assert 'UI assets are missing' in caplog.text
    assert 'dataIGP' in caplog.text
    assert not (output / 'extracted' / 'ui' / 'dataIGP').exists()

    manifest = json.loads((output / 'extracted' / 'meta' / 'ui_manifest.json').read_text(encoding='utf-8'))
    assert manifest['missing_files'] == ['dataIGP']
    assert [item['name'] for item in manifest['files']] == ['icon.png']
