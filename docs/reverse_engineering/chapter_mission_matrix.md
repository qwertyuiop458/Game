# Chapter Mission Matrix (документация артефакта)

Этот файл добавлен как стабильная точка в репозитории, чтобы ссылки из `README.md`
были валидными.

## Что это такое

`chapter_mission_matrix` — таблица соответствий «глава → миссии → связанные ресурсы».

- Формируется модулем карт/скриптов: `tools/decode_maps.py`
  (функция `build_chapter_mission_matrix`).
- В полном пайплайне вызывается из `tools/extract_zombie_infection.py`.
- Runtime-артефакты создаются в output-dir (по умолчанию):
  - `.artifacts/extractor_out/docs/reverse_engineering/chapter_mission_matrix.md`
  - `.artifacts/extractor_out/docs/reverse_engineering/chapter_mission_matrix.json`

## Как сгенерировать локально

```bash
python3 -m tools.extract_zombie_infection 240x320-rus-zombie-infection.jar
```

Далее откройте:

```text
.artifacts/extractor_out/docs/reverse_engineering/chapter_mission_matrix.md
```

## Примечание

Файл в репозитории — это документация интерфейса артефакта.
Актуальные данные хранятся в результатах конкретного запуска экстрактора.
