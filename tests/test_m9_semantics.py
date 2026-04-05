from tools.m9_semantics import build_chapter_mission_links, parse_m9_chunk_tables
from tests.fixtures_mission_semantics import EXPECTED_MISSION_ROWS, SAMPLE_M9_CHUNK0


def test_build_chapter_mission_links_from_chunk0_levels() -> None:
    tables = parse_m9_chunk_tables([bytes([7, 4, 9, 0, 1, 2, 3, 0])])
    links = build_chapter_mission_links(tables, chapter_count=6)
    assert links['levels_total'] == 2
    first = links['mission_links'][0]
    assert first['chapter'] == 1
    assert first['script_chunk'] == 14
    assert first['map_subchunk'] == 9


def test_mission_field_mapping_for_known_examples_has_no_unknowns() -> None:
    tables = parse_m9_chunk_tables([SAMPLE_M9_CHUNK0])
    links = build_chapter_mission_links(tables, chapter_count=6)

    assert links['field_mappings']
    for expected, row in zip(EXPECTED_MISSION_ROWS, links['mission_links'], strict=True):
        for key, expected_value in expected.items():
            assert row[key] == expected_value
            assert row[key] != 'unknown'
