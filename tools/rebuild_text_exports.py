from __future__ import annotations

import argparse
import re
from pathlib import Path


def _score_text(text: str) -> float:
    non_space = [ch for ch in text if not ch.isspace()]
    if not non_space:
        return 0.0
    cyr = sum(('а' <= ch.lower() <= 'я') or ch.lower() == 'ё' for ch in non_space)
    letters = sum(ch.isalpha() for ch in non_space)
    replacement = text.count('�')
    mojibake_markers = text.count('Г')
    return (cyr * 2 + letters) / len(non_space) - replacement * 3 - mojibake_markers * 0.1


def _demojibake_candidates(text: str) -> list[str]:
    candidates = [text]

    transforms = [
        lambda s: s.encode('cp1251', errors='ignore').decode('utf-8', errors='ignore'),
        lambda s: s.encode('latin-1', errors='ignore').decode('cp1251', errors='ignore'),
        lambda s: s.encode('latin-1', errors='ignore').decode('utf-8', errors='ignore'),
        lambda s: s.encode('cp866', errors='ignore').decode('utf-8', errors='ignore'),
        lambda s: s.encode('utf-16-le', errors='ignore').decode('utf-8', errors='ignore'),
    ]

    frontier = [text]
    seen = {text}
    for _ in range(2):
        next_frontier: list[str] = []
        for base in frontier:
            for transform in transforms:
                try:
                    decoded = transform(base)
                except Exception:
                    continue
                if decoded and decoded not in seen:
                    seen.add(decoded)
                    candidates.append(decoded)
                    next_frontier.append(decoded)
        frontier = next_frontier

    return candidates


def repair_text(text: str) -> str:
    best = max(_demojibake_candidates(text), key=_score_text)
    return best.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True

    if len(stripped) == 1 and not stripped.isalnum():
        return True

    chars = [ch for ch in stripped if not ch.isspace()]
    if not chars:
        return True

    letters = sum(ch.isalpha() for ch in chars)
    cyr = sum(('а' <= ch.lower() <= 'я') or ch.lower() == 'ё' for ch in chars)
    digits = sum(ch.isdigit() for ch in chars)
    punctuation = sum(not ch.isalnum() for ch in chars)

    if letters == 0 and digits == 0:
        return True
    if letters > 0 and cyr == 0 and letters < 3 and punctuation > letters:
        return True
    if punctuation / len(chars) > 0.65 and cyr == 0:
        return True

    return False


def _merge_fragments(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        line = re.sub(r'\s+', ' ', line).strip()
        if not line:
            continue

        if merged:
            prev = merged[-1]
            prev_end = prev[-1]
            cur_start = line[0]
            looks_cut = (
                prev_end.isalpha()
                and prev_end.lower() not in {'й', 'ь', 'ъ'}
                and cur_start.isalpha()
                and not prev.endswith(('...', '…'))
                and len(prev) < 140
                and len(line) < 60
            )
            if looks_cut:
                merged[-1] = prev + line
                continue

        merged.append(line)
    return merged


def collect_lines(text_dir: Path) -> tuple[list[tuple[str, list[str]]], list[str]]:
    files = sorted(text_dir.glob('t0_*_full.txt'))
    per_file: list[tuple[str, list[str]]] = []
    all_lines: list[str] = []

    for path in files:
        raw = path.read_text(encoding='utf-8', errors='ignore')
        fixed = repair_text(raw)
        parts = [x.strip() for x in re.split(r'%(?:n|j|p\d?)|\n+', fixed) if x.strip()]
        parts = _merge_fragments(parts)
        parts = [line for line in parts if not _is_noise(line)]
        per_file.append((path.name, parts))
        all_lines.extend(parts)

    return per_file, all_lines


def write_structured(path: Path, per_file: list[tuple[str, list[str]]], all_lines: list[str]) -> None:
    unique_sorted = sorted(set(all_lines), key=lambda s: (s.casefold(), s))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fh:
        fh.write('Zombie Infection (RU) — полный структурированный текст (cleaned)\n')
        fh.write(f'Файлов: {len(per_file)}\n')
        fh.write(f'Строк после нормализации: {len(all_lines)}\n')
        fh.write(f'Уникальных строк: {len(unique_sorted)}\n\n')
        fh.write('===== SECTION 1: STRUCTURED BY SOURCE (t0_full chunks) =====\n\n')
        for name, lines in per_file:
            fh.write(f'--- {name} | lines={len(lines)} ---\n')
            for i, line in enumerate(lines, start=1):
                fh.write(f'{i:04d}. {line}\n')
            fh.write('\n')
        fh.write('===== SECTION 2: GLOBAL UNIQUE SORTED LINES (cleaned) =====\n\n')
        for i, line in enumerate(unique_sorted, start=1):
            fh.write(f'{i:05d}. {line}\n')


def write_restored(path: Path, per_file: list[tuple[str, list[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fh:
        for name, lines in per_file:
            fh.write(f'[{name}]\n')
            for line in lines:
                fh.write(f'{line}\n')
            fh.write('\n')


def main() -> None:
    parser = argparse.ArgumentParser(description='Rebuild cleaned text exports from extracted t0_full chunks')
    parser.add_argument('text_dir', type=Path, help='Directory with extracted text files (t0_*_full.txt)')
    parser.add_argument('--structured-out', type=Path, default=Path('docs/text_exports/t0_all_structured_sorted.txt'))
    parser.add_argument('--restored-out', type=Path, default=Path('docs/text_exports/t0_all_restored_plain.txt'))
    args = parser.parse_args()

    per_file, all_lines = collect_lines(args.text_dir)
    write_structured(args.structured_out, per_file, all_lines)
    write_restored(args.restored_out, per_file)


if __name__ == '__main__':
    main()
