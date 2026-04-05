# Game

Offline extractor for `240x320-rus-zombie-infection.jar`.

## Usage

```bash
python3 offline_extractor.py 240x320-rus-zombie-infection.jar
```

Equivalent modular entrypoints are available under `tools/`:

```bash
python3 -m tools.extract_zombie_infection 240x320-rus-zombie-infection.jar
python3 -m tools.parse_packs 240x320-rus-zombie-infection.jar
python3 -m tools.decode_text_t0 240x320-rus-zombie-infection.jar
python3 -m tools.decode_audio_m13 240x320-rus-zombie-infection.jar
python3 -m tools.decode_graphics 240x320-rus-zombie-infection.jar
python3 -m tools.decode_maps 240x320-rus-zombie-infection.jar
python3 -m tools.linker 240x320-rus-zombie-infection.jar
```

By default, the extractor writes to `.artifacts/extractor_out/`, which is gitignored so generated binaries, PNGs, MIDI files, and JSON dumps do not end up in pull requests. Use `-o <dir>` if you want a different output location.

## GitHub guide

- Подробное объяснение экстрактора на русском для чтения прямо в GitHub: [`docs/github_explanations_ru.md`](docs/github_explanations_ru.md)
- Документ оформлен как интерактивная навигация по архитектуре, функциям и выходным артефактам, чтобы код было легче читать через GitHub UI.

## What the extractor produces

- raw chunk dumps for all `m*` / `t0` containers under `chunks/`;
- corrected `t0` text exports under `extracted/text/`;
- recovered MIDI files and documented raw audio cues under `extracted/audio/`;
- tile / collision map previews and per-pack metadata under `extracted/maps/`;
- research previews for `m3_0`, `m4_0`, `m11_0`, `m11_1` under `extracted/images/research/`;
- reverse-engineering notes plus the requested chapter/mission summary table under `docs/reverse_engineering/`;
- machine-readable `summary.json` tying the above artifacts together.
- chapter dependency matrix in JSON/Markdown (`chapter_matrix.json`, `chapter_matrix.md`) with direct/inferred links and cross-check status.

`chunks/containers.json` stores per-chunk metadata with exact hash fields:

- `crc32_hex`: 8-character lowercase CRC32 checksum of raw chunk bytes.
- `sha1`: full 40-character SHA-1 digest computed as `hashlib.sha1(chunk).hexdigest()`.

## Repository policy

Generated extractor output is intentionally **not committed** to this repository. Run the extractor locally or in CI/GitHub artifacts when you need the binary dumps and derived previews.

## Iteration 1 coverage

This first pass implements:

- parser for `m*` and `t0` containers;
- text extractor for `t0`;
- audio extractor for `m13_1` and `m13_2`;
- research decoders for graphics packs `m3_0`, `m4_0`, `m11_0`, `m11_1`;
- parsers for level / script packs `m8`, `m9`, `m10`;
- parsers for tile / collision packs `m6_0..m6_5`.
