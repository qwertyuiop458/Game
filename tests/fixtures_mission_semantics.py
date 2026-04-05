from __future__ import annotations

SAMPLE_M9_CHUNK0 = bytes(
    [
        2, 5, 12, 0,  # mission 0
        4, 9, 6, 0,  # mission 1
        1, 11, 3, 0,  # mission 2
        0, 13, 8, 0,  # mission 3
        5, 15, 2, 0,  # mission 4
    ]
)

EXPECTED_MISSION_ROWS = [
    {'mission_id': 0, 'mission': 0, 'level_index': 0, 'chapter': 2, 'script_chunk': 15, 'script_subchunk_index': 5, 'map_pack_name': 'm6_2', 'map_subchunk': 12, 'm8_script_index': 0},
    {'mission_id': 1, 'mission': 1, 'level_index': 1, 'chapter': 4, 'script_chunk': 19, 'script_subchunk_index': 9, 'map_pack_name': 'm6_4', 'map_subchunk': 6, 'm8_script_index': 1},
    {'mission_id': 2, 'mission': 2, 'level_index': 2, 'chapter': 1, 'script_chunk': 21, 'script_subchunk_index': 11, 'map_pack_name': 'm6_1', 'map_subchunk': 3, 'm8_script_index': 2},
    {'mission_id': 3, 'mission': 3, 'level_index': 3, 'chapter': 0, 'script_chunk': 23, 'script_subchunk_index': 13, 'map_pack_name': 'm6_0', 'map_subchunk': 8, 'm8_script_index': 3},
    {'mission_id': 4, 'mission': 4, 'level_index': 4, 'chapter': 5, 'script_chunk': 25, 'script_subchunk_index': 15, 'map_pack_name': 'm6_5', 'map_subchunk': 2, 'm8_script_index': 4},
]
