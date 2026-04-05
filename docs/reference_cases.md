# Reference-кейсы для graphics decoder

В репозитории есть фиксированный набор эталонных кейсов в `tests/reference_cases/graphics/`.

Каждый кейс хранится в отдельной папке и включает:

- `table_chunk.hex` — atlas-чанк в hex-тексте (основной вход декодера),
- `external_*.hex` — дополнительные чанки в hex-тексте (если payload продолжается в следующих блоках),
- `preview.png.b64` — ожидаемый превью-рендер в base64 (PNG),
- `expected.json` — зафиксированные метаданные сравнения,
- `case.json` — манифест кейса (описание и имена файлов).

На текущий момент в наборе есть кейсы с inline/external payload и разными
форматами индексов/палитр (`INDEX_8`, `PACKED_4`, `PACKED_2`,
`ARGB8888`, `RGB4444`, `RGB565_ALPHA_KEY`).

## Что проверяется

Проверка выполняется утилитой `tools/reference_cases.py` и тестом
`tests/test_graphics_reference_cases.py`.

Сверяются:

1. **Размеры превью** (`width`, `height`, `pixel_count`).
2. **Базовые пиксельные метрики**:
   - `channel_sum` и `channel_mean` по RGBA,
   - количество непрозрачных пикселей (`opaque_pixels`),
   - число уникальных цветов (`unique_colors`).
3. **Контрольные хэши**:
   - SHA-256 входных бинарников (`table_sha256`, `external_sha256`),
   - SHA-256 массива RGBA (`rgba_sha256`),
   - SHA-256 PNG-файла превью (`png_sha256`).

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

1. Обновите эталоны (только при явном подтверждении):

```bash
python3 -m tools.reference_cases --update --confirm-update
```

Без `--confirm-update` утилита завершится с ошибкой. Это защита от
случайного переписывания `expected.json`/`preview.png.b64`.

2. Перезапустите проверку:

```bash
python3 -m tools.reference_cases
pytest -q tests/test_graphics_reference_cases.py
pytest -q tests/test_graphics_decoder.py
```

3. В PR обязательно укажите:
   - почему изменился декодер,
   - какие кейсы затронуты,
   - какие именно поля в `expected.json` изменились и почему.

4. Если изменялась логика alpha/fallback:
   - добавьте/обновите regression-кейс в `tests/reference_cases/graphics/`,
   - убедитесь, что для non-empty raw в тестах не возникает «полностью
     прозрачный кадр» без статуса `degraded_decode`/`failed_decode`.

Это нужно, чтобы изменения reference-данных были осознанными, а не случайными.
