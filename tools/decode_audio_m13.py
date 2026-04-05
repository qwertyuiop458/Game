from __future__ import annotations

import argparse
import hashlib
import math
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


def build_chunk_signature(chunk: bytes, head_size: int = 24, top_bytes: int = 8) -> dict:
    size = len(chunk)
    if size == 0:
        return {
            'key': 'empty:0',
            'size': 0,
            'head_hex': '',
            'sha1': hashlib.sha1(chunk).hexdigest(),
            'nonzero_ratio': 0.0,
            'entropy': 0.0,
            'top_bytes': [],
        }
    freq = Counter(chunk)
    entropy = 0.0
    for count in freq.values():
        p = count / size
        entropy -= p * math.log2(p)
    head_hex = chunk[:head_size].hex()
    top = freq.most_common(top_bytes)
    nonzero_ratio = round(sum(1 for b in chunk if b) / size, 4)
    key = (
        f'len:{size}|head:{head_hex}|'
        f'entropy:{entropy:.4f}|nonzero:{nonzero_ratio:.4f}|'
        f'top:{",".join(f"{byte:02x}:{count}" for byte, count in top)}'
    )
    return {
        'key': key,
        'size': size,
        'head_hex': head_hex,
        'sha1': hashlib.sha1(chunk).hexdigest(),
        'nonzero_ratio': nonzero_ratio,
        'entropy': round(entropy, 4),
        'top_bytes': [[byte, count] for byte, count in top],
    }


def decode_audio(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    audio_dir = output / 'extracted' / 'audio'
    ensure_dir(audio_dir)
    out = {'midi': [], 'raw_audio': []}
    unsupported_registry: dict[str, dict] = {}
    coverage = {
        'total_chunks': 0,
        'empty_chunks': 0,
        'midi_chunks': 0,
        'unsupported_chunks': 0,
    }
    for name in ('m13_1', 'm13_2'):
        container = project.containers.get(name)
        if not container:
            continue
        pack_dir = audio_dir / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            coverage['total_chunks'] += 1
            if not chunk:
                coverage['empty_chunks'] += 1
                continue
            if b'MThd' in chunk:
                start = chunk.index(b'MThd')
                path = pack_dir / f'{idx:02d}.mid'
                path.write_bytes(chunk[start:])
                out['midi'].append(str(path.relative_to(output)))
                coverage['midi_chunks'] += 1
            else:
                path = pack_dir / f'{idx:02d}.bin'
                meta = pack_dir / f'{idx:02d}.json'
                path.write_bytes(chunk)
                write_json(meta, analyse_audio_blob(chunk))
                out['raw_audio'].append({'path': str(path.relative_to(output)), 'meta': str(meta.relative_to(output))})
                coverage['unsupported_chunks'] += 1

                # Best effort: keep pipeline running and preserve unknown-variant artifacts.
                try:
                    signature = build_chunk_signature(chunk)
                    registry_item = unsupported_registry.setdefault(
                        signature['key'],
                        {
                            'signature': signature,
                            'count': 0,
                            'examples': [],
                            'notes': 'Chunk has no MThd marker; saved as raw binary for later analysis.',
                        },
                    )
                    registry_item['count'] += 1
                    if len(registry_item['examples']) < 8:
                        registry_item['examples'].append(
                            {
                                'container': name,
                                'index': idx,
                                'path': str(path.relative_to(output)),
                                'meta': str(meta.relative_to(output)),
                            }
                        )
                except Exception as exc:
                    fallback_key = f'fallback-len:{len(chunk)}|sha1:{hashlib.sha1(chunk).hexdigest()}'
                    registry_item = unsupported_registry.setdefault(
                        fallback_key,
                        {
                            'signature': {'key': fallback_key, 'size': len(chunk)},
                            'count': 0,
                            'examples': [],
                            'notes': f'Fallback signature used due to signature analysis error: {exc}',
                        },
                    )
                    registry_item['count'] += 1
                    if len(registry_item['examples']) < 8:
                        registry_item['examples'].append(
                            {
                                'container': name,
                                'index': idx,
                                'path': str(path.relative_to(output)),
                                'meta': str(meta.relative_to(output)),
                            }
                        )
    coverage['midi_coverage_ratio'] = round(
        coverage['midi_chunks'] / max(1, coverage['total_chunks'] - coverage['empty_chunks']), 4
    )
    coverage['unsupported_coverage_ratio'] = round(
        coverage['unsupported_chunks'] / max(1, coverage['total_chunks'] - coverage['empty_chunks']), 4
    )
    unsupported_path = audio_dir / 'unsupported_signatures.json'
    unsupported_payload = {
        'signatures': sorted(
            unsupported_registry.values(),
            key=lambda item: item['count'],
            reverse=True,
        ),
        'stats': {
            'unique_signatures': len(unsupported_registry),
            'unsupported_chunks': coverage['unsupported_chunks'],
            'total_nonempty_chunks': max(0, coverage['total_chunks'] - coverage['empty_chunks']),
        },
    }
    write_json(unsupported_path, unsupported_payload)
    out['unsupported_signatures'] = str(unsupported_path.relative_to(output))
    out['coverage'] = coverage
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
