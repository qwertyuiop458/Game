# Reference-кейсы для graphics decoder

В репозитории есть фиксированный набор эталонных кейсов в `tests/reference_cases/graphics/`.

Каждый кейс хранится в отдельной папке и включает:

- `table_chunk.hex` — atlas-чанк в hex-тексте (основной вход декодера),
- `external_*.hex` — дополнительные чанки в hex-тексте (если payload продолжается в следующих блоках),
- `preview.png.b64` — ожидаемый превью-рендер в base64 (PNG),
- `expected.json` — зафиксированные метаданные сравнения,
- `case.json` — манифест кейса (описание и имена файлов).

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

## Обычная проверка (без изменений эталонов)

```bash
python3 -m tools.reference_cases
pytest -q tests/test_graphics_reference_cases.py
```

## Осознанное обновление эталонов

Если декодер изменился намеренно и новый результат корректный:

1. Обновите эталоны:

```bash
python3 -m tools.reference_cases --update
```

2. Перезапустите проверку:

```bash
python3 -m tools.reference_cases
pytest -q tests/test_graphics_reference_cases.py
```

3. В PR обязательно укажите:
   - почему изменился декодер,
   - какие кейсы затронуты,
   - какие именно поля в `expected.json` изменились и почему.

Это нужно, чтобы изменения reference-данных были осознанными, а не случайными.
