from tools.m9_semantics import build_chapter_mission_links, parse_m9_chunk_tables


def test_build_chapter_mission_links_from_chunk0_levels() -> None:
    tables = parse_m9_chunk_tables([bytes([7, 4, 9, 0, 1, 2, 3, 0])])
    links = build_chapter_mission_links(tables, chapter_count=6)
    assert links['levels_total'] == 2
    first = links['mission_links'][0]
    assert first['chapter'] == 1
    assert first['script_chunk'] == 14
    assert first['map_subchunk'] == 9
