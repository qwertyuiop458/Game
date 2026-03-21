# Game

Offline extractor for `240x320-rus-zombie-infection.jar`.

## Usage

### Full pipeline

```bash
python3 tools/extract_zombie_infection.py 240x320-rus-zombie-infection.jar
```

### Compatibility wrapper

```bash
python3 offline_extractor.py 240x320-rus-zombie-infection.jar
```

By default, the extractor writes to `.artifacts/extractor_out/`, which is gitignored so generated binaries, PNGs, MIDI files, and JSON dumps do not end up in pull requests. Use `-o <dir>` if you want a different output location.

## Tooling layout

The reverse-engineering pipeline is split into dedicated tools:

- `tools/parse_packs.py` — generic `m*` / `t0` container parser with relative-offset handling;
- `tools/decode_text_t0.py` — `t0` text recovery and segmented exports;
- `tools/decode_audio_m13.py` — `m13_1` / `m13_2` MIDI and raw cue extraction;
- `tools/decode_graphics.py` — graphics metadata parser based on `a.class`, plus palette/atlas candidate exports for `m3_0`, `m4_0`, `m7`, `m11_0`, `m11_1`;
- `tools/decode_maps.py` — `m6_*`, `m8`, `m9`, `m10` map/script analysis and final chapter table;
- `tools/extract_zombie_infection.py` — orchestrates the full extraction run.

## What the extractor produces

- raw chunk dumps for all `m*` / `t0` containers under `chunks/`;
- corrected `t0` text exports under `extracted/text/`;
- recovered MIDI files and documented raw audio cues under `extracted/audio/`;
- UI exports (`icon.png`, `dataIGP`, engine classes) under `extracted/ui/`;
- graphics metadata, palette previews, region maps, and candidate atlas decodes under `extracted/images/`, `extracted/sprites/`, and `extracted/tiles/`;
- tile / collision previews and script summaries under `extracted/maps/`;
- final chapter/mission linkage table under `extracted/maps/final_asset_table.*`;
- machine-readable `summary.json` tying the above artifacts together.

## Repository policy

Generated extractor output is intentionally **not committed** to this repository. Run the extractor locally or in CI/GitHub artifacts when you need the binary dumps and derived previews.
