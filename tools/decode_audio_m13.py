from __future__ import annotations

import argparse
import hashlib
import math
import zlib
from collections import Counter
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json


def _u16be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def validate_midi_blob(blob: bytes) -> dict[str, int | str]:
    if len(blob) < 14:
        return {'status': 'invalid', 'reason': 'midi_header_too_short'}
    if blob[:4] != b'MThd':
        return {'status': 'invalid', 'reason': 'missing_mthd_header'}

    header_len = int.from_bytes(blob[4:8], byteorder='big', signed=False)
    if header_len != 6:
        return {'status': 'invalid', 'reason': f'invalid_mthd_length:{header_len}'}

    if len(blob) < 8 + header_len:
        return {'status': 'invalid', 'reason': 'truncated_mthd_payload'}

    track_count = _u16be(blob, 10)
    if track_count <= 0:
        return {'status': 'invalid', 'reason': f'invalid_track_count:{track_count}'}

    mtrk_count = blob.count(b'MTrk')
    if mtrk_count <= 0:
        return {'status': 'invalid', 'reason': 'missing_mtrk_chunk'}
    if mtrk_count != track_count:
        return {
            'status': 'warning',
            'reason': f'track_count_mismatch:declared={track_count},found={mtrk_count}',
            'declared_tracks': track_count,
            'found_tracks': mtrk_count,
        }

    return {
        'status': 'valid',
        'reason': 'ok',
        'declared_tracks': track_count,
        'found_tracks': mtrk_count,
    }


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


def detect_chunk_format(chunk: bytes) -> tuple[str, bytes]:
    if b'MThd' in chunk:
        start = chunk.index(b'MThd')
        return 'midi', chunk[start:]
    return 'raw', chunk


def _load_unsupported_registry(path: Path) -> list[dict[str, str | int]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def decode_audio(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    audio_dir = output / 'extracted' / 'audio'
    ensure_dir(audio_dir)
    unsupported_path = audio_dir / 'unsupported_m13_signatures.json'
    unsupported_registry = _load_unsupported_registry(unsupported_path)
    seen_unsupported = {str(item.get('signature_hex')) for item in unsupported_registry if item.get('signature_hex')}
    signature_registry: list[dict[str, str | int]] = []
    out = {
        'midi': [],
        'midi_validation': [],
        'raw_audio': [],
        'midi_validation_report': str((audio_dir / 'midi_validation_report.json').relative_to(output)),
        'invalid_audio': [],
        'signature_registry': str((audio_dir / 'signatures.json').relative_to(output)),
        'unsupported_signature_registry': str(unsupported_path.relative_to(output)),
        'stats': {'valid': 0, 'invalid': 0, 'raw': 0},
        'counts': {'valid_midi': 0, 'invalid_midi': 0, 'raw_audio': 0, 'warnings': 0},
        'audio_coverage': {'total_tracks': 0, 'decoded_tracks': 0, 'coverage_percent': 0.0},
        'midi_validation_summary': {'total': 0, 'valid': 0, 'invalid': 0, 'warnings': 0},
    }
    coverage = {'total_chunks': 0, 'empty_chunks': 0}
    for name in ('m13_1', 'm13_2'):
        container = project.containers.get(name)
        if not container:
            continue
        pack_dir = audio_dir / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            if not chunk:
                continue
            try:
                chunk_kind, payload = detect_chunk_format(chunk)
                if chunk_kind == 'midi':
                    path = pack_dir / f'{idx:02d}.mid'
                    path.write_bytes(payload)
                    out['midi'].append(str(path.relative_to(output)))
                    midi_check = validate_midi_blob(payload)
                    midi_validation_entry = {
                        'container': name,
                        'chunk_index': idx,
                        'path': str(path.relative_to(output)),
                        'status': str(midi_check['status']),
                        'reason': str(midi_check['reason']),
                    }
                    if 'declared_tracks' in midi_check:
                        midi_validation_entry['declared_tracks'] = int(midi_check['declared_tracks'])
                    if 'found_tracks' in midi_check:
                        midi_validation_entry['found_tracks'] = int(midi_check['found_tracks'])
                    out['midi_validation'].append(midi_validation_entry)
                    out['stats']['valid'] += 1
                    out['midi_validation_summary']['total'] += 1
                    if midi_check['status'] == 'invalid':
                        out['midi_validation_summary']['invalid'] += 1
                        out['counts']['invalid_midi'] += 1
                    elif midi_check['status'] == 'warning':
                        out['midi_validation_summary']['warnings'] += 1
                        out['counts']['warnings'] += 1
                        out['counts']['valid_midi'] += 1
                    else:
                        out['midi_validation_summary']['valid'] += 1
                        out['counts']['valid_midi'] += 1
                    signature_registry.append({
                        'container': name,
                        'chunk_index': idx,
                        'kind': 'midi',
                        'path': str(path.relative_to(output)),
                        'size': len(payload),
                        'crc32_hex': f'{zlib.crc32(payload) & 0xFFFFFFFF:08x}',
                        'sha1': hashlib.sha1(payload).hexdigest(),
                    })
                else:
                    path = pack_dir / f'{idx:02d}.bin'
                    meta = pack_dir / f'{idx:02d}.json'
                    path.write_bytes(payload)
                    write_json(meta, analyse_audio_blob(payload))
                    out['raw_audio'].append({'path': str(path.relative_to(output)), 'meta': str(meta.relative_to(output))})
                    out['stats']['valid'] += 1
                    out['stats']['raw'] += 1
                    out['counts']['raw_audio'] += 1
                    signature_registry.append({
                        'container': name,
                        'chunk_index': idx,
                        'kind': 'raw',
                        'path': str(path.relative_to(output)),
                        'meta': str(meta.relative_to(output)),
                        'size': len(payload),
                        'crc32_hex': f'{zlib.crc32(payload) & 0xFFFFFFFF:08x}',
                        'sha1': hashlib.sha1(payload).hexdigest(),
                    })
                    chunk_signature = build_chunk_signature(payload)
                    signature_hex = str(chunk_signature['head_hex'])
                    if signature_hex not in seen_unsupported:
                        seen_unsupported.add(signature_hex)
                        unsupported_registry.append({
                            'signature_hex': signature_hex,
                            'first_seen_pack': name,
                            'chunk_index': idx,
                            'length': len(payload),
                            'notes': 'Unknown non-MIDI chunk format; stored as raw binary.',
                        })
            except Exception as exc:
                out['stats']['invalid'] += 1
                out['invalid_audio'].append({
                    'container': name,
                    'chunk_index': idx,
                    'error': str(exc),
                })
    decoded_tracks = coverage['total_chunks'] - coverage['empty_chunks']
    coverage_percent = 0.0 if coverage['total_chunks'] == 0 else round(decoded_tracks * 100.0 / coverage['total_chunks'], 2)
    out['audio_coverage'] = {
        'total_tracks': coverage['total_chunks'],
        'decoded_tracks': decoded_tracks,
        'coverage_percent': coverage_percent,
    }
    write_json(audio_dir / 'signatures.json', signature_registry)
    write_json(audio_dir / 'midi_validation_report.json', out['midi_validation_summary'])
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
