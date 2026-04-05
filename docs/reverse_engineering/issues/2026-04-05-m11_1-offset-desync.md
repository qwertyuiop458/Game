# Issue: offset/payload desync в m11_1#00 (manifest/metadata vs frames.json)

- **Дата:** 2026-04-05
- **Симптом:** `metadata.json` и `manifest.json` сообщают 17 кадров, но `frames.json` содержит только 4 визуально экспортированных кадра (`frames`), при этом `payloads` остаётся 17.
- **Пакет/чанк:** `m11_1#00`.

## Repro

```bash
python -m tools.decode_graphics 240x320-rus-zombie-infection.jar -o .artifacts/extractor_out
python - <<'PY'
import json
pack='m11_1'
md=json.load(open(f'.artifacts/extractor_out/extracted/sprites/{pack}/chunk_00/metadata.json'))
man=json.load(open(f'.artifacts/extractor_out/extracted/sprites/{pack}/chunk_00/manifest.json'))
fr=json.load(open(f'.artifacts/extractor_out/extracted/images/{pack}/chunk_00/frames.json'))
print('metadata.frame_count=',md['frame_count'])
print('manifest.frames=',len(man['frames']))
print('frames.json.frames=',len(fr['frames']))
print('frames.json.payloads=',len(fr['payloads']))
PY
```

## Наблюдение

- Нарушена консистентность offset/payload trace для воспроизводимости гипотезы `HYP-m11_1-00-01`.
- Вероятная зона проверки: ветка `codec_switch`/логика фильтрации экспортируемых кадров при `data_chunk = -1`.
