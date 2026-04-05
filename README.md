# Game

[![Tests](https://github.com/<OWNER>/<REPO>/actions/workflows/tests.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/tests.yml)

Offline extractor for `240x320-rus-zombie-infection.jar`.

## Usage

Primary entrypoint (recommended):

```bash
python3 -m tools.extract_zombie_infection 240x320-rus-zombie-infection.jar
```

Migration is complete: extraction logic lives in dedicated modules under `tools/`:

- `tools/parse_packs.py`
- `tools/decode_text_t0.py`
- `tools/decode_audio_m13.py`
- `tools/decode_graphics.py`
- `tools/decode_maps.py`
- `tools/extract_zombie_infection.py` (orchestrator)

`offline_extractor.py` is kept as a backward-compatible thin wrapper that calls the new orchestrator.

### New modular CLI

Supported launch modes for the full extractor (in priority order):

1. **Recommended**: module mode (stable imports in any working directory):

```bash
python3 -m tools.extract_zombie_infection 240x320-rus-zombie-infection.jar
```

2. Compatibility direct run (works from the repository root):

```bash
python3 tools/extract_zombie_infection.py 240x320-rus-zombie-infection.jar
```

Other modular entrypoints:

```bash
python3 -m tools.parse_packs 240x320-rus-zombie-infection.jar
python3 -m tools.decode_text_t0 240x320-rus-zombie-infection.jar
python3 -m tools.decode_audio_m13 240x320-rus-zombie-infection.jar
python3 -m tools.decode_graphics 240x320-rus-zombie-infection.jar
python3 -m tools.decode_maps 240x320-rus-zombie-infection.jar
python3 -m tools.linker 240x320-rus-zombie-infection.jar
```

Orchestrator command with explicit output directory:

```bash
python3 -m tools.extract_zombie_infection \
  240x320-rus-zombie-infection.jar \
  -o .artifacts/extractor_out
```

By default, the extractor writes to `.artifacts/extractor_out/`, which is gitignored so generated binaries, PNGs, MIDI files, and JSON dumps do not end up in pull requests. Use `-o <dir>` if you want a different output location.

## GitHub guide

- Подробное объяснение экстрактора на русском для чтения прямо в GitHub: [`docs/github_explanations_ru.md`](docs/github_explanations_ru.md)
- Текущий roadmap по статусу декодеров и ближайшим шагам: [`docs/roadmap_ru.md`](docs/roadmap_ru.md)
- Про reference-кейсы графического декодера и процесс осознанного обновления эталонов: [`docs/reference_cases.md`](docs/reference_cases.md)
- В начале документа явно указано, что `offline_extractor.py` — тонкий backward-compatible wrapper, а реальная точка входа пайплайна/CLI — `tools/extract_zombie_infection.py`.
- Документ оформлен как интерактивная навигация по архитектуре, функциям и выходным артефактам, чтобы код было легче читать через GitHub UI.

## Output directory layout (`-o <output_dir>`)

Top-level structure written by the orchestrator:

```text
<output_dir>/
├─ chunks/
│  ├─ containers.json
│  ├─ container_validation.json
│  └─ <pack>/<NN>.bin
├─ extracted/
│  ├─ audio/
│  ├─ images/
│  ├─ maps/
│  ├─ meta/
│  ├─ sprites/
│  ├─ text/
│  ├─ tiles/
│  └─ ui/
├─ images/
│  └─ decoded/
├─ docs/
│  └─ reverse_engineering/
│     ├─ chapter_matrix.json               # generated at runtime
│     ├─ chapter_matrix.md                 # generated at runtime
│     ├─ chapter_mission_matrix.json       # generated at runtime
│     └─ final_asset_table.{json,md}       # generated at runtime
├─ summary.json
└─ ...
```

## What the extractor produces

- raw chunk dumps for all `m*` / `t0` containers under `chunks/`;
- corrected `t0` text exports under `extracted/text/`;
- recovered MIDI files and documented raw audio cues under `extracted/audio/`;
- tile / collision map previews and per-pack metadata under `extracted/maps/`;
- research previews for `m3_0`, `m4_0`, `m11_0`, `m11_1` under `extracted/images/research/`;
- reverse-engineering notes plus the requested chapter/mission summary table under `docs/reverse_engineering/`;
- machine-readable `summary.json` tying the above artifacts together.
- formalized API contract for `summary.json`: [`docs/reverse_engineering/summary_schema.md`](docs/reverse_engineering/summary_schema.md).
- chapter dependency matrix in JSON/Markdown (`chapter_matrix.json`, `chapter_matrix.md`) with direct/inferred links and cross-check status.
- chapter matrix artifacts are **runtime-generated** (not stored in git):  
  - generated under `<output_dir>/docs/reverse_engineering/chapter_matrix.json`;  
  - generated under `<output_dir>/docs/reverse_engineering/chapter_matrix.md`;  
  - generated under `<output_dir>/docs/reverse_engineering/chapter_mission_matrix.json`;  
  - generated under `<output_dir>/docs/reverse_engineering/final_asset_table.json`;  
  - generated under `<output_dir>/docs/reverse_engineering/final_asset_table.md`.  
  With default settings, these files appear in `.artifacts/extractor_out/docs/reverse_engineering/`.
- UI resources copied from the original JAR under `extracted/ui/`:
  - `icon.png`
  - `dataIGP`
  - metadata manifest with file size and checksums in `extracted/meta/ui_manifest.json`.
  - бинарные UI-файлы не хранятся в git (ограничение PR-платформы); при необходимости восстановите их локально:

```bash
mkdir -p extracted/ui
unzip -p 240x320-rus-zombie-infection.jar icon.png > extracted/ui/icon.png
unzip -p 240x320-rus-zombie-infection.jar dataIGP > extracted/ui/dataIGP
```

`chunks/containers.json` stores per-chunk metadata with exact hash fields:

- `crc32_hex`: 8-character lowercase CRC32 checksum of raw chunk bytes.
- `sha1`: full 40-character SHA-1 digest computed as `hashlib.sha1(chunk).hexdigest()`.

## Repository policy

Generated extractor output is intentionally **not committed** to this repository. Run the extractor locally or in CI/GitHub artifacts when you need the binary dumps and derived previews.

This policy includes chapter/mission matrix outputs (`chapter_matrix.*`, `chapter_mission_matrix.*`, `final_asset_table.*`): they are generated during extractor execution and should be read from `<output_dir>/docs/reverse_engineering/` (default: `.artifacts/extractor_out/docs/reverse_engineering/`).

## `summary.json` as an analytics API (consumer-oriented)

Treat `summary.json` as a versioned API contract, not just a debug dump:

1. Check `summary_schema_version` (`MAJOR.MINOR.PATCH`).
2. Accept only the supported major version.
3. Read required keys and ignore unknown keys for forward compatibility.

Minimal Python example:

```python
import json
from pathlib import Path

summary = json.loads(Path(".artifacts/extractor_out/summary.json").read_text(encoding="utf-8"))
schema_version = summary["summary_schema_version"]  # e.g. "1.0.0"
major = int(schema_version.split(".", 1)[0])
if major != 1:
    raise RuntimeError(f"Unsupported summary schema major: {schema_version}")

coverage = summary["audio_coverage"]["coverage_percent"]
maps_failed = summary["maps_validation_failed"]
print({"coverage_percent": coverage, "maps_validation_failed": maps_failed})
```

For full field list, invariants, and breaking/deprecation policy see:
[`docs/reverse_engineering/summary_schema.md`](docs/reverse_engineering/summary_schema.md).

## Iteration 1 coverage

This first pass implements:

- parser for `m*` and `t0` containers;
- text extractor for `t0`;
- audio extractor for `m13_1` and `m13_2`;
- research decoders for graphics packs `m3_0`, `m4_0`, `m11_0`, `m11_1`;
- parsers for level / script packs `m8`, `m9`, `m10`;
- parsers for tile / collision packs `m6_0..m6_5`.
