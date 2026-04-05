"""Совместимый импорт декодера графики.

Файл добавлен как корневой shim, чтобы можно было импортировать модели
Palette/Frame/Region/Animation/Atlas напрямую из `graphics_decoder`.
"""

from tools.graphics_decoder import Animation, Atlas, Frame, Palette, Region, parse_atlas

__all__ = ['Palette', 'Frame', 'Region', 'Animation', 'Atlas', 'parse_atlas']
