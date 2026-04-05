from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json


def _u16be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def validate_midi_blob(blob: bytes) -> str | None:
    if len(blob) < 14:
        return 'midi_header_too_short'
    if blob[:4] != b'MThd':
        return 'missing_mthd_header'

    header_len = int.from_bytes(blob[4:8], byteorder='big', signed=False)
    if header_len != 6:
        return f'invalid_mthd_length:{header_len}'

    if len(blob) < 8 + header_len:
        return 'truncated_mthd_payload'

    track_count = _u16be(blob, 10)
    if track_count <= 0:
        return f'invalid_track_count:{track_count}'

    mtrk_count = blob.count(b'MTrk')
    if mtrk_count <= 0:
        return 'missing_mtrk_chunk'

    return None


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
    out = {
        'midi': [],
        'invalid_midi': [],
        'raw_audio': [],
        'counts': {
            'valid_midi': 0,
            'invalid_midi': 0,
            'raw_audio': 0,
        },
    }
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
                midi_blob = chunk[start:]
                reason = validate_midi_blob(midi_blob)
                path = pack_dir / f'{idx:02d}.mid'
                path.write_bytes(midi_blob)
                if reason is None:
                    out['midi'].append(str(path.relative_to(output)))
                    out['counts']['valid_midi'] += 1
                else:
                    meta = pack_dir / f'{idx:02d}.json'
                    write_json(meta, {'kind': 'invalid_midi', 'reason': reason, 'size': len(midi_blob)})
                    out['invalid_midi'].append({
                        'path': str(path.relative_to(output)),
                        'meta': str(meta.relative_to(output)),
                        'reason': reason,
                    })
                    out['counts']['invalid_midi'] += 1
            else:
                path = pack_dir / f'{idx:02d}.bin'
                meta = pack_dir / f'{idx:02d}.json'
                path.write_bytes(chunk)
                write_json(meta, analyse_audio_blob(chunk))
                out['raw_audio'].append({'path': str(path.relative_to(output)), 'meta': str(meta.relative_to(output))})
                out['counts']['raw_audio'] += 1
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
