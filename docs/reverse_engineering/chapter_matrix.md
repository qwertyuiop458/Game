# Chapter Matrix (документация артефакта)

Этот файл добавлен как стабильная точка в репозитории, чтобы ссылки из `README.md`
не были «битые».

## Что это такое

`chapter_matrix` — это сводка связей между главами, которую строит линкер.

- Источник генерации: `tools/linker.py` (`build_chapter_matrix`).
- В основном пайплайне вызывается из `tools/extract_zombie_infection.py`.
- Машинный артефакт создаётся в runtime-выводе (по умолчанию):
  - `.artifacts/extractor_out/docs/reverse_engineering/chapter_matrix.md`
  - `.artifacts/extractor_out/docs/reverse_engineering/chapter_matrix.json`

## Как получить актуальную матрицу локально

```bash
python3 -m tools.extract_zombie_infection 240x320-rus-zombie-infection.jar
```

После запуска откройте runtime-файл:

```text
.artifacts/extractor_out/docs/reverse_engineering/chapter_matrix.md
```

## Зачем файл хранится в git

Репозиторный `docs/reverse_engineering/chapter_matrix.md` — это
документационный «якорь», а не snapshot данных конкретного прогона.
