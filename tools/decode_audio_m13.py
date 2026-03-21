from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json


def analyse_audio_blob(chunk: bytes) -> dict:
    return {
        'size': len(chunk),
        'head_hex': chunk[:32].hex(),
        'nonzero_bytes': sum(1 for b in chunk if b),
        'top_bytes': Counter(chunk).most_common(8),
    }


def decode_audio(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    audio_dir = output / 'extracted' / 'audio'
    ensure_dir(audio_dir)
    out = {'midi': [], 'raw_audio': []}
    for name in ('m13_1', 'm13_2'):
        container = project.containers.get(name)
        if not container:
            continue
        pack_dir = audio_dir / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            if not chunk:
                continue
            if b'MThd' in chunk:
                start = chunk.index(b'MThd')
                path = pack_dir / f'{idx:02d}.mid'
                path.write_bytes(chunk[start:])
                out['midi'].append(str(path.relative_to(output)))
            else:
                path = pack_dir / f'{idx:02d}.bin'
                meta = pack_dir / f'{idx:02d}.json'
                path.write_bytes(chunk)
                write_json(meta, analyse_audio_blob(chunk))
                out['raw_audio'].append({'path': str(path.relative_to(output)), 'meta': str(meta.relative_to(output))})
    write_json(audio_dir / 'index.json', out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode m13_1/m13_2 audio packs')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_audio(args.jar, args.output)


if __name__ == '__main__':
    main()
