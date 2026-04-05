from __future__ import annotations

import argparse
from pathlib import Path

from tools.common import JarProject, ensure_dir, write_json


def parse_packs(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    out = {}
    disputed_names = {'m3_0', 'm4_0', 'm7', 'm11_0', 'm11_1', 'm8', 'm9', 'm10'}
    validation_report = {}
    chunk_root = output / 'chunks'
    ensure_dir(chunk_root)
    for name, container in project.containers.items():
        pack_dir = chunk_root / name
        ensure_dir(pack_dir)
        for idx, chunk in enumerate(container.payloads):
            (pack_dir / f'{idx:02d}.bin').write_bytes(chunk)
        out[name] = container.describe()
        if name in disputed_names:
            chunk_sizes = [len(chunk) for chunk in container.payloads]
            suspicious_chunks = []
            for idx, ((rel_start, rel_end), chunk) in enumerate(zip(container.relative_ranges, container.payloads)):
                reasons = []
                if rel_start > rel_end:
                    reasons.append('start_greater_than_end')
                if rel_start < 0 or rel_end < 0:
                    reasons.append('negative_range')
                if rel_end > container.payload_size:
                    reasons.append('range_exceeds_payload')
                if len(chunk) == 0:
                    reasons.append('empty_chunk')
                if reasons:
                    suspicious_chunks.append({
                        'index': idx,
                        'start': rel_start,
                        'end': rel_end,
                        'size': len(chunk),
                        'reasons': reasons,
                    })
            validation_report[name] = {
                'header_mode': container.header_mode,
                'valid': container.valid,
                'validation_errors': container.validation_errors,
                'count': container.chunk_count,
                'offsets': container.offsets,
                'min_chunk_size': min(chunk_sizes) if chunk_sizes else 0,
                'max_chunk_size': max(chunk_sizes) if chunk_sizes else 0,
                'suspicious_chunks': suspicious_chunks,
            }
    write_json(output / 'chunks' / 'containers.json', out)
    write_json(output / 'chunks' / 'container_validation.json', validation_report)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description='Parse Gameloft m* containers from Zombie Infection')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    parse_packs(args.jar, args.output)


if __name__ == '__main__':
    main()
