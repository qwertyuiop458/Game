# `summary.json` API contract (analytics-facing)

`summary.json` считается стабильным API-контрактом для downstream-консьюмеров (аналитика, отчёты, quality-gates).

## 1) Версия схемы

- Обязательное поле верхнего уровня: `summary_schema_version`.
- Формат: semantic version `MAJOR.MINOR.PATCH`.
- Текущая версия схемы: `1.0.0`.

## 2) Обязательные ключи верхнего уровня

Все поля ниже обязательны и должны присутствовать в каждом `summary.json`:

- `summary_schema_version: string` (`MAJOR.MINOR.PATCH`)
- `jar: string`
- `containers: object`
- `container_quality: object`
- `text: object`
- `audio: object`
- `audio_stats: object`
- `audio_validation_summary: object`
- `maps: object`
- `scripts: object`
- `map_mismatch_summary: object`
- `maps_validation_passed: integer >= 0`
- `maps_validation_failed: integer >= 0`
- `audio_coverage: object`
- `graphics: object`
- `ui: object`
- `final_table_rows: integer >= 0`
- `chapter_mission_matrix_rows: integer >= 0`
- `chapter_matrix_rows: integer >= 0`
- `chapter_matrix_cross_check: object`
- `linker_conflicts_summary: object`

## 2.1) Гарантированные поля (stable contract blocks)

Независимо от внутренних рефакторингов декодеров, в схеме `1.x` гарантированно присутствуют следующие блоки:

- `audio_coverage`
- `audio_validation_summary`
- `map_mismatch_summary`
- `chapter_matrix_cross_check`
- `linker_conflicts_summary`

Для каждого блока валидируются типы, диапазоны, неотрицательность и базовая согласованность счётчиков.

## 3) Инварианты (обязательные)

### `audio_coverage`

- `total_tracks: int >= 0`
- `decoded_tracks: int`, `0 <= decoded_tracks <= total_tracks`
- `coverage_percent: float`, `0.0 <= coverage_percent <= 100.0`

### `audio_validation_summary`

- Ровно ключи: `total`, `valid`, `invalid`, `warnings`
- Все значения — `int >= 0`
- `valid <= total`
- `invalid <= total`

### `map_mismatch_summary`

- `total_maps: int >= 0`
- `mismatched_maps: int`, `0 <= mismatched_maps <= total_maps`
- `mismatch_details: list`
- `maps_validation_passed: int >= 0`
- `maps_validation_failed: int >= 0`
- `maps_validation_passed <= total_maps`
- `maps_validation_failed <= total_maps`
- Дублирующие top-level поля должны совпадать:
  - `maps_validation_passed == map_mismatch_summary.maps_validation_passed`
  - `maps_validation_failed == map_mismatch_summary.maps_validation_failed`

### `chapter_matrix_cross_check`

- `total_refs: int >= 0`
- `valid_refs: int`, `0 <= valid_refs <= total_refs`
- `valid_confidence_totals` содержит `direct`, `inferred`, `unknown` (все `int >= 0`)
- `invalid_refs: list`
- `dropped_invalid_refs: list`
- `conflict_summary.total_conflicts: int >= 0`
- `conflict_summary.by_type: object<string, int>=0`

### `linker_conflicts_summary`

- `total_conflicts: int >= 0`
- `blocking_conflicts: int`, `0 <= blocking_conflicts <= total_conflicts`
- `conflicts: list`

## 4) Правила semantic-version и compatibility

### Что считается backward-compatible

- Сохранение всех гарантированных полей (`audio_coverage`, `audio_validation_summary`, `map_mismatch_summary`, `chapter_matrix_cross_check`, `linker_conflicts_summary`) без изменения их типов.
- Добавление новых **необязательных** полей (top-level или nested).
- Расширение enum-like значений без удаления существующих.
- Уточнение документации и инвариантов без изменения фактического формата данных.

Это `MINOR`/`PATCH` изменения при сохранении `MAJOR`.

### Что считается breaking change

Любое из ниже требует увеличения `MAJOR`:

- удаление любого обязательного ключа;
- переименование ключа;
- изменение типа существующего ключа;
- ужесточение формата так, что ранее валидные значения становятся невалидными;
- изменение смысловой интерпретации поля без сохранения прежней совместимой формы.

### Runtime-правило совместимости

Консьюмер версии `1.x` должен:

1. Проверить `summary_schema_version` как semver.
2. Проверить, что `MAJOR == 1`.
3. Проверить наличие минимального обязательного набора ключей.
4. Игнорировать неизвестные дополнительные ключи.

## 5) Политика депрекации и срок поддержки

- Сначала помечаем поле как **deprecated** в документации (без удаления).
- Минимальный срок поддержки deprecated-поля: **2 MINOR-релиза** или **90 дней** (что дольше).
- В этот период поле остаётся в `summary.json`, а новые консьюмеры должны читать новый ключ с fallback на deprecated.
- Удаление deprecated-поля допускается только в следующем `MAJOR`.

## 6) Рекомендации для консьюмеров

- Всегда валидируйте `summary_schema_version`.
- Пишите tolerant-reader логику: обязательные ключи проверяются строго, лишние — игнорируются.
- Для метрик используйте инварианты из этого документа как runtime-assertions.
