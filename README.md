# Game

Offline extractor for `240x320-rus-zombie-infection.jar`.

## Usage

```bash
python3 offline_extractor.py 240x320-rus-zombie-infection.jar -o extractor_out
```

## What the extractor produces

- raw chunk dumps for all `m*`/`t0` containers;
- machine-readable JSON summaries for containers, scripts, maps, and chapter linkage;
- exported `t0` string chunks as UTF-8 text files;
- extracted MIDI files from `m13_1`/`m13_2` when an embedded `MThd` header is present;
- raw audio blobs for non-MIDI chunks that still need deeper reverse engineering;
- PNG previews for tile/layer chunks and graphics-research visualizations.
