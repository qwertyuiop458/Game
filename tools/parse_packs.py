from __future__ import annotations

import argparse
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json


def parse_packs(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    out = {}
    chunk_root = output / 'chunks'
    ensure_dir(chunk_root)
    for name, container in project.containers.items():
        pack_dir = chunk_root / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            (pack_dir / f'{idx:02d}.bin').write_bytes(chunk)
        out[name] = container.describe()
    write_json(output / 'chunks' / 'containers.json', out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description='Parse Gameloft m* containers from Zombie Infection')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    parse_packs(args.jar, args.output)


if __name__ == '__main__':
    main()
