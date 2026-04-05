# Graphics Reverse Engineering Hypotheses

> Scope: hypotheses for `tools/decode_graphics.py` outputs and research artifacts under `extracted/images/research/`.
> 
> Last updated: 2026-04-05.

## How to use this note

1. Run extraction and graphics decode.
2. Open artifacts listed in each hypothesis block.
3. Mark status after visual/manual verification.

Example reproduction command:

```bash
python -m tools.decode_graphics 240x320-rus-zombie-infection.jar -o .artifacts/extractor_out
```

---

## Unified hypothesis template

```md
### [HYP-<pack>-<chunk>-<id>] <short title>
- **Pack/chunk:** `<pack>#<chunk>`
- **Header structure hypothesis:** <what bytes/fields are assumed and why>
- **Palette hypothesis:**
  - format: <ARGB8888/RGB4444/RGB565+alpha-key/etc>
  - count/size: <N palettes, M colors>
  - expected visual effect: <e.g. transparent background, skin tones preserved>
- **Offset observation:**
  - table chunk: <index>
  - payload chunk(s): <indices>
  - data_offset pattern: <monotonic/non-monotonic/repeating>
  - anomaly notes: <if any>
- **Reproducibility anchors:**
  - metadata: `<path/to/metadata.json>`
  - manifest: `<path/to/manifest.json>`
  - frame samples: `<path/to/frame_XXX.png>`
  - raw samples: `<path/to/frame_XXX.bin>`
- **Confirmation status:** `unverified | partially_confirmed | confirmed | rejected`
- **Validation notes:** <what was checked; by whom/date if needed>
```

---

## Active hypotheses

### [HYP-m3_0-00-01] Базовая привязка палитры через runtime slot
- **Pack/chunk:** `m3_0#00`
- **Header structure hypothesis:** заголовок корректно парсится через `parse_atlas(...)`, а таблица длин кадров хранится в atlas chunk (`table_chunk=0`) с продолжением payload в последующих чанках контейнера.
- **Palette hypothesis:**
  - format: `palette_format` из `metadata.json` (ожидаемо один из `ARGB8888`, `RGB4444`, `RGB565+alpha-key`)
  - count/size: `palette_count >= 1`, `palette_size` из метаданных
  - expected visual effect: `frame_*.png` читаемы, фон прозрачен там, где alpha-индекс активен
- **Offset observation:**
  - table chunk: `0`
  - payload chunk(s): см. `payloads[*].data_chunk` в `frames.json`
  - data_offset pattern: ожидается неубывающий `data_offset` внутри одного sprite pool
  - anomaly notes: при нарушении монотонности вероятен неправильный разбор RLE или fallback на неверный external chunk
- **Reproducibility anchors:**
  - metadata: `.artifacts/extractor_out/extracted/sprites/m3_0/chunk_00/metadata.json`
  - manifest: `.artifacts/extractor_out/extracted/sprites/m3_0/chunk_00/manifest.json`
  - frame samples: `.artifacts/extractor_out/extracted/images/m3_0/chunk_00/frame_000.png`
  - raw samples: `.artifacts/extractor_out/extracted/images/m3_0/chunk_00/frame_000.bin`
- **Confirmation status:** `unverified`
- **Validation notes:** проверить визуально соответствие palette preview (`palette_00.png`) и `frame_000.png`; затем сверить `data_offset` в `frames.json`.

### [HYP-m4_0-00-01] Смещения sprite payload продолжаются в external chunks
- **Pack/chunk:** `m4_0#00`
- **Header structure hypothesis:** atlas table в текущем чанке с переносом сырого спрайт-пула в соседние чанки (через `_candidate_external_chunks`).
- **Palette hypothesis:**
  - format: из `metadata.json`, без ручного override
  - count/size: как в `palettes[*]` и `palette_previews`
  - expected visual effect: палитры дают связные цвета объектов, без массового «цветового шума»
- **Offset observation:**
  - table chunk: `0`
  - payload chunk(s): ожидаемо `>= 1` при больших пулах
  - data_offset pattern: offsets внутри кадра не выходят за `len(sprite_data)`
  - anomaly notes: пустые `.bin` при ненулевом `frame_size` — сигнал о неверном `frame_offset`
- **Reproducibility anchors:**
  - metadata: `.artifacts/extractor_out/extracted/sprites/m4_0/chunk_00/metadata.json`
  - manifest: `.artifacts/extractor_out/extracted/sprites/m4_0/chunk_00/manifest.json`
  - frame samples: `.artifacts/extractor_out/extracted/images/m4_0/chunk_00/frame_000.png`
  - raw samples: `.artifacts/extractor_out/extracted/images/m4_0/chunk_00/frame_000.bin`
- **Confirmation status:** `unverified`
- **Validation notes:** отдельно сравнить `decoded_frame_count` в `extracted/images/index.json` и фактическое число `frame_*.png`.

### [HYP-m11_0-00-01] Таблица регионов не влияет на базовый decode frame payload
- **Pack/chunk:** `m11_0#00`
- **Header structure hypothesis:** region table (`regions`) парсится независимо от данных кадра и не должна ломать extraction payload.
- **Palette hypothesis:**
  - format: как в `palette_trace`/`palette_table`
  - count/size: доступно `available_palettes`
  - expected visual effect: основной кадр декодируется даже без применения регионов/анимаций
- **Offset observation:**
  - table chunk: `0`
  - payload chunk(s): см. `frame_links[*].data_chunk` в `graphics_manifest.json`
  - data_offset pattern: offsets согласованы между `manifest.json` и `frames.json`
  - anomaly notes: рассинхрон offsets между manifest/frames указывает на ошибку сериализации payload map
- **Reproducibility anchors:**
  - metadata: `.artifacts/extractor_out/extracted/sprites/m11_0/chunk_00/metadata.json`
  - manifest: `.artifacts/extractor_out/extracted/sprites/m11_0/chunk_00/manifest.json`
  - frame samples: `.artifacts/extractor_out/extracted/images/m11_0/chunk_00/frame_000.png`
  - raw samples: `.artifacts/extractor_out/extracted/images/m11_0/chunk_00/frame_000.bin`
- **Confirmation status:** `unverified`
- **Validation notes:** проверять пары `frame_id -> payload.frame_index` на совпадение.

### [HYP-m11_1-00-01] Вариант контейнера m11_1 совместим с тем же codec_switch
- **Pack/chunk:** `m11_1#00`
- **Header structure hypothesis:** layout совместим с `m11_0`; различия — в конкретных значениях frame table и payload lengths.
- **Palette hypothesis:**
  - format: как в parsed palette header
  - count/size: из `palette_count`/`palette_size`
  - expected visual effect: одинаковый `codec_switch` должен декодировать большинство кадров без искажений
- **Offset observation:**
  - table chunk: `0`
  - payload chunk(s): `data_chunk` может ссылаться на несколько чанков
  - data_offset pattern: offsets в trace должны согласовываться с экспортированными `.bin`
  - anomaly notes: если PNG пустые при непустом raw — вероятна ошибка в ветке pixel_format
- **Reproducibility anchors:**
  - metadata: `.artifacts/extractor_out/extracted/sprites/m11_1/chunk_00/metadata.json`
  - manifest: `.artifacts/extractor_out/extracted/sprites/m11_1/chunk_00/manifest.json`
  - frame samples: `.artifacts/extractor_out/extracted/images/m11_1/chunk_00/frame_000.png`
  - raw samples: `.artifacts/extractor_out/extracted/images/m11_1/chunk_00/frame_000.bin`
- **Confirmation status:** `unverified`
- **Validation notes:** первичная проверка — наличие `tile_preview` и консистентный `frame_count` в trace.

---

## Confirmation workflow

- Переводите статус в `partially_confirmed` после:
  1) проверки минимум 3 кадров на пакет,
  2) сверки offsets по `frames.json`.
- Переводите в `confirmed` после:
  1) проверки минимум 10 кадров или 20% кадров пакета (что больше),
  2) отсутствия критичных несоответствий по palette/offset.
- Ставьте `rejected`, если гипотеза ломает воспроизводимость (пути/чанки не дают тот же результат).
