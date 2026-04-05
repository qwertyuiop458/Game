# Roadmap модулей декодера

Ниже — текущий статус ключевых модулей и ближайшие практические шаги по каждому из них.

| Модуль | Статус | Успешный результат | Известные ограничения | Следующий конкретный шаг |
|---|---|---|---|---|
| `tools/decode_text_t0.py` | **stable** | Для всех `t0`-контейнеров формируются читаемые текстовые выгрузки в `extracted/text/` без падений пайплайна. | Возможны отдельные артефакты кодировки/разметки в редких строках, если формат содержит нестандартные управляющие байты. | 1) Добавить точечные regression-тесты на редкие управляющие последовательности.<br>2) Включить авто-проверку целостности строк (счётчик записей до/после декодирования). |
| `tools/decode_audio_m13.py` | **partial** | Для поддержанных контейнеров (`m13_*`) извлекаются MIDI/сырьевые артефакты, пригодные для прослушивания и дальнейшего анализа. | Не все варианты внутренних структур аудио-паков нормализованы одинаково; часть данных остаётся в «raw/research» виде. | 1) Зафиксировать сигнатуры неподдержанных вариантов `m13` в отдельном реестре.<br>2) Добавить пост-валидацию MIDI (базовые structural checks) и отчёт о покрытии. |
| `tools/decode_maps.py` | **partial** | Генерируются тайловые/коллизионные представления и метаданные карт, достаточные для анализа уровней. | Семантика части полей остаётся эвристической; не все карты полностью верифицированы с игровым рантаймом. | 1) Расширить карту соответствия полей `m8/m9/m10` с примерами из реальных миссий.<br>2) Добавить сверку коллизий/границ с автоматическим отчётом о mismatch. |
| `tools/decode_graphics.py` | **research** | Для исследуемых паков (`m3_0`, `m4_0`, `m11_0`, `m11_1`) строятся preview-артефакты для reverse engineering. | Формат графики декодирован не полностью; возможны неверные палитры, смещения и неполная реконструкция спрайтов/тайлов. | 1) Держать контракт `graphics_quality_gate` в `extracted/images/index.json` и `extracted/meta/graphics_manifest.json` стабильным.<br>2) Переводить модуль в `partial/stable` только при выполнении gate-критериев ниже. |
| `tools/linker.py` | **partial** | Формируются сводные таблицы/матрицы связей ассетов и глав (JSON/MD), пригодные для навигации и аналитики. | Часть связей остаётся inferred (эвристической), а не подтверждённой прямыми ссылками; возможны ложноположительные соответствия. | 1) Разделить confidence-уровни в итоговой матрице (direct / inferred / unknown).<br>2) Добавить cross-check с декодированными скриптами и отчёт о конфликтующих связях. |

## Критерии перехода `partial -> stable`

### `tools/decode_graphics.py` (`research -> partial -> stable`)

- В итоговых артефактах всегда присутствует блок `graphics_quality_gate` с фиксированными ключами:
  - `total_frames`, `decoded_frames`, `degraded_frames`, `failed_frames`, `skipped_frames`;
  - `non_empty_raw_frames`, `non_empty_raw_with_alpha_nonzero`;
  - `reference_cases_passed`, `gate_passed`, `gate_reasons`.
- Контрактные инварианты обязательны:
  - все счётчики неотрицательные;
  - `decoded_frames + degraded_frames + failed_frames + skipped_frames == total_frames`;
  - `non_empty_raw_with_alpha_nonzero <= non_empty_raw_frames`.
- Логика качества:
  - `gate_passed == True` только если `reference_cases_passed == True`;
  - `gate_passed == False`, если есть `failed_frames` для `non_empty raw` кадров без допустимой деградации
    (причина в `gate_reasons`: `non_empty_raw_failed_without_acceptable_degradation`);
  - любые нарушения инвариантов добавляются в `gate_reasons` и переводят gate в fail.
- Переход `research -> partial`:
  - gate стабильно присутствует в отчётах;
  - для контрольных прогонов `failed_frames == 0` или все проблемные случаи переведены в `degraded_frames`
    с диагностикой причины.
- Переход `partial -> stable`:
  - `gate_passed == True` на CI smoke/regression прогонах;
  - `reference_cases_passed == True` на том же наборе;
  - доля `degraded_frames` документирована и не растёт без объяснённой причины.

### `tools/decode_audio_m13.py`

- `summary.json` всегда содержит нормализованные блоки `audio_coverage` и `audio_validation_summary` с фиксированными ключами:
  - `audio_coverage`: `total_tracks`, `decoded_tracks`, `coverage_percent`;
  - `audio_validation_summary`: `total`, `valid`, `invalid`, `warnings`.
- Для этих блоков соблюдаются инварианты контрактов:
  - `0 <= decoded_tracks <= total_tracks`;
  - `0.0 <= coverage_percent <= 100.0`;
  - `valid <= total`, `invalid <= total`, все счётчики неотрицательные.
- Контрактные тесты на структуру/диапазоны включены в быстрый smoke-набор CI.

### `tools/decode_maps.py`

- `summary.json` всегда содержит `map_mismatch_summary` с фиксированными ключами:
  `total_maps`, `mismatched_maps`, `mismatch_details`, `maps_validation_passed`, `maps_validation_failed`.
- Соблюдаются инварианты:
  - все счётчики неотрицательные;
  - `mismatched_maps <= total_maps`;
  - `maps_validation_passed <= total_maps`;
  - `maps_validation_failed <= total_maps`.
- Каждая запись в `mismatch_details` соответствует формату:
  `pack: str`, `chunk: int`, `expected: dict`, `actual: dict`, `severity: str`, `message: str`.
- Контрактные тесты на инварианты и формат mismatch entries включены в smoke-набор CI.

### `tools/linker.py`

- `summary.json` всегда содержит блоки `chapter_matrix_cross_check` и `linker_conflicts_summary` с фиксированными ключами.
- Для `chapter_matrix_cross_check` соблюдаются базовые инварианты консистентности:
  - `0 <= valid_refs <= total_refs`;
  - `valid_confidence_totals` содержит ключи `direct`, `inferred`, `unknown` с неотрицательными счётчиками;
  - `conflict_summary.total_conflicts >= 0`, значения `conflict_summary.by_type` неотрицательные.
- Для `linker_conflicts_summary` соблюдается инвариант:
  - `0 <= blocking_conflicts <= total_conflicts`, `conflicts` всегда список.
- Контрактные тесты на эти инварианты запускаются в smoke-наборе CI до тяжёлых интеграционных прогонов.

## Легенда статусов

- **stable** — модуль регулярно используется в основном пайплайне, результат предсказуем.
- **partial** — ключевой функционал работает, но покрытие форматов/валидация пока неполные.
- **research** — модуль в исследовательской фазе, результаты применимы прежде всего для reverse engineering.

## Подтверждённые соответствия полей (`m8/m9/m10`)

| Поле | Подтверждённая интерпретация |
|---|---|
| `mission_id` (`m9.chunk0.level_index`) | Идентификатор миссии/уровня: порядок записей в `m9` chunk0. |
| `chapter` (`m9.chunk0.chapter_hint % chapter_count`) | Номер главы и выбор контейнера карты `m6_<chapter>`. |
| `map_pack_name` | Контейнер карт миссии: `m6_<chapter>`. |
| `map_subchunk` (`m9.chunk0.map_subchunk_hint`) | Индекс tile-слоя карты в соответствующем `m6_<chapter>`. |
| `script_subchunk_index` (`m9.chunk0.script_subchunk_hint`) | Индекс сценарного сабчанка внутри script-области `m9`. |
| `script_chunk` (`10 + script_subchunk_index`) | Явная ссылка на `m9` script chunk (диапазон `chunk >= 10`). |
| `m8_script_index` | Базовый индекс `m8`-скрипта для миссии; фиксируется по `mission_id`. |
| `m10.chapter_chunks[idx]` | Табличные чанки по главам для coverage-check (валидация: количество чанков >= число глав). |
