# -*- coding: utf-8 -*-
"""
Генератор значка программы «PDF Manager».

Значок — лист с загнутым уголком и именем автора «Tatemia». В мелких
размерах (до 64 пикселей) слово не читается, поэтому там вместо него
крупная буква «T».

Буквы и подложка строятся программно из геометрических примитивов
(прямоугольники, эллипсы, секторы, многоугольники) средствами Pillow.
Шрифты, готовые изображения и пиктограммы не используются, поэтому
на значок не распространяются лицензии третьих лиц.

Запуск:   python tools/make_icon.py        (нужен Pillow 10 или новее)
Результат: assets/icon.png (1024×1024) и assets/icon.ico (16–256 пикселей)
"""

import os
from dataclasses import dataclass

from PIL import Image, ImageDraw

# Цвета соответствуют палитре интерфейса программы (main.py: ACCENT, ACCENT2)
TOP_COLOR    = (107, 92, 238)    # верх подложки, чуть светлее ACCENT
BOTTOM_COLOR = (70, 58, 184)     # низ подложки, ACCENT2
FOLD_COLOR   = (196, 189, 250)   # загнутый уголок
LETTER_COLOR = (255, 255, 255)

SIZE = 1024
SUPERSAMPLE = 4                  # рисуем крупнее и уменьшаем — сглаживание краёв
WORDMARK_ICO_SIZES = [(128, 128), (256, 256)]
MONOGRAM_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)]

# Геометрия в долях стороны значка
CORNER_RADIUS = 0.22             # скругление подложки
FOLD = 0.28                      # размер загнутого уголка

# Слово «Tatemia»
X_HEIGHT = 0.125                 # высота строчных букв
STROKE = 0.032                   # толщина штриха
CAP_RATIO = 1.42                 # высота «T» относительно строчных
TRACKING = 0.15                  # просвет между буквами, в высотах строчных
T_KERNING = -0.2                 # «a» заходит под перекладину «T»
BASELINE = 0.62                  # положение базовой линии

# Монограмма «T» для мелких размеров
MONO_TOP, MONO_BOTTOM = 0.36, 0.82
MONO_WIDTH = 0.50
MONO_STROKE = 0.15

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets")


@dataclass(frozen=True)
class Pen:
    """Маска для рисования букв и общие размеры строки."""
    draw: ImageDraw.ImageDraw
    baseline: float
    x_height: float
    stroke: float

    @property
    def x_top(self):
        return self.baseline - self.x_height

    def ring(self, x0, y0, x1, y1):
        self.draw.ellipse([x0, y0, x1, y1], fill=255)
        s = self.stroke
        self.draw.ellipse([x0 + s, y0 + s, x1 - s, y1 - s], fill=0)


# ── Буквы: каждая функция рисует букву от x и возвращает её ширину ──────────

def glyph_cap_t(pen, x):
    width = pen.x_height * 0.95
    top = pen.baseline - pen.x_height * CAP_RATIO
    pen.draw.rectangle([x, top, x + width, top + pen.stroke], fill=255)
    stem = x + (width - pen.stroke) / 2
    pen.draw.rectangle([stem, top, stem + pen.stroke, pen.baseline], fill=255)
    return width


def glyph_a(pen, x):
    width = pen.x_height
    pen.ring(x, pen.x_top, x + width, pen.baseline)
    pen.draw.rectangle([x + width - pen.stroke, pen.x_top, x + width, pen.baseline],
                       fill=255)
    return width


def glyph_t(pen, x):
    width = pen.x_height * 0.6
    stem = x + (width - pen.stroke) / 2
    top = pen.baseline - pen.x_height * 1.3
    pen.draw.rectangle([stem, top, stem + pen.stroke, pen.baseline], fill=255)
    pen.draw.rectangle([x, pen.x_top, x + width, pen.x_top + pen.stroke], fill=255)
    return width


def glyph_e(pen, x):
    width = pen.x_height
    center_y = pen.baseline - pen.x_height / 2
    half = pen.stroke / 2
    pen.ring(x, pen.x_top, x + width, pen.baseline)
    # просвет в правой нижней части кольца, под перекладиной
    pen.draw.polygon([(x + width / 2, center_y + half),
                      (x + width + 1, center_y + half),
                      (x + width + 1, center_y + pen.x_height * 0.42)], fill=0)
    # перекладина доходит до внутреннего края кольца, иначе её углы
    # выступают за скруглённый контур буквы
    pen.draw.rectangle([x + half, center_y - half,
                        x + width - pen.stroke, center_y + half], fill=255)
    return width


def glyph_m(pen, x):
    hump = pen.x_height * 0.75
    s = pen.stroke
    center_y = pen.x_top + hump / 2
    # сначала верхние половины колец, затем поверх — вертикальные штрихи
    for left in (x, x + hump - s):
        pen.ring(left, pen.x_top, left + hump, pen.x_top + hump)
        pen.draw.rectangle([left, center_y, left + hump, pen.x_top + hump + 1], fill=0)
    pen.draw.rectangle([x, pen.x_top, x + s, pen.baseline], fill=255)
    for stem in (x + hump - s, x + 2 * hump - 2 * s):
        pen.draw.rectangle([stem, center_y, stem + s, pen.baseline], fill=255)
    return 2 * hump - s


def glyph_i(pen, x):
    s = pen.stroke
    pen.draw.rectangle([x, pen.x_top, x + s, pen.baseline], fill=255)
    dot = s * 1.15
    dot_y = pen.x_top - s * 1.6
    pen.draw.ellipse([x + s / 2 - dot / 2, dot_y - dot / 2,
                      x + s / 2 + dot / 2, dot_y + dot / 2], fill=255)
    return s


WORD = [glyph_cap_t, glyph_a, glyph_t, glyph_e, glyph_m, glyph_i, glyph_a]


def word_width(side):
    """Ширина слова: каждая буква рисуется на пробной маске и меряется."""
    probe = Image.new("L", (side, side), 0)
    pen = Pen(ImageDraw.Draw(probe), side / 2, side * X_HEIGHT, side * STROKE)
    letters = sum(glyph(pen, 0) for glyph in WORD)
    gaps = (len(WORD) - 1) * TRACKING + T_KERNING
    return letters + gaps * side * X_HEIGHT


def wordmark_mask(side):
    mask = Image.new("L", (side, side), 0)
    pen = Pen(ImageDraw.Draw(mask), side * BASELINE, side * X_HEIGHT, side * STROKE)
    x = (side - word_width(side)) / 2
    for index, glyph in enumerate(WORD):
        x += glyph(pen, x) + pen.x_height * TRACKING
        if index == 0:
            x += pen.x_height * T_KERNING
    return mask


def monogram_mask(side):
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    stroke, width = side * MONO_STROKE, side * MONO_WIDTH
    top, bottom = side * MONO_TOP, side * MONO_BOTTOM
    left = (side - width) / 2
    draw.rectangle([left, top, left + width, top + stroke], fill=255)
    draw.rectangle([(side - stroke) / 2, top, (side + stroke) / 2, bottom], fill=255)
    return mask


# ── Подложка ────────────────────────────────────────────────────────────────

def gradient(side):
    """Вертикальный градиент от TOP_COLOR к BOTTOM_COLOR."""
    column = Image.new("RGB", (1, side))
    for y in range(side):
        t = y / (side - 1)
        column.putpixel((0, y), tuple(
            round(a + (b - a) * t) for a, b in zip(TOP_COLOR, BOTTOM_COLOR)))
    return column.resize((side, side))


def sheet_mask(side):
    """Подложка: скруглённый квадрат со срезанным правым верхним углом."""
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, side - 1, side - 1],
                           radius=round(side * CORNER_RADIUS), fill=255)
    fold = round(side * FOLD)
    draw.polygon([(side - fold, 0), (side, 0), (side, fold)], fill=0)
    return mask


def build(letters_mask):
    """Значок с буквами из letters_mask, в размере SIZE×SIZE."""
    side = SIZE * SUPERSAMPLE
    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    img.paste(gradient(side), (0, 0), sheet_mask(side))

    fold = round(side * FOLD)
    ImageDraw.Draw(img).polygon(
        [(side - fold, 0), (side - fold, fold), (side, fold)], fill=FOLD_COLOR)

    img.paste(Image.new("RGBA", (side, side), LETTER_COLOR), (0, 0),
              letters_mask(side))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    wordmark = build(wordmark_mask)
    monogram = build(monogram_mask)
    wordmark.save(os.path.join(OUT_DIR, "icon.png"))
    # Все кадры ICO готовятся заранее: Pillow берёт кадр из append_images
    # по совпадению размера, а недостающие масштабирует из последнего
    # переданного изображения, а не из основного.
    frames = ([monogram.resize(size, Image.LANCZOS) for size in MONOGRAM_ICO_SIZES]
              + [wordmark.resize(size, Image.LANCZOS) for size in WORDMARK_ICO_SIZES])
    # bitmap_format="bmp" обязателен: по умолчанию Pillow сжимает все кадры
    # значка в PNG, а Windows поддерживает PNG в значках только для размера
    # 256x256. Значок с PNG-кадрами мелких размеров Проводник не отображает.
    frames[-1].save(os.path.join(OUT_DIR, "icon.ico"), bitmap_format="bmp",
                    sizes=MONOGRAM_ICO_SIZES + WORDMARK_ICO_SIZES,
                    append_images=frames[:-1])
    print(f"Значок сохранён в {OUT_DIR}")


if __name__ == "__main__":
    main()
