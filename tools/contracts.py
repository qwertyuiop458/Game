from __future__ import annotations

from typing import Any


class ContractValidationError(ValueError):
    """Raised when a payload violates a required contract invariant."""


def to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def to_bounded_float(value: Any, *, minimum: float, maximum: float, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def ensure_required_blocks(payload: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    for key, default_value in defaults.items():
        if key not in payload:
            payload[key] = default_value
    return payload


def normalize_audio_coverage(raw: Any) -> dict[str, int | float]:
    data = raw if isinstance(raw, dict) else {}
    total_tracks = to_non_negative_int(data.get('total_tracks', 0))
    decoded_tracks = min(to_non_negative_int(data.get('decoded_tracks', 0)), total_tracks)
    coverage_percent = to_bounded_float(data.get('coverage_percent', 0.0), minimum=0.0, maximum=100.0)
    return {
        'total_tracks': total_tracks,
        'decoded_tracks': decoded_tracks,
        'coverage_percent': coverage_percent,
    }


def normalize_midi_validation_summary(raw: Any) -> dict[str, int]:
    data = raw if isinstance(raw, dict) else {}
    total = to_non_negative_int(data.get('total', 0))
    valid = min(to_non_negative_int(data.get('valid', 0)), total)
    invalid = min(to_non_negative_int(data.get('invalid', 0)), total)
    warnings = to_non_negative_int(data.get('warnings', 0))
    return {
        'total': total,
        'valid': valid,
        'invalid': invalid,
        'warnings': warnings,
    }


def normalize_map_mismatch_summary(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    total_maps = to_non_negative_int(data.get('total_maps', 0))
    maps_validation_passed = to_non_negative_int(data.get('maps_validation_passed', 0))
    maps_validation_failed = to_non_negative_int(data.get('maps_validation_failed', 0))
    mismatched_maps = to_non_negative_int(data.get('mismatched_maps', maps_validation_failed))

    details: list[dict[str, Any]] = []
    raw_details = data.get('mismatch_details')
    if isinstance(raw_details, list):
        for item in raw_details:
            entry = item if isinstance(item, dict) else {}
            details.append(
                {
                    'pack': str(entry.get('pack', '')),
                    'chunk': to_non_negative_int(entry.get('chunk', 0)),
                    'expected': entry.get('expected') if isinstance(entry.get('expected'), dict) else {},
                    'actual': entry.get('actual') if isinstance(entry.get('actual'), dict) else {},
                    'severity': str(entry.get('severity', 'unknown')),
                    'message': str(entry.get('message', '')),
                }
            )

    if total_maps == 0:
        total_maps = maps_validation_passed + maps_validation_failed
    maps_validation_passed = min(maps_validation_passed, total_maps)
    maps_validation_failed = min(maps_validation_failed, total_maps)
    mismatched_maps = min(mismatched_maps, total_maps)

    return {
        'total_maps': total_maps,
        'mismatched_maps': mismatched_maps,
        'mismatch_details': details,
        'maps_validation_passed': maps_validation_passed,
        'maps_validation_failed': maps_validation_failed,
    }


def normalize_chapter_matrix_cross_check(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    total_refs = to_non_negative_int(data.get('total_refs', 0))
    valid_refs = min(to_non_negative_int(data.get('valid_refs', 0)), total_refs)
    confidence_raw = data.get('valid_confidence_totals') if isinstance(data.get('valid_confidence_totals'), dict) else {}

    conflict_summary = data.get('conflict_summary') if isinstance(data.get('conflict_summary'), dict) else {}
    by_type_raw = conflict_summary.get('by_type') if isinstance(conflict_summary.get('by_type'), dict) else {}

    return {
        'total_refs': total_refs,
        'valid_refs': valid_refs,
        'valid_confidence_totals': {
            'direct': to_non_negative_int(confidence_raw.get('direct', 0)),
            'inferred': to_non_negative_int(confidence_raw.get('inferred', 0)),
            'unknown': to_non_negative_int(confidence_raw.get('unknown', 0)),
        },
        'invalid_refs': data.get('invalid_refs') if isinstance(data.get('invalid_refs'), list) else [],
        'dropped_invalid_refs': data.get('dropped_invalid_refs') if isinstance(data.get('dropped_invalid_refs'), list) else [],
        'conflict_summary': {
            'total_conflicts': to_non_negative_int(conflict_summary.get('total_conflicts', 0)),
            'by_type': {str(key): to_non_negative_int(value) for key, value in by_type_raw.items()},
        },
    }


def normalize_linker_conflicts_summary(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    total_conflicts = to_non_negative_int(data.get('total_conflicts', 0))
    blocking_conflicts = min(to_non_negative_int(data.get('blocking_conflicts', 0)), total_conflicts)
    conflicts_raw = data.get('conflicts') if isinstance(data.get('conflicts'), list) else []
    conflicts = [entry if isinstance(entry, dict) else {'value': str(entry)} for entry in conflicts_raw]
    return {
        'total_conflicts': total_conflicts,
        'blocking_conflicts': blocking_conflicts,
        'conflicts': conflicts,
    }
