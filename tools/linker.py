from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from tools.common import CHAPTER_COUNT, JarProject, detect_m6_chapter_count, ensure_dir, write_json
from tools.script_parser import parse_m9_chunk_tables, parse_script_chunk_semantic, resolve_level_trace

CONFIDENCE_VALUES = ('direct', 'inferred', 'unknown')


def _classify_confidence(source: str) -> str:
    if source in ('structure', 'script'):
        return 'direct'
    if source == 'heuristic':
        return 'inferred'
    return 'unknown'


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
        confidence = entry.get('confidence')
        if confidence not in CONFIDENCE_VALUES:
            entry['confidence'] = 'unknown'
        ok, error = _validate_reference(project, entry['ref'])
        if ok:
            valid_entries.append(entry)
        else:
            dropped_bucket.append({'entry': entry, 'error': error})
    return valid_entries


def _ref_id(ref: dict[str, Any]) -> str:
    chunk = ref.get('chunk_index')
    return f"{ref['container']}#{chunk if chunk is not None else '*'}"


def _extract_chapter_from_ref(ref: dict[str, Any], chapter_count: int) -> int | None:
    container_name = str(ref.get('container', ''))
    if container_name.startswith('m6_'):
        tail = container_name.split('_', 1)[1]
        if tail.isdigit():
            chapter = int(tail)
            if 0 <= chapter < chapter_count:
                return chapter
    if container_name == 'm9':
        chunk = ref.get('chunk_index')
        if isinstance(chunk, int):
            candidate = chunk - 10
            if 0 <= candidate < chapter_count:
                return candidate
    return None


def _detect_conflicts(rows: list[dict[str, Any]], chapter_count: int) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    claims_by_entity: dict[str, list[dict[str, Any]]] = {}
    graph_edges: dict[int, set[int]] = {}
    exclusive_kinds = {'map_pack', 'm6_subchunk_semantic', 'm9_script_chunk_semantic'}

    for row in rows:
        chapter = int(row['chapter'])
        all_entries = [('direct', entry) for entry in row.get('direct_refs', [])] + [('inferred', entry) for entry in row.get('inferred_refs', [])]
        direct_entries = row.get('direct_refs', [])

        # duplicate refs in chapter (same kind + target) regardless of source confidence
        chapter_dupes: dict[tuple[str, str], int] = {}
        for _source, entry in all_entries:
            key = (str(entry.get('kind', 'unknown')), _ref_id(entry['ref']))
            chapter_dupes[key] = chapter_dupes.get(key, 0) + 1
        for (kind, ref_key), count in sorted(chapter_dupes.items()):
            if count > 1:
                conflicts.append(
                    {
                        'type': 'cycles_or_duplicates',
                        'participants': {
                            'chapter': chapter,
                            'kind': kind,
                            'entity': ref_key,
                            'duplicate_count': count,
                        },
                        'explanation': f'Chapter {chapter} contains duplicated {kind} assignment for {ref_key} ({count} occurrences).',
                    }
                )

        map_pack_targets = {entry['ref']['container'] for entry in direct_entries if entry.get('kind') == 'map_pack'}
        semantic_m6_targets = {
            entry['ref']['container']
            for entry in direct_entries
            if entry.get('kind') in ('m6_subchunk_semantic', 'm9_command_m6_semantic')
        }
        if map_pack_targets and semantic_m6_targets and map_pack_targets != semantic_m6_targets:
            conflicts.append(
                {
                    'type': 'incompatible_truth_sources',
                    'participants': {
                        'chapter': chapter,
                        'map_pack_targets': sorted(map_pack_targets),
                        'semantic_targets': sorted(semantic_m6_targets),
                    },
                    'explanation': (
                        f'Chapter {chapter} has map-pack naming targets {sorted(map_pack_targets)} '
                        f'but semantic script links target {sorted(semantic_m6_targets)}.'
                    ),
                }
            )

        for entry in direct_entries:
            ref = entry['ref']
            ref_key = _ref_id(ref)
            target_chapter = _extract_chapter_from_ref(ref, chapter_count=chapter_count)
            if target_chapter is not None and target_chapter != chapter:
                graph_edges.setdefault(chapter, set()).add(target_chapter)

            if entry.get('kind') in exclusive_kinds:
                claims_by_entity.setdefault(ref_key, []).append(
                    {
                        'chapter': chapter,
                        'kind': entry.get('kind'),
                        'confidence': entry.get('confidence'),
                    }
                )

    # competing assignments: same exclusive entity assigned by multiple chapters
    for entity, claims in sorted(claims_by_entity.items()):
        chapters = sorted({int(claim['chapter']) for claim in claims})
        if len(chapters) > 1:
            conflicts.append(
                {
                    'type': 'competing_assignments',
                    'participants': {
                        'entity': entity,
                        'chapters': chapters,
                        'claims': claims,
                    },
                    'explanation': f'Entity {entity} has competing direct chapter assignments: {chapters}.',
                }
            )

    # cycles between chapters inferred from chapter -> chapter semantic edges
    for src in sorted(graph_edges):
        for dst in sorted(graph_edges[src]):
            if src < dst and src in graph_edges.get(dst, set()):
                conflicts.append(
                    {
                        'type': 'cycles_or_duplicates',
                        'participants': {
                            'edge_a': [src, dst],
                            'edge_b': [dst, src],
                        },
                        'explanation': f'Cycle detected between chapter {src} and chapter {dst} in semantic cross-links.',
                    }
                )

    return conflicts


def _cross_check_source_conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        chapter = int(row['chapter'])
        chapter_key = str(row.get('chapter_key', f'chapter_{chapter}'))
        assignments: dict[str, set[str]] = {
            'maps': {entry['ref']['container'] for entry in row.get('direct_refs', []) if entry.get('kind') == 'map_pack'},
            'scripts': {
                entry['ref']['container']
                for entry in row.get('direct_refs', [])
                if entry.get('kind') in ('m6_subchunk_semantic', 'm9_command_m6_semantic')
            },
            'text_metadata': {f'm6_{chapter}'},
        }
        source_pairs = (('maps', 'scripts'), ('maps', 'text_metadata'), ('scripts', 'text_metadata'))
        for source_a, source_b in source_pairs:
            targets_a = sorted(assignments[source_a])
            targets_b = sorted(assignments[source_b])
            if not targets_a or not targets_b or targets_a == targets_b:
                continue
            conflicts.append(
                {
                    'entity': chapter_key,
                    'source_a': {'name': source_a, 'targets': targets_a},
                    'source_b': {'name': source_b, 'targets': targets_b},
                    'conflict_type': 'chapter_target_mismatch',
                    'suggested_resolution': (
                        'Сверить m9 semantic links и m6 chapter pack; '
                        'для приоритета использовать script-derived связи при наличии подтверждённых команд.'
                    ),
                }
            )
            break
    return conflicts


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
    all_candidate_entries: list[dict[str, Any]] = []
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
        has_confirmed_level_matches = bool(level_matches)
        if not level_matches:
            level_matches = [{'level_index': chapter, 'map_subchunk_hint': 0, 'script_subchunk_hint': chapter}]
        resolved_traces = [resolve_level_trace(int(item.get('level_index', chapter)), m9_tables) for item in level_matches]
        row['script_chunks'] = {
            'm8': sorted({f"m8#{trace.level_index:02d}" for trace in resolved_traces}) if m8_container else [],
            'm9': sorted({f"m9#{trace.script_chunk:02d}" for trace in resolved_traces}) if m9_container else [],
        }

        # Primary links from semantic script/map relations.
        direct_candidates = [
            {
                'kind': 'map_pack',
                'ref': _build_reference(f'm6_{chapter}'),
                'confidence': _classify_confidence('structure'),
                'reason': 'chapter pack naming m6_<chapter>',
            },
        ]
        for level_entry in level_matches:
            level_index = int(level_entry.get('level_index', chapter))
            trace = resolve_level_trace(level_index, m9_tables)
            direct_candidates.append(
                {
                    'kind': 'm9_script_chunk_semantic',
                    'ref': _build_reference('m9', trace.script_chunk),
                    'confidence': _classify_confidence('script'),
                    'reason': f'level {level_index} resolved by m9 chunk0 + 10+level/subchunk rule',
                }
            )
            direct_candidates.append(
                {
                    'kind': 'm6_subchunk_semantic',
                    'ref': _build_reference(f'm6_{trace.chapter}', trace.map_subchunk),
                    'confidence': _classify_confidence('script'),
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
                                'confidence': _classify_confidence('script'),
                                'reason': f"m9#{trace.script_chunk:02d} opcode {item['opcode']} offset 0x{item['offset']:x}",
                                'source': {'level_index': level_index, 'm9_chunk': trace.script_chunk, 'offset': item['offset']},
                            }
                        )
                    if link.get('target') == 'm6':
                        direct_candidates.append(
                            {
                                'kind': 'm9_command_m6_semantic',
                                'ref': _build_reference(str(link['pack']), int(link['subchunk'])),
                                'confidence': _classify_confidence('script'),
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
                    'confidence': _classify_confidence('heuristic'),
                    'reason': 'global graphics pack reused across chapters',
                }
            )
        for cue in row['audio_cues']['midi_ids']:
            container_name, chunk_str = cue.split('#', 1)
            inferred_candidates.append(
                {
                    'kind': 'audio_midi',
                    'ref': _build_reference(container_name, int(chunk_str)),
                    'confidence': _classify_confidence('heuristic'),
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
                    'confidence': _classify_confidence('heuristic'),
                    'reason': 'chapter-wise even partition of raw cue chunks',
                    'cue_id': cue,
                }
            )

        if not has_confirmed_level_matches:
            direct_candidates.append(
                {
                    'kind': 'script_trace_unconfirmed',
                    'ref': _build_reference('m9', 10 + chapter if m9_container else None),
                    'confidence': _classify_confidence('unconfirmed'),
                    'reason': 'fallback level trace used without chapter-specific evidence',
                }
            )

        row['direct_refs'] = _keep_valid_refs(project, direct_candidates, dropped_invalid_refs)
        row['inferred_refs'] = _keep_valid_refs(project, inferred_candidates, dropped_invalid_refs)
        row['map_pack_candidates'] = {
            'direct_refs': [entry for entry in row['direct_refs'] if entry['kind'] in ('map_pack', 'm6_subchunk_semantic', 'm9_command_m6_semantic')],
            'inferred_refs': [entry for entry in row['inferred_refs'] if entry['kind'] == 'graphics_pack'],
        }

        rows.append(row)
        all_candidate_entries.extend(direct_candidates)
        all_candidate_entries.extend(inferred_candidates)
        all_refs.extend([entry['ref'] for entry in direct_candidates])
        all_refs.extend([entry['ref'] for entry in inferred_candidates])

    structural_conflicts = _detect_conflicts(rows, chapter_count=chapter_count)
    source_conflicts = _cross_check_source_conflicts(rows)
    conflict_counts: dict[str, int] = {}
    for conflict in source_conflicts:
        conflict_type = str(conflict.get('conflict_type', 'unknown'))
        conflict_counts[conflict_type] = conflict_counts.get(conflict_type, 0) + 1

    cross_check = {
        'total_refs': len(all_refs),
        'valid_refs': 0,
        'valid_confidence_totals': {key: 0 for key in CONFIDENCE_VALUES},
        'invalid_refs': [],
        'dropped_invalid_refs': dropped_invalid_refs,
        'conflict_summary': {
            'total_conflicts': len(source_conflicts),
            'by_type': conflict_counts,
        },
    }
    for entry in all_candidate_entries:
        ref = entry['ref']
        valid, error = _validate_reference(project, ref)
        if valid:
            cross_check['valid_refs'] += 1
            confidence = entry.get('confidence', 'unknown')
            if confidence not in CONFIDENCE_VALUES:
                confidence = 'unknown'
            cross_check['valid_confidence_totals'][confidence] += 1
        else:
            cross_check['invalid_refs'].append({'ref': ref, 'error': error, 'confidence': entry.get('confidence', 'unknown')})

    matrix = {
        'chapters': rows,
        'cross_check': cross_check,
        'conflicts': structural_conflicts,
        'link_conflicts': source_conflicts,
        'linker_conflicts_summary': {
            'total_conflicts': len(source_conflicts),
            'blocking_conflicts': len(source_conflicts),
            'conflicts': source_conflicts,
        },
    }
    json_path = docs_dir / 'chapter_matrix.json'
    conflicts_path = docs_dir / 'link_conflicts.json'
    md_path = docs_dir / 'chapter_matrix.md'
    write_json(json_path, matrix)
    write_json(
        conflicts_path,
        {
            'conflicts': source_conflicts,
            'summary': cross_check['conflict_summary'],
        },
    )

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
            f"{entry['kind']} → {entry['ref']['container']}#{entry['ref']['chunk_index'] if entry['ref']['chunk_index'] is not None else '*'} "
            f"(confidence={entry.get('confidence', 'unknown')})"
            for entry in row['direct_refs']
        )
        inferred_col = '<br>'.join(
            f"{entry['kind']} → {entry['ref']['container']}#{entry['ref']['chunk_index'] if entry['ref']['chunk_index'] is not None else '*'} "
            f"(confidence={entry.get('confidence', 'unknown')})"
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
    lines.append('## Conflicts')
    lines.append(
        'Conflict summary: '
        f"{cross_check['conflict_summary']['total_conflicts']} total "
        f"({', '.join(f'{k}={v}' for k, v in sorted(cross_check['conflict_summary']['by_type'].items())) or 'none'})."
    )
    if source_conflicts:
        lines.append('| entity | conflict_type | source_a | source_b |')
        lines.append('| --- | --- | --- | --- |')
        for conflict in source_conflicts:
            left = f"{conflict['source_a']['name']}={','.join(conflict['source_a']['targets'])}"
            right = f"{conflict['source_b']['name']}={','.join(conflict['source_b']['targets'])}"
            lines.append(f"| {conflict['entity']} | {conflict['conflict_type']} | {left} | {right} |")
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
