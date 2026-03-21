from __future__ import annotations

import argparse
from pathlib import Path

from tools.common import JarProject, decode_game_text, ensure_dir, sanitize_text, u32le, write_json


def guess_offset_table(chunk: bytes) -> dict | None:
    best = None
    limit = min(512, len(chunk))
    for start in range(0, limit):
        offsets = []
        pos = start
        while pos + 4 <= len(chunk):
            value = u32le(chunk, pos)
            if value >= len(chunk):
                break
            if offsets and value < offsets[-1]:
                break
            offsets.append(value)
            pos += 4
            if len(offsets) >= 2:
                candidate = {'start': start, 'count': len(offsets), 'blob_start': pos}
                if best is None or candidate['count'] > best['count']:
                    best = candidate
        
    return best if best and best['count'] >= 4 else None


def decode_text(jar: Path, output: Path) -> dict:
    project = JarProject(jar, output)
    project.load()
    container = project.containers['t0']
    out_dir = output / 'extracted' / 'text'
    ensure_dir(out_dir)
    result = {'chunks': []}
    for idx, chunk in enumerate(container.payloads):
        decoded = sanitize_text(decode_game_text(chunk))
        full_path = out_dir / f't0_{idx:02d}_full.txt'
        full_path.write_text(decoded, encoding='utf-8')
        entry = {
            'chunk_index': idx,
            'char_length': len(decoded),
            'path': str(full_path.relative_to(output)),
        }
        guess = guess_offset_table(chunk)
        if guess:
            offsets = [u32le(chunk, guess['start'] + i * 4) for i in range(guess['count'])]
            combined = chunk[:guess['start']] + chunk[guess['blob_start']:]
            last = 0
            strings = []
            for end in offsets:
                if 0 <= last <= end <= len(combined):
                    strings.append(sanitize_text(decode_game_text(combined[last:end])))
                    last = end
            if last < len(combined):
                strings.append(sanitize_text(decode_game_text(combined[last:])))
            strings = [s for s in strings if s.strip()]
            guessed = out_dir / f't0_{idx:02d}_segments_guess.json'
            write_json(guessed, {'chunk_index': idx, 'offset_table_guess': guess, 'strings': strings})
            reconstructed = out_dir / f't0_{idx:02d}_reconstructed.txt'
            reconstructed.write_text('\n'.join(strings) + '\n', encoding='utf-8')
            entry['segment_guess_path'] = str(guessed.relative_to(output))
            entry['reconstructed_path'] = str(reconstructed.relative_to(output))
            entry['segment_guess_count'] = len(strings)
        result['chunks'].append(entry)
    write_json(out_dir / 'index.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode t0 text container')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    decode_text(args.jar, args.output)


if __name__ == '__main__':
    main()
