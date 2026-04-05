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

## Пакет `m3_0`

### [HYP-m3_0-00-01] Базовая привязка палитры через runtime slot
- **Pack/chunk:** `m3_0#00`
- **Формат заголовка (предполагаемые поля):**
  - `pixel_format`
  - `frame_count`
  - `palette_count` / `palette_size`
  - `regions_count` (опционально)
  - `sprite_length_table_offset` (таблица длины кадров в table chunk)
  - `sprite_data_stream_ref` (данные кадра могут продолжаться во внешних чанках)
- **Palette hypothesis:**
  - model: palette slot выбирается runtime (`runtime-selected`), per-frame remap не изменяет сырой источник
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
  - research preview: `extracted/images/research/m3_0/chunk_00/preview_frame_000.md`
  - research raw: `extracted/images/research/m3_0/chunk_00/raw_frame_000.md`
- **Confirmation status:** `partially_confirmed`
- **Validation notes:** `2026-04-05: проверены кадры 000/001/002 (preview+raw), пути в metadata.json/manifest.json/frames.json совпадают, offsets для выборки согласованы (chunk/data_offset: 0:0, -1:0, -1:0); открыта issue по симптомам empty PNG при non-empty raw на других кадрах пакета.`
- **Критерий подтверждения/опровержения:**
  - подтверждение: минимум 3 кадра с совпадением preview/raw и монотонными offsets в `frames.json`
  - опровержение: систематический color noise или несовместимость `data_offset` с экспортированным `.bin`

## Пакет `m4_0`

### [HYP-m4_0-00-01] Смещения sprite payload продолжаются в external chunks
- **Pack/chunk:** `m4_0#00`
- **Формат заголовка (предполагаемые поля):**
  - `pixel_format`
  - `frame_count`
  - `palette_count` / `palette_size`
  - `frame_table_offset`
  - `payload_continuation_flags` (косвенно выводится по `data_chunk` ссылкам во внешние чанки)
- **Palette hypothesis:**
  - model: единая таблица палитр контейнера + runtime binding на кадр
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
  - research preview: `extracted/images/research/m4_0/chunk_00/preview_frame_000.md`
  - research raw: `extracted/images/research/m4_0/chunk_00/raw_frame_000.md`
- **Confirmation status:** `partially_confirmed`
- **Validation notes:** `2026-04-05: проверены кадры 000/001/002 (preview+raw), сверены metadata.json/manifest.json/frames.json, offsets выборки согласованы (chunk/data_offset: -1:0, -1:0, 0:0); открыта issue по массовым empty PNG при non-empty raw за пределами минимальной выборки.`
- **Критерий подтверждения/опровержения:**
  - подтверждение: `decoded_frame_count` совпадает с фактическими preview/raw выборками и offsets не выходят за sprite stream
  - опровержение: повторяемые пустые `.bin` при валидных размерах кадров или разрушенные палитры в preview

## Пакет `m11_0`

### [HYP-m11_0-00-01] Таблица регионов не влияет на базовый decode frame payload
- **Pack/chunk:** `m11_0#00`
- **Формат заголовка (предполагаемые поля):**
  - `pixel_format`
  - `frame_count`
  - `region_count`
  - `palette_count` / `palette_size`
  - `frame_payload_map_offset` (соответствие frame table -> payload stream)
- **Palette hypothesis:**
  - model: palette table общая для atlas, выбор активной палитры выполняется экземпляром спрайта
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
  - research preview: `extracted/images/research/m11_0/chunk_00/preview_frame_000.md`
  - research raw: `extracted/images/research/m11_0/chunk_00/raw_frame_000.md`
- **Confirmation status:** `partially_confirmed`
- **Validation notes:** `2026-04-05: проверены кадры 000/001/002 (preview+raw), frame_id -> payload.frame_index совпадает между manifest и frames trace, offsets согласованы (chunk/data_offset: 0:0, 1:0, 1:1499); открыта issue по единичным empty PNG при non-empty raw в chunk_00.`
- **Критерий подтверждения/опровержения:**
  - подтверждение: совпадают пары `frame_id -> payload.frame_index`; region table не ломает базовый decode
  - опровержение: рассинхрон frame/payload mapping либо деградация decode после учета regions

## Пакет `m11_1`

### [HYP-m11_1-00-01] Вариант контейнера m11_1 совместим с тем же codec_switch
- **Pack/chunk:** `m11_1#00`
- **Формат заголовка (предполагаемые поля):**
  - `pixel_format`
  - `frame_count`
  - `palette_count` / `palette_size`
  - `region_count`
  - `codec_switch_marker` (ветка decode определяется `pixel_format`)
  - `payload_lengths_table`
- **Palette hypothesis:**
  - model: совместимая с `m11_0` таблица палитр, используемая через тот же runtime slot механизм
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
  - research preview: `extracted/images/research/m11_1/chunk_00/preview_frame_000.md`
  - research raw: `extracted/images/research/m11_1/chunk_00/raw_frame_000.md`
- **Confirmation status:** `rejected`
- **Validation notes:** `2026-04-05: проверены кадры 000/001/002 (preview+raw), offsets выборки формально согласованы (chunk/data_offset: -1:0, -1:0, -1:0), но воспроизводимость нарушена: metadata/manifest фиксируют 17 кадров, а frames.json экспортирует только 4; заведена issue по offset/payload desync для m11_1#00.`
- **Критерий подтверждения/опровержения:**
  - подтверждение: консистентный `frame_count` в trace + валидные preview/raw пары без системных искажений
  - опровержение: пустые PNG при непустом raw в повторяемом наборе кадров или несоответствие выбранной ветки codec

---

## Confirmation workflow

- Переводите статус в `partially_confirmed` после:
  1) проверки минимум 3 кадров на пакет,
  2) сверки offsets по `frames.json`.
- Переводите в `confirmed` после:
  1) проверки минимум 10 кадров или 20% кадров пакета (что больше),
  2) отсутствия критичных несоответствий по palette/offset.
- Ставьте `rejected`, если гипотеза ломает воспроизводимость (пути/чанки не дают тот же результат).
