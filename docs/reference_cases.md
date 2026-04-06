# Reference-кейсы для graphics decoder

В репозитории есть фиксированный набор эталонных кейсов в `tests/reference_cases/graphics/`.

Каждый кейс хранится в отдельной папке и включает:

- `table_chunk.hex` — atlas-чанк в hex-тексте (основной вход декодера),
- `external_*.hex` — дополнительные чанки в hex-тексте (если payload продолжается в следующих блоках),
- `preview.png.b64` — ожидаемый детерминированный atlas-preview в base64 (PNG),
- `expected.json` — зафиксированные метаданные сравнения,
- `case.json` — манифест кейса (описание и имена файлов).

На текущий момент в наборе есть кейсы с inline/external payload и разными
форматами индексов/палитр (`INDEX_8`, `PACKED_4`, `PACKED_2`,
`ARGB8888`, `RGB4444`, `RGB565_ALPHA_KEY`).

## Что проверяется

Проверка выполняется утилитой `tools/reference_cases.py` и тестом
`tests/test_graphics_reference_cases.py`.

Сверяются:

1. **Полный набор кадров** (`frames`):
   - полный список `frame_index` (без пропусков),
   - размеры кадра (`width`, `height`),
   - `decode_status` для каждого кадра,
   - ключевые пиксельные метрики (`channel_sum`, `opaque_pixels`),
   - `rgba_sha256` для каждого кадра.
2. **Агрегаты по кейсу** (`totals`) для быстрого сравнения:
   - общее количество кадров и статусы (`decoded/degraded/failed`),
   - суммарные метрики (`pixel_count`, `opaque_pixels`, `channel_sum`),
   - сводный hash по кадрам (`frames_rgba_sha256`),
   - hash atlas-preview по RGBA (`preview_rgba_sha256`).
3. **Контрольные хэши входов и preview-файла**:
   - SHA-256 входных бинарников (`table_sha256`, `external_sha256`),
   - SHA-256 PNG-файла atlas-preview (`preview_png_sha256`).

Новая структура `expected.json`:

```json
{
  "case_id": "...",
  "description": "...",
  "atlas": { "frame_count": 0, "...": "..." },
  "inputs": { "table_sha256": "...", "external_sha256": {} },
  "frames": [
    {
      "frame_index": 0,
      "width": 0,
      "height": 0,
      "rgba_sha256": "...",
      "channel_sum": { "r": 0, "g": 0, "b": 0, "a": 0 },
      "opaque_pixels": 0,
      "decode_status": "decoded",
      "pixel_count": 0
    }
  ],
  "totals": {
    "frame_count": 0,
    "decoded_frames": 0,
    "degraded_frames": 0,
    "failed_frames": 0,
    "pixel_count": 0,
    "opaque_pixels": 0,
    "channel_sum": { "r": 0, "g": 0, "b": 0, "a": 0 },
    "frames_rgba_sha256": "...",
    "preview_width": 0,
    "preview_height": 0,
    "preview_rgba_sha256": "...",
    "preview_png_sha256": "..."
  }
}
```

## Критерии «валидного кадра» на этапе рендера

Для экспорта PNG в `tools/decode_graphics.py` кадр считается валидным, если:

1. payload кадра корректно читается (`raw_payload_size > 0` для непустого кадра),
2. определён codec path из `pixel_format`,
3. после декодирования alpha имеет ожидаемую статистику (`min/max/non_zero`),
4. при `raw_payload_size > 0` кадр не остаётся полностью прозрачным **без**
   явного статуса деградации.

Если при непустом raw декодер не может восстановить корректную alpha
(`decode=None` или все alpha=0), применяется fallback-preview
(непрозрачный grayscale), а кадр маркируется статусом `degraded_decode`.
Полный отказ декодирования без fallback маркируется как `failed_decode`.

## Обычная проверка (без изменений эталонов)

```bash
python3 -m tools.reference_cases
pytest -q tests/test_graphics_reference_cases.py
pytest -q tests/test_graphics_decoder.py
```

## Осознанное обновление эталонов

Если декодер изменился намеренно и новый результат корректный:

1. Сначала посмотрите diff expected vs actual:

```bash
python3 -m tools.reference_cases --update
```

Утилита покажет pending-изменения (`frame_count`, `rgba_sha256`) и завершится
с ошибкой без `--confirm-update`. Это принудительная защита от случайного
перезаписывания эталонов.

2. Обновите эталоны только при явном подтверждении:

```bash
python3 -m tools.reference_cases --update --confirm-update
```

3. Перезапустите проверку:

```bash
python3 -m tools.reference_cases
pytest -q tests/test_graphics_reference_cases.py
pytest -q tests/test_graphics_decoder.py
```

4. В PR обязательно укажите:
   - почему изменился декодер,
   - какие кейсы затронуты,
   - какие именно поля в `expected.json` изменились и почему.

5. Если изменялась логика alpha/fallback:
   - добавьте/обновите regression-кейс в `tests/reference_cases/graphics/`,
   - убедитесь, что для non-empty raw в тестах не возникает «полностью
     прозрачный кадр» без статуса `degraded_decode`/`failed_decode`.

Это нужно, чтобы изменения reference-данных были осознанными, а не случайными.

## Быстрый smoke-набор (contract + reference regression)

Для короткой проверки ключевых регрессий:

```bash
pytest -q -m smoke tests/test_smoke_contract_reference.py tests/test_graphics_contract_smoke.py tests/test_graphics_reference_cases.py
```

## Короткий чек-лист: когда можно обновлять эталоны

Обновлять `expected.json`/`preview.png.b64` допустимо только когда **всё** ниже выполнено:

- [ ] Изменение декодера осознанное и описано (что именно поменялось и зачем).
- [ ] `python3 -m tools.reference_cases --update` показывает ожидаемый diff, а не случайный шум.
- [ ] `graphics_quality_gate` остаётся валидным: инварианты счётчиков соблюдены, `gate_reasons` объяснимы.
- [ ] `reference_cases_passed` и `gate_passed` на smoke/regression прогонах соответствуют правилам roadmap.
- [ ] В PR перечислены затронутые кейсы и причины изменения эталонных метрик/хэшей.

Если хотя бы один пункт не выполнен, эталоны обновлять нельзя.
