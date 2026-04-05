from __future__ import annotations

import argparse
from pathlib import Path

from tools.common import JarProject, ensure_dir, sanitize_text, u32le, write_json


ENCODING_CHAIN = ('utf-8', 'cp1251', 'latin-1')


def text_metrics(text: str, segment_count: int) -> dict:
    lines = text.splitlines()
    non_empty_lines = sum(1 for line in lines if line.strip())
    control_lines = sum(
        1
        for line in lines
        if any(ord(ch) < 32 and ch not in '\n\r\t' for ch in line)
    )
    return {
        'segment_count': segment_count,
        'line_count': len(lines),
        'non_empty_line_count': non_empty_lines,
        'control_char_line_ratio': round((control_lines / len(lines)), 6) if lines else 0.0,
    }


def build_integrity_report(before: dict, after: dict) -> dict:
    checks: list[dict] = []
    status = 'ok'
    before_non_empty = before['non_empty_line_count']
    after_non_empty = after['non_empty_line_count']
    line_ratio = (after_non_empty / before_non_empty) if before_non_empty else 1.0
    if before_non_empty > 0 and after_non_empty == 0:
        checks.append({
            'code': 'non_empty_lines_lost',
            'severity': 'error',
            'message': 'All non-empty lines were lost after processing.',
        })
    elif before_non_empty >= 5 and line_ratio < 0.3:
        checks.append({
            'code': 'non_empty_lines_drop',
            'severity': 'error',
            'message': 'Sharp drop in non-empty lines after processing.',
            'details': {'ratio': round(line_ratio, 6)},
        })
    elif before_non_empty >= 3 and line_ratio < 0.7:
        checks.append({
            'code': 'non_empty_lines_drop',
            'severity': 'warning',
            'message': 'Noticeable drop in non-empty lines after processing.',
            'details': {'ratio': round(line_ratio, 6)},
        })

    before_segments = before['segment_count']
    after_segments = after['segment_count']
    if before_segments > 0 and after_segments == 0:
        checks.append({
            'code': 'segments_lost',
            'severity': 'error',
            'message': 'All text segments were lost after processing.',
        })
    elif before_segments >= 4 and (after_segments / before_segments) < 0.5:
        checks.append({
            'code': 'segments_drop',
            'severity': 'warning',
            'message': 'Significant segment count drop after processing.',
            'details': {'ratio': round(after_segments / before_segments, 6)},
        })

    if after['control_char_line_ratio'] > max(before['control_char_line_ratio'] + 0.1, 0.2):
        checks.append({
            'code': 'control_char_ratio_growth',
            'severity': 'warning',
            'message': 'Control-character line ratio increased after processing.',
            'details': {
                'before': before['control_char_line_ratio'],
                'after': after['control_char_line_ratio'],
            },
        })

    if any(check['severity'] == 'error' for check in checks):
        status = 'error'
    elif checks:
        status = 'warning'
    return {'status': status, 'checks': checks, 'before': before, 'after': after}


def decode_chunk_with_fallback(chunk: bytes, forced_encoding: str | None = None) -> dict:
    encodings = (forced_encoding,) if forced_encoding else ENCODING_CHAIN
    best: dict | None = None
    for encoding in encodings:
        decoded = chunk.decode(encoding, errors='replace')
        replacement_count = decoded.count('\ufffd')
        candidate = {
            'raw_text': decoded,
            'decoded_text': sanitize_text(decoded),
            'encoding_used': encoding,
            'replacement_stats': {
                'replacement_count': replacement_count,
                'replacement_ratio': round((replacement_count / len(decoded)), 6) if decoded else 0.0,
            },
        }
        if best is None or replacement_count < best['replacement_stats']['replacement_count']:
            best = candidate
    return best or {
        'decoded_text': '',
        'encoding_used': forced_encoding or ENCODING_CHAIN[0],
        'replacement_stats': {'replacement_count': 0, 'replacement_ratio': 0.0},
    }


def decode_text_chunk(chunk: bytes, forced_encoding: str | None = None) -> dict:
    decoded = decode_chunk_with_fallback(chunk, forced_encoding=forced_encoding)
    return {
        'raw_text': decoded['raw_text'],
        'text': decoded['decoded_text'],
        'encoding_used': decoded['encoding_used'],
        'decode_quality': decoded['replacement_stats'],
    }


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


def export_strings(combined: bytes, offsets: list[int], forced_encoding: str | None = None) -> list[dict]:
    def _decode_segment(segment: bytes) -> dict:
        decoded = decode_chunk_with_fallback(segment, forced_encoding=forced_encoding)
        return {
            'text': decoded['decoded_text'],
            'raw_text': decoded['raw_text'],
            'encoding_used': decoded['encoding_used'],
            'replacement_stats': decoded['replacement_stats'],
            'decode_quality': decoded['replacement_stats'],
        }

    strings = []
    last = 0
    for end in offsets:
        if 0 <= last <= end <= len(combined):
            strings.append(_decode_segment(combined[last:end]))
            last = end
    if last < len(combined):
        strings.append(_decode_segment(combined[last:]))
    return [entry for entry in strings if entry['text'].strip()]


def decode_text(jar: Path, output: Path, strings_encoding: str | None = None) -> dict:
    project = JarProject(jar, output)
    project.load()
    container = project.containers['t0']
    out_dir = output / 'extracted' / 'text'
    ensure_dir(out_dir)
    result = {'chunks': []}
    for idx, chunk in enumerate(container.payloads):
        full_chunk = decode_text_chunk(chunk, forced_encoding=strings_encoding)
        decoded = full_chunk['text']
        before_metrics = text_metrics(full_chunk['raw_text'], segment_count=1)
        after_metrics = text_metrics(decoded, segment_count=1)
        full_path = out_dir / f't0_{idx:02d}_full.txt'
        full_path.write_text(decoded, encoding='utf-8')
        entry = {
            'chunk_index': idx,
            'char_length': len(decoded),
            'path': str(full_path.relative_to(output)),
            'encoding_used': full_chunk['encoding_used'],
            'decode_quality': full_chunk['decode_quality'],
        }
        guess = guess_offset_table(chunk)
        if guess:
            offsets = [u32le(chunk, guess['start'] + i * 4) for i in range(guess['count'])]
            combined = chunk[:guess['start']] + chunk[guess['blob_start']:]
            strings = export_strings(combined, offsets, forced_encoding=strings_encoding)
            guessed = out_dir / f't0_{idx:02d}_segments_guess.json'
            write_json(guessed, {'chunk_index': idx, 'offset_table_guess': guess, 'strings': strings})
            reconstructed = out_dir / f't0_{idx:02d}_reconstructed.txt'
            reconstructed.write_text('\n'.join(item['text'] for item in strings) + '\n', encoding='utf-8')
            entry['segment_guess_path'] = str(guessed.relative_to(output))
            entry['reconstructed_path'] = str(reconstructed.relative_to(output))
            entry['segment_guess_count'] = len(strings)
            before_metrics = text_metrics('\n'.join(item['raw_text'] for item in strings), segment_count=guess['count'])
            after_metrics = text_metrics('\n'.join(item['text'] for item in strings), segment_count=len(strings))
        integrity_path = out_dir / f't0_{idx:02d}_integrity.json'
        integrity_report = build_integrity_report(before_metrics, after_metrics)
        write_json(integrity_path, integrity_report)
        entry['integrity_path'] = str(integrity_path.relative_to(output))
        entry['integrity_status'] = integrity_report['status']
        result['chunks'].append(entry)
    write_json(out_dir / 'index.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode t0 text container')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    parser.add_argument('--strings-encoding', choices=ENCODING_CHAIN, help='Force encoding for t0 text chunks')
    args = parser.parse_args()
    decode_text(args.jar, args.output, strings_encoding=args.strings_encoding)


if __name__ == '__main__':
    main()
