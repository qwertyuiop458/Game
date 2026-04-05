from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from tools.common import CHAPTER_COUNT, JarProject, detect_m6_chapter_count, ensure_dir, write_json
from tools.script_parser import parse_m9_chunk_tables, parse_script_chunk_semantic, resolve_level_trace


def _map_entries(project: JarProject, chapter: int) -> list[dict[str, Any]]:
    container_name = f'm6_{chapter}'
    container = project.containers.get(container_name)
    if not container:
        return []
    maps: list[dict[str, Any]] = []
    for chunk_index in range(0, len(container.payloads), 2):
        collision_index = chunk_index + 1 if chunk_index + 1 < len(container.payloads) else None
        maps.append(
            {
                'map_chunk': f'{container_name}#{chunk_index:02d}',
                'tile_layer_chunk': f'{container_name}#{chunk_index:02d}',
                'collision_layer_chunk': f'{container_name}#{collision_index:02d}' if collision_index is not None else None,
            }
        )
    return maps


def _audio_entries(project: JarProject) -> tuple[list[str], list[str]]:
    midi: list[str] = []
    raw: list[str] = []
    for container_name in ('m13_1', 'm13_2'):
        container = project.containers.get(container_name)
        if not container:
            continue
        for idx, chunk in enumerate(container.payloads):
            cue_id = f'{container_name}#{idx:02d}'
            if b'MThd' in chunk:
                midi.append(cue_id)
            else:
                raw.append(cue_id)
    return midi, raw


def _partition_for_chapter(items: list[str], chapter: int, chapter_count: int = CHAPTER_COUNT) -> list[str]:
    if not items:
        return []
    block = max(1, (len(items) + chapter_count - 1) // chapter_count)
    start = chapter * block
    end = min(len(items), start + block)
    if start >= len(items):
        return []
    return items[start:end]


def _build_reference(container: str, chunk: int | None = None) -> dict[str, Any]:
    if chunk is None:
        return {'container': container, 'chunk_index': None}
    return {'container': container, 'chunk_index': int(chunk)}


def _validate_reference(project: JarProject, ref: dict[str, Any]) -> tuple[bool, str | None]:
    container_name = ref['container']
    chunk_index = ref['chunk_index']
    container = project.containers.get(container_name)
    if container is None:
        return False, f'container {container_name} missing'
    if chunk_index is None:
        return True, None
    if not (0 <= chunk_index < len(container.payloads)):
        return False, f'chunk {container_name}#{chunk_index:02d} missing'
    return True, None




def _keep_valid_refs(project: JarProject, refs: list[dict[str, Any]], dropped_bucket: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_entries: list[dict[str, Any]] = []
    for entry in refs:
        ok, error = _validate_reference(project, entry['ref'])
        if ok:
            valid_entries.append(entry)
        else:
            dropped_bucket.append({'entry': entry, 'error': error})
    return valid_entries

def build_chapter_matrix(jar: Path, output: Path) -> dict[str, Any]:
    project = JarProject(jar, output)
    project.load()
    chapter_count = detect_m6_chapter_count(project.containers, fallback=CHAPTER_COUNT)

    docs_dir = output / 'docs' / 'reverse_engineering'
    ensure_dir(docs_dir)

    midi_cues, raw_cues = _audio_entries(project)
    graphics_sets = [name for name in ('m3_0', 'm4_0', 'm11_0', 'm11_1') if name in project.containers]
    m8_container = project.containers.get('m8')
    m9_container = project.containers.get('m9')
    m9_tables = parse_m9_chunk_tables(m9_container.payloads) if m9_container else {'chunk0_levels': {'levels': []}}
    semantic_by_chunk: dict[int, dict[str, Any]] = {}
    if m9_container:
        for idx, payload in enumerate(m9_container.payloads):
            if idx >= 10:
                semantic_by_chunk[idx] = parse_script_chunk_semantic(payload)

    rows: list[dict[str, Any]] = []
    all_refs: list[dict[str, Any]] = []
    dropped_invalid_refs: list[dict[str, Any]] = []

    for chapter in range(chapter_count):
        chapter_key = f'chapter_{chapter}'
        row: dict[str, Any] = {
            'chapter': chapter,
            'level': chapter,
            'chapter_key': chapter_key,
            'direct_refs': [],
            'inferred_refs': [],
            'audio_cues': {
                'midi_ids': _partition_for_chapter(midi_cues, chapter, chapter_count=chapter_count),
                'raw_ids': _partition_for_chapter(raw_cues, chapter, chapter_count=chapter_count),
            },
            'maps': _map_entries(project, chapter),
            'graphics_sets': graphics_sets,
            'script_chunks': {
                'm8': f'm8#{chapter:02d}' if m8_container and chapter < len(m8_container.payloads) else None,
                'm9': f'm9#{10 + chapter:02d}' if m9_container and (10 + chapter) < len(m9_container.payloads) else None,
            },
        }

        level_matches = [
            row for row in m9_tables.get('chunk0_levels', {}).get('levels', []) if row.get('chapter_hint', 0) % chapter_count == chapter
        ]
        if not level_matches:
            level_matches = [{'level_index': chapter, 'map_subchunk_hint': 0, 'script_subchunk_hint': chapter}]
        resolved_traces = [resolve_level_trace(int(item.get('level_index', chapter)), m9_tables) for item in level_matches]
        row['script_chunks'] = {
            'm8': sorted({f"m8#{trace.level_index:02d}" for trace in resolved_traces}) if m8_container else [],
            'm9': sorted({f"m9#{trace.script_chunk:02d}" for trace in resolved_traces}) if m9_container else [],
        }

        # Primary links from semantic script/map relations.
        direct_candidates = [
            {'kind': 'map_pack', 'ref': _build_reference(f'm6_{chapter}'), 'confidence': 1.0, 'reason': 'chapter pack naming m6_<chapter>'},
        ]
        for level_entry in level_matches:
            level_index = int(level_entry.get('level_index', chapter))
            trace = resolve_level_trace(level_index, m9_tables)
            direct_candidates.append(
                {
                    'kind': 'm9_script_chunk_semantic',
                    'ref': _build_reference('m9', trace.script_chunk),
                    'confidence': 0.98,
                    'reason': f'level {level_index} resolved by m9 chunk0 + 10+level/subchunk rule',
                }
            )
            direct_candidates.append(
                {
                    'kind': 'm6_subchunk_semantic',
                    'ref': _build_reference(f'm6_{trace.chapter}', trace.map_subchunk),
                    'confidence': 0.9,
                    'reason': f'level {level_index} map_subchunk_hint from m9 chunk0',
                }
            )
            parsed = semantic_by_chunk.get(trace.script_chunk, {'commands': []})
            for item in parsed['commands']:
                for link in item.get('command_links', []):
                    if link.get('target') == 'm8':
                        direct_candidates.append(
                            {
                                'kind': 'm9_command_m8_semantic',
                                'ref': _build_reference('m8', int(link['subchunk_index'])),
                                'confidence': 0.9,
                                'reason': f"m9#{trace.script_chunk:02d} opcode {item['opcode']} offset 0x{item['offset']:x}",
                                'source': {'level_index': level_index, 'm9_chunk': trace.script_chunk, 'offset': item['offset']},
                            }
                        )
                    if link.get('target') == 'm6':
                        direct_candidates.append(
                            {
                                'kind': 'm9_command_m6_semantic',
                                'ref': _build_reference(str(link['pack']), int(link['subchunk'])),
                                'confidence': 0.82,
                                'reason': f"m9#{trace.script_chunk:02d} opcode {item['opcode']} offset 0x{item['offset']:x}",
                                'source': {'level_index': level_index, 'm9_chunk': trace.script_chunk, 'offset': item['offset']},
                            }
                        )

        inferred_candidates = []
        for g in graphics_sets:
            inferred_candidates.append(
                {
                    'kind': 'graphics_pack',
                    'ref': _build_reference(g),
                    'confidence': 0.72,
                    'reason': 'global graphics pack reused across chapters',
                }
            )
        for cue in row['audio_cues']['midi_ids']:
            container_name, chunk_str = cue.split('#', 1)
            inferred_candidates.append(
                {
                    'kind': 'audio_midi',
                    'ref': _build_reference(container_name, int(chunk_str)),
                    'confidence': 0.58,
                    'reason': 'chapter-wise even partition of discovered MIDI cues',
                    'cue_id': cue,
                }
            )
        for cue in row['audio_cues']['raw_ids']:
            container_name, chunk_str = cue.split('#', 1)
            inferred_candidates.append(
                {
                    'kind': 'audio_raw',
                    'ref': _build_reference(container_name, int(chunk_str)),
                    'confidence': 0.53,
                    'reason': 'chapter-wise even partition of raw cue chunks',
                    'cue_id': cue,
                }
            )

        row['direct_refs'] = _keep_valid_refs(project, direct_candidates, dropped_invalid_refs)
        row['inferred_refs'] = _keep_valid_refs(project, inferred_candidates, dropped_invalid_refs)
        row['map_pack_candidates'] = {
            'direct_refs': [entry for entry in row['direct_refs'] if entry['kind'] in ('map_pack', 'm6_subchunk_semantic', 'm9_command_m6_semantic')],
            'inferred_refs': [entry for entry in row['inferred_refs'] if entry['kind'] == 'graphics_pack'],
        }

        rows.append(row)
        all_refs.extend([entry['ref'] for entry in direct_candidates])
        all_refs.extend([entry['ref'] for entry in inferred_candidates])

    cross_check = {'total_refs': len(all_refs), 'valid_refs': 0, 'invalid_refs': [], 'dropped_invalid_refs': dropped_invalid_refs}
    for ref in all_refs:
        valid, error = _validate_reference(project, ref)
        if valid:
            cross_check['valid_refs'] += 1
        else:
            cross_check['invalid_refs'].append({'ref': ref, 'error': error})

    matrix = {'chapters': rows, 'cross_check': cross_check}
    json_path = docs_dir / 'chapter_matrix.json'
    md_path = docs_dir / 'chapter_matrix.md'
    write_json(json_path, matrix)

    headers = [
        'chapter',
        'level',
        'map/tile layers',
        'script chunks',
        'direct refs',
        'inferred refs',
        'audio_cues (MIDI/WAV)',
        'graphics sets',
    ]
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        map_cols = '<br>'.join(
            f"{m['map_chunk']} [tile={m['tile_layer_chunk']}, collision={m['collision_layer_chunk'] or '-'}]" for m in row['maps']
        ) or '-'
        scripts_flat: list[str] = []
        for value in row['script_chunks'].values():
            if isinstance(value, list):
                scripts_flat.extend(value)
            elif value:
                scripts_flat.append(value)
        scripts_col = ', '.join(scripts_flat) or '-'
        direct_col = '<br>'.join(
            f"{entry['kind']} → {entry['ref']['container']}#{entry['ref']['chunk_index'] if entry['ref']['chunk_index'] is not None else '*'} (c={entry['confidence']:.2f})"
            for entry in row['direct_refs']
        )
        inferred_col = '<br>'.join(
            f"{entry['kind']} → {entry['ref']['container']}#{entry['ref']['chunk_index'] if entry['ref']['chunk_index'] is not None else '*'} (c={entry['confidence']:.2f})"
            for entry in row['inferred_refs']
        )
        audio_col = (
            'MIDI: ' + (', '.join(row['audio_cues']['midi_ids']) or '-') + '<br>' +
            'RAW: ' + (', '.join(row['audio_cues']['raw_ids']) or '-')
        )
        graphics_col = ', '.join(row['graphics_sets']) or '-'
        lines.append(
            '| ' + ' | '.join(
                [
                    str(row['chapter']),
                    str(row['level']),
                    map_cols,
                    scripts_col,
                    direct_col,
                    inferred_col,
                    audio_col,
                    graphics_col,
                ]
            ) + ' |'
        )
    lines.append('')
    lines.append(f"Cross-check: {cross_check['valid_refs']}/{cross_check['total_refs']} references are valid and used in the matrix.")
    if cross_check['invalid_refs']:
        lines.append('Invalid references:')
        for item in cross_check['invalid_refs']:
            ref = item['ref']
            lines.append(f"- {ref['container']}#{ref['chunk_index']}: {item['error']}")
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description='Build chapter dependency matrix from m6/m8/m9/m3/m4/m11/m13 parser data')
    parser.add_argument('jar', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('.artifacts/extractor_out'))
    args = parser.parse_args()
    build_chapter_matrix(args.jar, args.output)


if __name__ == '__main__':
    main()
