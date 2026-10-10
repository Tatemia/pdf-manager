#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
#
#   PDF Manager
#   ------------------------------------------------------------------------
#   Полное наименование:  Программа для управления PDF-документами
#                         «PDF Manager»
#   Краткое наименование: PDF Manager
#   Версия:               1.0
#   Год создания:         2026
#   Язык программирования: Python 3
#
# =============================================================================
"""
PDF Manager — настольное приложение для работы с PDF-документами.

Возможности: объединение файлов, удаление / извлечение / поворот /
перестановка страниц, разделение документа, защита паролем, просмотр и
правка метаданных, сжатие, нумерация страниц и водяные знаки, извлечение
текста и изображений, сборка PDF из растровых изображений.

Наименование и версия — в заголовочном блоке выше
и в константах раздела «Program identity».

Среда выполнения: Python 3.10+, графическая библиотека Tkinter (Tcl/Tk).

Используемые сторонние библиотеки (все — со свободными разрешительными
лицензиями, допускающими использование в составе закрытого ПО):
    pypdf        — BSD-3-Clause          (обязательная)
    pypdfium2    — BSD-3-Clause/Apache-2.0 (миниатюры страниц)
    Pillow       — MIT-CMU               (миниатюры, изображения → PDF)
    reportlab    — BSD-3-Clause          (нумерация, водяные знаки)
    tkinterdnd2  — MIT                   (перетаскивание файлов в окно)
    cryptography — Apache-2.0 / BSD-3-Clause (шифрование AES-256)

Необязательные библиотеки подключаются при наличии; без них программа
работает, а соответствующие разделы сообщают, что нужно доустановить.
"""

import datetime
import io
import os
import re
import sys
import tempfile
import traceback
import tkinter as tk
from contextlib import contextmanager
from tkinter import ttk, filedialog, messagebox, simpledialog

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ArrayObject, DictionaryObject
from pypdf.constants import UserAccessPermissions
from pypdf.errors import DependencyError

# ── Optional dependencies ────────────────────────────────────────────────────
try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except Exception:
    HAS_PDFIUM = False

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# ImageTk в некоторых дистрибутивах Linux ставится отдельным пакетом
# (python3-pil.imagetk), поэтому проверяется отдельно от Pillow.
try:
    from PIL import ImageTk
    HAS_PIL_TK = True
except Exception:
    HAS_PIL_TK = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False

try:
    import cryptography  # noqa: F401  — нужен pypdf для шифрования AES
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    DND_FILES = None
    _BaseTk = tk.Tk
    HAS_DND = False

HAS_THUMBS = HAS_PDFIUM and HAS_PIL and HAS_PIL_TK


# ── Program identity ─────────────────────────────────────────────────────────
__version__   = "1.0"
__license__   = "MIT"

APP_NAME      = "PDF Manager"                 # краткое наименование (интерфейс)
APP_NAME_FULL = "Программа для управления PDF-документами «PDF Manager»"
APP_VERSION   = __version__
APP_YEAR      = "2026"


# ── Colour palette (light theme) ────────────────────────────────────────────
BG        = "#FFFFFF"   # main background
SURFACE   = "#F4F5F9"   # header / status bar / panels
SURFACE2  = "#EAECF4"   # cards, nav items, input backgrounds
ACCENT    = "#5B4BE0"
ACCENT2   = "#463AB8"
TEXT      = "#1C1B29"
TEXT_DIM  = "#6B6A80"
SUCCESS   = "#1B7F3B"
DANGER    = "#C62828"
WARNING   = "#B25E00"
BORDER    = "#D5D8E4"

FONT_H1   = ("Segoe UI", 18, "bold")
FONT_H2   = ("Segoe UI", 13, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_NAV  = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)

THUMB_W   = 132         # thumbnail width, px
THUMB_MAX_H = 190       # thumbnail height limit: узкая длинная страница
                        # иначе отрисовывается в сотни мегапикселей
THUMB_COLS = 5

JPEG_QUALITY = 95       # качество JPEG при сборке PDF из изображений


# Программа может работать как из исходных текстов, так и в виде одного
# исполняемого файла, собранного PyInstaller. Во втором случае вложенные
# ресурсы распаковываются во временный каталог sys._MEIPASS.
IS_FROZEN = getattr(sys, "frozen", False)


def resource_path(*parts):
    """Путь к вложенному ресурсу — одинаково работает из .py и из .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class Cancelled(Exception):
    """Пользователь отменил операцию — сообщение об ошибке не показываем."""


def _luminance(hex_color):
    """Perceived brightness of #RRGGBB in the 0..255 range."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def contrast_fg(bg_color):
    """Pick a readable text colour for the given background."""
    return TEXT if _luminance(bg_color) > 150 else "#FFFFFF"


def shift(hex_color, amount):
    """Lighten (amount > 0) or darken (amount < 0) a #RRGGBB colour."""
    parts = []
    for i in (1, 3, 5):
        v = int(hex_color[i:i + 2], 16) + amount
        parts.append(max(0, min(255, v)))
    return "#{:02X}{:02X}{:02X}".format(*parts)


# ── Helpers ──────────────────────────────────────────────────────────────────
def parse_page_range(text, total):
    """Parse '1,3,5-8,10' -> sorted zero-based page indices (no duplicates)."""
    pages = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a.strip()), int(b.strip())
            except ValueError:
                raise ValueError(f"«{part}» — не диапазон страниц") from None
            if a < 1 or b > total or a > b:
                raise ValueError(f"Диапазон {a}-{b} выходит за пределы (1–{total})")
            pages.update(range(a - 1, b))
        else:
            try:
                n = int(part)
            except ValueError:
                raise ValueError(f"«{part}» — не номер страницы") from None
            if n < 1 or n > total:
                raise ValueError(f"Страница {n} выходит за пределы (1–{total})")
            pages.add(n - 1)
    if not pages:
        raise ValueError("Не указано ни одной страницы")
    return sorted(pages)


def parse_page_order(text, total):
    """Like parse_page_range, but keeps the given order and allows repeats.

    Обратные диапазоны разрешены: '10-1' = страницы с 10-й по 1-ю.
    """
    order = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a.strip()), int(b.strip())
            except ValueError:
                raise ValueError(f"«{part}» — не диапазон страниц") from None
            if min(a, b) < 1 or max(a, b) > total:
                raise ValueError(f"Диапазон {a}-{b} выходит за пределы (1–{total})")
            step = 1 if b >= a else -1
            order.extend(n - 1 for n in range(a, b + step, step))
        else:
            try:
                n = int(part)
            except ValueError:
                raise ValueError(f"«{part}» — не номер страницы") from None
            if n < 1 or n > total:
                raise ValueError(f"Страница {n} выходит за пределы (1–{total})")
            order.append(n - 1)
    if not order:
        raise ValueError("Не указано ни одной страницы")
    return order


def compress_ranges(indices):
    """[0,1,2,4] -> '1-3,5' (человекочитаемая запись для поля ввода)."""
    if not indices:
        return ""
    nums = sorted({i + 1 for i in indices})
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(out)


def short_name(path, max_len=38):
    name = os.path.basename(path)
    return name if len(name) <= max_len else "…" + name[-(max_len - 1):]


def human_size(num_bytes):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if num_bytes < 1024 or unit == "ГБ":
            return f"{num_bytes:.0f} {unit}" if unit == "Б" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0


def safe_stem(text, fallback="page", max_len=48):
    """Превратить заголовок закладки в безопасное имя файла."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "_", (text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return (cleaned[:max_len] or fallback)


def unique_path(path):
    """Добавить ' (2)', ' (3)'… если файл уже существует."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


AES_REQUIRED = ("Файл зашифрован алгоритмом AES. Для работы с такими "
                "документами установите пакет cryptography:\n\n"
                "    pip install cryptography")


def _try_decrypt(reader, password):
    """decrypt() с понятными ошибками; True — пароль подошёл."""
    try:
        return bool(reader.decrypt(password))
    except DependencyError:
        raise RuntimeError(AES_REQUIRED) from None
    except Exception as e:
        raise RuntimeError(f"Не удалось расшифровать файл: {e}") from e


def open_pdf(path, parent=None):
    """Открыть PDF, при необходимости запросив пароль.

    Возвращает (reader, password | None). Пустая строка вместо пароля
    означает документ, у которого есть только ограничения владельца:
    он открывается без пароля, но формально зашифрован. Бросает Cancelled,
    если пользователь закрыл диалог ввода пароля.
    """
    try:
        reader = PdfReader(path)
    except DependencyError:
        raise RuntimeError(AES_REQUIRED) from None
    if not reader.is_encrypted:
        return reader, None
    if _try_decrypt(reader, ""):
        return reader, ""
    name = short_name(path)
    for attempt in range(3):
        prompt = (f"Файл «{name}» защищён паролем.\nВведите пароль:"
                  if attempt == 0 else "Неверный пароль. Попробуйте ещё раз:")
        pwd = simpledialog.askstring(APP_NAME, prompt, show="•", parent=parent)
        if pwd is None:
            raise Cancelled
        if _try_decrypt(reader, pwd):
            return reader, pwd
    raise ValueError("Не удалось снять защиту: неверный пароль.")


def page_count(path):
    """Число страниц без запроса пароля; None, если файл не прочитать.

    Только для справочных подписей (очередь слияния). Для операций
    документ открывается через open_pdf().
    """
    try:
        return len(PdfReader(path).pages)
    except Exception:
        return None


def ask_save_pdf(title="Сохранить как…", initial=None):
    return filedialog.asksaveasfilename(
        defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
        title=title, initialfile=initial)


def check_not_same(src, dst):
    """Не дать перезаписать исходный файл: pypdf читает страницы лениво."""
    try:
        if src and dst and os.path.exists(dst) and os.path.samefile(src, dst):
            messagebox.showerror(
                "Нельзя перезаписать исходник",
                "Результат нельзя сохранять поверх исходного файла — "
                "он читается по мере записи и будет повреждён.\n\n"
                "Выберите другое имя файла.")
            return False
    except OSError:
        pass
    return True


def _current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


_FILE_MODE = 0o666 & ~_current_umask()


@contextmanager
def atomic_open(path, mode="wb", **kwargs):
    """Запись через временный файл в той же папке с заменой в конце.

    Если запись прервётся (битая страница, нет места, файл занят), прежний
    файл с тем же именем останется нетронутым, а недописанный — удалится.
    """
    folder = os.path.dirname(os.path.abspath(path))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=folder)
    except PermissionError:
        # в папку писать нельзя, а в сам файл, возможно, можно
        with open(path, mode, **kwargs) as f:
            yield f
        return
    try:
        with os.fdopen(fd, mode, **kwargs) as f:
            yield f
        os.chmod(tmp, _FILE_MODE)       # mkstemp создаёт файл с правами 0600
        try:
            os.replace(tmp, path)
        except OSError as e:
            raise OSError(f"Не удалось сохранить «{os.path.basename(path)}»: "
                          f"{e.strerror or e}. Возможно, файл открыт в другой "
                          "программе.") from e
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_pdf(writer, out_path):
    with atomic_open(out_path) as f:
        writer.write(f)


def copy_metadata(reader, writer):
    """Перенести свойства документа (/Info); False — если не удалось."""
    if not reader.metadata:
        return True
    try:
        writer.add_metadata(reader.metadata)
        return True
    except Exception:
        return False


def strip_metadata(writer):
    """Убрать /Info (в т. ч. /Producer, который pypdf ставит сам) и XMP."""
    writer.metadata = None
    root = writer.root_object
    if "/Metadata" in root:
        del root["/Metadata"]


def select_pages(reader, indices):
    """Новый документ из страниц indices (порядок и повторы сохраняются).

    Возвращает (writer, замечания для пользователя). append() отбрасывает
    ссылки на страницы, не вошедшие в результат, и переносит относящиеся
    к ним закладки. Но повторённую страницу он копирует один раз — ссылки
    и поля формы остались бы только у последней копии, — а на повреждённых
    аннотациях падает. В этих случаях страницы копируются по одной после
    prune_links(): иначе ссылка на удалённую страницу тянет её содержимое
    в новый файл.
    """
    indices = list(indices)
    notes = []
    writer = None
    if len(set(indices)) == len(indices):
        try:
            writer = PdfWriter()
            writer.append(reader, pages=indices)
        except Exception as e:
            writer = None
            notes.append(f"закладки не перенесены: структура файла повреждена ({e})")
    elif reader.outline:
        notes.append("закладки не перенесены: страницы в порядке повторяются")
    if writer is None:
        prune_links(reader, indices)
        writer = PdfWriter()
        for i in indices:
            writer.add_page(reader.pages[i])
    if not copy_metadata(reader, writer):
        notes.append("свойства документа (автор, заголовок) не перенесены")
    return writer, notes


def clone_document(reader):
    """Полная копия документа: закладки, формы, метки страниц, свойства.

    Возвращает (writer, предупреждение | None). Если структура документа
    повреждена и не копируется целиком, переносятся только страницы.
    """
    try:
        return PdfWriter(clone_from=reader), None
    except Exception as e:
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        copy_metadata(reader, writer)
        return writer, f"закладки и формы не перенесены ({e})"


def prune_links(reader, indices):
    """Удалить у страниц ссылки на страницы, не входящие в indices.

    Нужно перед постраничным add_page(): иначе целевая страница вместе
    с содержимым попадает в результат как невидимый объект.
    """
    kept = {getattr(reader.pages[i].indirect_reference, "idnum", None)
            for i in indices}
    for i in set(indices):
        page = reader.pages[i]
        annots = page.get("/Annots")
        annots = annots.get_object() if annots is not None else None
        if not isinstance(annots, ArrayObject):
            continue
        own = getattr(page.indirect_reference, "idnum", None)
        survivors = []
        for ref in annots:
            annot = ref.get_object() if ref is not None else None
            if not isinstance(annot, DictionaryObject):
                survivors.append(ref)   # битая запись: не наша забота, add_page её снесёт
                continue
            target = _link_target(annot)
            if target is not None and target not in kept:
                continue
            # /P — страница-владелец; чужая страница здесь тоже потянула бы
            # своё содержимое
            p_id = getattr(annot.raw_get("/P"), "idnum", None) if "/P" in annot else None
            if p_id is not None and p_id != own and p_id not in kept:
                del annot["/P"]
            survivors.append(ref)
        annots[:] = survivors


def _link_target(annot):
    """idnum страницы, на которую ведёт ссылка-аннотация, или None."""
    dest = annot.get("/Dest")
    if dest is None:
        action = annot.get("/A")
        action = action.get_object() if action is not None else None
        if action is not None and action.get("/S") == "/GoTo":
            dest = action.get("/D")
    if dest is None:
        return None
    dest = dest.get_object()
    if isinstance(dest, DictionaryObject):        # /D << /D [...] >>
        dest = dest.get("/D")
    if isinstance(dest, list) and dest:
        return getattr(dest[0], "idnum", None)
    return None                 # именованное назначение в файл не копируется


def error_log_path():
    """Файл журнала ошибок: %LOCALAPPDATA% в Windows, ~/.cache в Linux."""
    base = (os.environ.get("LOCALAPPDATA")
            or os.path.join(os.path.expanduser("~"), ".cache"))
    return os.path.join(base, APP_NAME, "errors.log")


def log_exception(exc_type, exc, tb):
    """Записать трассировку в журнал; вернуть путь или None.

    В портативной сборке нет консоли (sys.stderr is None), поэтому без
    журнала подробности ошибки были бы потеряны.
    """
    path = error_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now().isoformat(timespec='seconds')}"
                    f"  {APP_NAME} {__version__} ===\n")
            f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        return path
    except OSError:
        return None


_REGISTERED_FONT = None


def cyrillic_font():
    """Найти и зарегистрировать TTF с кириллицей для reportlab.

    Встроенные шрифты reportlab (Helvetica) кириллицу не содержат, поэтому
    подбираем системный шрифт. Если ничего не нашли — вернём Helvetica,
    и вызывающий код предупредит пользователя.
    """
    global _REGISTERED_FONT
    if _REGISTERED_FONT:
        return _REGISTERED_FONT
    candidates = [
        # вложенный в программу шрифт — работает на любом ПК без настройки
        ("DejaVuSans", resource_path("assets", "DejaVuSans.ttf")),
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("DejaVuSans", "/usr/share/fonts/TTF/DejaVuSans.ttf"),
        ("LiberationSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("Arial", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")),
        ("Calibri", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "calibri.ttf")),
        ("Helvetica-mac", "/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for name, path in candidates:
        try:
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
                _REGISTERED_FONT = name
                return name
        except Exception:
            continue
    _REGISTERED_FONT = "Helvetica"
    return _REGISTERED_FONT


def flatten_outline(reader):
    """Плоский список закладок: [(заголовок, индекс страницы, уровень), …]."""
    items = []

    def walk(node, depth=0):
        for it in node:
            if isinstance(it, list):
                walk(it, depth + 1)
            else:
                try:
                    page_no = reader.get_destination_page_number(it)
                except Exception:
                    continue
                if page_no is None:     # закладка без страницы-цели
                    continue
                title = getattr(it, "title", None) or "Без названия"
                items.append((str(title), page_no, depth))

    try:
        walk(reader.outline)
    except Exception:
        return []
    return items


def plan_by_bookmarks(marks, total):
    """Части документа по закладкам верхнего уровня.

    marks — [(заголовок, индекс страницы, уровень)]. Страницы до первой
    закладки (обложка, введение) идут отдельной частью, несколько закладок
    на одной странице открывают одну общую часть — иначе страницы
    терялись бы или повторялись.
    """
    starts = []
    for title, page_no, _ in sorted(marks, key=lambda m: m[1]):
        if 0 <= page_no < total and (not starts or starts[-1][1] != page_no):
            starts.append((title, page_no))
    if not starts:
        raise ValueError("Закладки не указывают на страницы документа")
    if starts[0][1] > 0:
        starts.insert(0, ("начало", 0))
    plan = []
    for i, (title, first) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else total
        plan.append((f"{i + 1:02d}_{safe_stem(title)}", list(range(first, end))))
    return plan


def visible_frame(page):
    """Видимый размер страницы и матрица из видимых координат в её собственные.

    Подложка рисуется так, как страницу видит читатель: по CropBox и с учётом
    /Rotate (поворот по часовой стрелке при показе). Матрица переносит
    рисунок в неповёрнутое пространство страницы, начало которого может
    быть смещено.
    """
    box = page.cropbox
    x0, y0 = float(box.left), float(box.bottom)
    w, h = float(box.width), float(box.height)
    rot = page.rotation % 360
    if rot == 90:
        return (h, w), Transformation((0, 1, -1, 0, x0 + w, y0))
    if rot == 180:
        return (w, h), Transformation((-1, 0, 0, -1, x0 + w, y0 + h))
    if rot == 270:
        return (h, w), Transformation((0, -1, 1, 0, x0, y0 + h))
    return (w, h), Transformation((1, 0, 0, 1, x0, y0))


# ── Custom widgets ───────────────────────────────────────────────────────────
class StyledButton(tk.Label):
    def __init__(self, parent, text, command, color=ACCENT, **kw):
        fg = contrast_fg(color)
        super().__init__(parent, text=text, bg=color, fg=fg,
                         font=("Segoe UI", 10, "bold"), cursor="hand2",
                         relief="flat", padx=12, pady=6, **kw)
        self._color = color
        # light buttons get darker on hover, dark ones get lighter
        self._hover = shift(color, -22 if _luminance(color) > 150 else 30)
        self._cmd   = command
        self.bind("<Enter>",    lambda e: self.config(bg=self._hover))
        self.bind("<Leave>",    lambda e: self.config(bg=self._color))
        self.bind("<Button-1>", lambda e: self._click())

    def _click(self):
        if callable(self._cmd):
            self._cmd()


class SectionHeader(tk.Frame):
    def __init__(self, parent, title, subtitle=""):
        super().__init__(parent, bg=BG)
        tk.Label(self, text=title, fg=TEXT, bg=BG, font=FONT_H2).pack(anchor="w")
        if subtitle:
            tk.Label(self, text=subtitle, fg=TEXT_DIM, bg=BG, font=FONT_SM,
                     justify="left").pack(anchor="w")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(6, 0))


class FileCard(tk.Frame):
    """One row in the merge list with optional per-file page range."""

    def __init__(self, parent, path, index, remove_cb, move_cb, range_var,
                 total=None, pick_cb=None):
        super().__init__(parent, bg=SURFACE2, pady=5, padx=8)
        self.path = path
        # число страниц считается один раз при добавлении файла в очередь:
        # карточки пересоздаются при каждой перестановке
        self._total = total
        pages_label = f"{total} стр." if total else "?"

        self._range_var = range_var

        # ── Top row: index · filename · page count · move · remove ───────────
        top = tk.Frame(self, bg=SURFACE2)
        top.pack(fill="x")

        tk.Label(top, text=f"{index + 1}.", fg=ACCENT2, bg=SURFACE2,
                 font=FONT_BODY, width=3, anchor="e").pack(side="left")
        tk.Label(top, text=short_name(path), fg=TEXT, bg=SURFACE2,
                 font=FONT_BODY, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(top, text=pages_label, fg=TEXT_DIM, bg=SURFACE2,
                 font=FONT_SM).pack(side="left", padx=6)

        # packed to the right, поэтому список перевёрнут: на экране ↑ ↓ ✕
        for sym, cb in [("✕", lambda: remove_cb(index)),
                        ("↓", lambda: move_cb(index,  1)),
                        ("↑", lambda: move_cb(index, -1))]:
            btn = tk.Label(top, text=sym, fg=TEXT_DIM, bg=SURFACE2,
                           font=("Segoe UI", 11, "bold"), cursor="hand2")
            btn.pack(side="right", padx=2)
            btn.bind("<Enter>", lambda e, b=btn, s=sym:
                     b.config(fg=DANGER if s == "✕" else ACCENT2))
            btn.bind("<Leave>", lambda e, b=btn: b.config(fg=TEXT_DIM))
            btn.bind("<Button-1>", lambda e, c=cb: c())

        # ── Bottom row: page range entry ─────────────────────────────────────
        bot = tk.Frame(self, bg=SURFACE2)
        bot.pack(fill="x", pady=(4, 0))

        tk.Label(bot, text="Страницы:", fg=TEXT_DIM, bg=SURFACE2,
                 font=FONT_SM).pack(side="left", padx=(22, 4))

        entry = tk.Entry(bot, textvariable=self._range_var,
                         bg=BG, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=FONT_MONO, width=22,
                         highlightthickness=1, highlightcolor=ACCENT,
                         highlightbackground=BORDER)
        entry.pack(side="left", ipady=3)

        if pick_cb and self._total:
            pick = tk.Label(bot, text="▦", fg=ACCENT2, bg=SURFACE2, cursor="hand2",
                            font=("Segoe UI", 11, "bold"))
            pick.pack(side="left", padx=4)
            pick.bind("<Button-1>", lambda e: pick_cb(self.path, self._range_var))

        hint = (f"пусто = все  (1–{self._total})" if self._total else "пусто = все")
        tk.Label(bot, text=hint, fg=TEXT_DIM, bg=SURFACE2,
                 font=FONT_SM).pack(side="left", padx=8)

        self._dot = tk.Label(bot, text="", bg=SURFACE2, font=FONT_SM)
        self._dot.pack(side="left")
        # StringVar переживает карточку, поэтому подписку нужно снимать
        self._trace = self._range_var.trace_add("write", lambda *_: self._validate())
        self._validate()

    def destroy(self):
        try:
            self._range_var.trace_remove("write", self._trace)
        except (AttributeError, tk.TclError):
            pass
        super().destroy()

    def _validate(self):
        rng = self._range_var.get().strip()
        if not rng or self._total is None:
            self._dot.config(text="")
            return
        try:
            pages = parse_page_range(rng, self._total)
            self._dot.config(text=f"✔ {len(pages)} стр.", fg=SUCCESS)
        except Exception:
            self._dot.config(text="✖ неверный диапазон", fg=DANGER)


class SourceFile(tk.Frame):
    """Строка выбора одного исходного PDF + сведения о нём."""

    def __init__(self, parent, app, on_load=None, label="PDF-файл:"):
        super().__init__(parent, bg=BG)
        self._app = app
        self._on_load = on_load
        self.path = None
        self.total = None
        self.password = None

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text=label, fg=TEXT_DIM, bg=BG, font=FONT_SM).pack(side="left")
        self._name_var = tk.StringVar(value="Файл не выбран")
        tk.Label(row, textvariable=self._name_var, fg=TEXT, bg=BG,
                 font=FONT_BODY).pack(side="left", padx=8)
        StyledButton(row, "Выбрать…", self.choose, color=SURFACE2).pack(side="right")

        self._info_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._info_var, fg=ACCENT2, bg=BG,
                 font=FONT_SM).pack(anchor="w", pady=(2, 0))

    def choose(self, path=None):
        path = path or filedialog.askopenfilename(
            title="Выберите PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            reader, pwd = open_pdf(path, self._app)
        except Cancelled:
            return
        except Exception as e:
            messagebox.showerror("Не удалось открыть файл", str(e))
            return
        self.path = path
        self.password = pwd
        self.total = len(reader.pages)
        self._name_var.set(short_name(path))
        try:
            size = human_size(os.path.getsize(path))
        except OSError:
            size = "?"
        lock = {None: "", "": "  ·  🔒 ограничения владельца"}.get(
            pwd, "  ·  🔒 защищён паролем")
        self._info_var.set(f"Страниц: {self.total}  ·  {size}{lock}")
        if callable(self._on_load):
            self._on_load(reader)

    @property
    def protection(self):
        """Описание защиты исходника для предупреждений или None."""
        if self.password is None:
            return None
        return "защищён паролем" if self.password else "имеет ограничения владельца"

    def reader(self):
        """Свежий PdfReader (уже расшифрованный) для текущего файла."""
        reader = PdfReader(self.path)
        if reader.is_encrypted and self.password is not None:
            if not _try_decrypt(reader, self.password):
                raise ValueError("Пароль больше не подходит: файл изменился "
                                 "после выбора. Выберите его заново.")
        if len(reader.pages) != self.total:
            raise ValueError("Файл изменился после выбора. Выберите его заново.")
        return reader

    def require(self):
        if not self.path:
            messagebox.showwarning("Нет файла", "Сначала выберите PDF-файл.")
            return False
        return True


class RangeField(tk.Frame):
    """Поле ввода диапазона страниц с подсказкой, проверкой и миниатюрами."""

    def __init__(self, parent, app, source, label, hint="", accent=ACCENT2,
                 describe=None):
        super().__init__(parent, bg=BG)
        self._app = app
        self._source = source
        self._describe = describe
        self.var = tk.StringVar()

        tk.Label(self, text=label, fg=TEXT, bg=BG, font=FONT_BODY).pack(anchor="w")

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=4)
        entry = tk.Entry(row, textvariable=self.var, bg=BG, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=FONT_MONO,
                         highlightthickness=1, highlightcolor=ACCENT,
                         highlightbackground=BORDER)
        entry.pack(side="left", fill="x", expand=True, ipady=6)
        StyledButton(row, "▦ Выбрать по миниатюрам", self._pick,
                     color=SURFACE2).pack(side="left", padx=(8, 0))

        if hint:
            tk.Label(self, text=hint, fg=TEXT_DIM, bg=BG,
                     font=FONT_SM).pack(anchor="w")

        self._preview = tk.Label(self, text="", fg=accent, bg=BG, font=FONT_SM)
        self._preview.pack(anchor="w", pady=3)
        self._accent = accent
        self.var.trace_add("write", lambda *_: self.update_preview())

    def _pick(self):
        if not self._source.require():
            return
        picked = ThumbnailPicker(self._app, self._source, self.var.get()).show()
        if picked is not None:
            self.var.set(picked)

    def update_preview(self):
        total = self._source.total
        rng = self.var.get().strip()
        if not total or not rng:
            self._preview.config(text="")
            return
        try:
            pages = parse_page_range(rng, total)
        except Exception as e:
            self._preview.config(text=f"⚠ {e}", fg=DANGER)
            return
        text = (self._describe(pages, total) if self._describe
                else f"Выбрано страниц: {len(pages)}")
        self._preview.config(text=text, fg=self._accent if pages else TEXT_DIM)

    def indices(self):
        return parse_page_range(self.var.get().strip(), self._source.total)


class ThumbnailPicker(tk.Toplevel):
    """Модальный выбор страниц галочками.

    С pypdfium2 + Pillow показывает миниатюры, без них — просто сетку
    номеров страниц (функция остаётся рабочей).
    """

    def __init__(self, app, source, preselect=""):
        super().__init__(app)
        self.title(f"Выбор страниц — {short_name(source.path)}")
        self.configure(bg=BG)
        self.geometry("880x620")
        self.minsize(560, 420)
        self.transient(app)
        self._source = source
        self._result = None
        self._vars = []
        self._photos = []          # держим ссылки, иначе Tk соберёт картинки
        self._labels = []
        self._doc = None
        self._after_id = None      # отложенный шаг отрисовки, отменяется в _close

        total = source.total
        try:
            selected = set(parse_page_range(preselect.strip(), total)) if preselect.strip() else set()
        except Exception:
            selected = set()

        top = tk.Frame(self, bg=SURFACE, padx=14, pady=10)
        top.pack(fill="x")
        tk.Label(top, text=f"Страниц в документе: {total}", fg=TEXT, bg=SURFACE,
                 font=FONT_BODY).pack(side="left")
        for text, cb in [("Выделить все", lambda: self._set_all(True)),
                         ("Снять все", lambda: self._set_all(False)),
                         ("Инвертировать", self._invert)]:
            StyledButton(top, text, cb, color=SURFACE2).pack(side="left", padx=(8, 0))
        self._progress = tk.Label(top, text="", fg=TEXT_DIM, bg=SURFACE, font=FONT_SM)
        self._progress.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(body, orient="vertical", command=canvas.yview,
                          bg=SURFACE2, troughcolor=SURFACE, activebackground=ACCENT2,
                          highlightthickness=0, bd=0, relief="flat", width=12)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        grid = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=grid, anchor="nw")
        grid.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        for seq, delta in (("<MouseWheel>", None), ("<Button-4>", -1), ("<Button-5>", 1)):
            canvas.bind_all(seq, lambda e, c=canvas, d=delta: self._scroll(e, c, d))

        for i in range(total):
            cell = tk.Frame(grid, bg=SURFACE2, padx=6, pady=6)
            cell.grid(row=i // THUMB_COLS, column=i % THUMB_COLS, padx=6, pady=6, sticky="n")
            holder = tk.Label(cell, bg=BG, width=16, height=9, relief="flat",
                              text="…", fg=TEXT_DIM, font=FONT_SM)
            holder.pack()
            self._labels.append(holder)
            var = tk.BooleanVar(value=(i in selected))
            self._vars.append(var)
            tk.Checkbutton(cell, text=f"стр. {i + 1}", variable=var, bg=SURFACE2,
                           fg=TEXT, selectcolor=BG, activebackground=SURFACE2,
                           activeforeground=TEXT, font=FONT_SM,
                           highlightthickness=0, bd=0,
                           command=self._update_counter).pack(pady=(4, 0))

        bottom = tk.Frame(self, bg=SURFACE, padx=14, pady=10)
        bottom.pack(fill="x", side="bottom")
        self._counter = tk.Label(bottom, text="", fg=TEXT_DIM, bg=SURFACE, font=FONT_SM)
        self._counter.pack(side="left")
        StyledButton(bottom, "Применить", self._ok).pack(side="right")
        StyledButton(bottom, "Отмена", self._cancel, color=SURFACE2).pack(side="right", padx=8)

        self._update_counter()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        if HAS_THUMBS:
            self._after_id = self.after(30, lambda: self._render(0))
        else:
            self._progress.config(
                text="миниатюры недоступны: нет pypdfium2 / Pillow")
            for lb in self._labels:
                lb.config(text="PDF")

    # ── rendering ────────────────────────────────────────────────────────────
    def _render(self, i):
        """Порционный рендер: окно остаётся отзывчивым без потоков."""
        if not self.winfo_exists():
            return
        if self._doc is None:
            try:
                self._doc = pdfium.PdfDocument(self._source.path,
                                              password=self._source.password)
            except Exception as e:
                self._progress.config(text=f"не удалось отрисовать: {e}")
                return
        total = len(self._labels)
        if i >= total:
            self._progress.config(text="")
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
            return
        try:
            page = self._doc[i]
            w, h = page.get_size()
            scale = min(THUMB_W / max(w, 1.0), THUMB_MAX_H / max(h, 1.0))
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            photo = ImageTk.PhotoImage(pil)
            self._photos.append(photo)
            self._labels[i].config(image=photo, text="", width=pil.width,
                                   height=pil.height)
        except Exception:
            self._labels[i].config(text=f"стр. {i + 1}\n(не отрисована)")
        self._progress.config(text=f"отрисовка… {i + 1}/{total}")
        self._after_id = self.after(1, lambda: self._render(i + 1))

    def _scroll(self, event, canvas, delta):
        if delta is None:
            delta = -1 if event.delta > 0 else 1
        canvas.yview_scroll(delta, "units")

    # ── actions ──────────────────────────────────────────────────────────────
    def _set_all(self, value):
        for v in self._vars:
            v.set(value)
        self._update_counter()

    def _invert(self):
        for v in self._vars:
            v.set(not v.get())
        self._update_counter()

    def _update_counter(self):
        n = sum(1 for v in self._vars if v.get())
        self._counter.config(text=f"Отмечено страниц: {n}")

    def _ok(self):
        self._result = compress_ranges([i for i, v in enumerate(self._vars) if v.get()])
        self._close()

    def _cancel(self):
        self._result = None
        self._close()

    def _close(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.unbind_all(seq)
            except Exception:
                pass
        try:
            if self._doc is not None:
                self._doc.close()
        except Exception:
            pass
        self.destroy()

    def show(self):
        self.grab_set()
        self.wait_window()
        return self._result


class LicensesDialog(tk.Toplevel):
    """Полные тексты лицензий сторонних компонентов, вложенных в программу."""

    def __init__(self, app, path):
        super().__init__(app)
        self.title("Лицензии сторонних компонентов")
        self.configure(bg=BG)
        self.geometry("860x640")
        self.minsize(520, 400)
        self.transient(app)

        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        text = tk.Text(frame, bg=BG, fg=TEXT, font=FONT_MONO, relief="flat",
                       wrap="word", padx=12, pady=10, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=BORDER)
        sb = tk.Scrollbar(frame, orient="vertical", command=text.yview,
                          bg=SURFACE2, troughcolor=SURFACE, activebackground=ACCENT2,
                          highlightthickness=0, bd=0, relief="flat", width=12)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Не удалось прочитать файл лицензий:\n{e}"
        text.insert("1.0", content)
        text.config(state="disabled")

        foot = tk.Frame(self, bg=SURFACE, padx=14, pady=10)
        foot.pack(fill="x")
        tk.Label(foot, text="Библиотеки — разрешительные лицензии; загрузчик "
                            "PyInstaller — GPL с исключением для программ",
                 fg=TEXT_DIM, bg=SURFACE, font=FONT_SM).pack(side="left")
        StyledButton(foot, "Закрыть", self.destroy).pack(side="right")
        self.grab_set()


class AboutDialog(tk.Toplevel):
    """Окно «О программе» со сведениями о версии и лицензиях."""

    def __init__(self, app):
        super().__init__(app)
        self.title(f"О программе — {APP_NAME}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)

        head = tk.Frame(self, bg=SURFACE, padx=24, pady=18)
        head.pack(fill="x")
        tk.Label(head, text="📄", bg=SURFACE, font=("Segoe UI", 28)).pack(side="left")
        box = tk.Frame(head, bg=SURFACE)
        box.pack(side="left", padx=14)
        tk.Label(box, text=APP_NAME, fg=TEXT, bg=SURFACE, font=FONT_H1).pack(anchor="w")
        tk.Label(box, text=f"Версия {APP_VERSION}", fg=TEXT_DIM, bg=SURFACE,
                 font=FONT_SM).pack(anchor="w")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=APP_NAME_FULL, fg=TEXT, bg=BG, font=FONT_BODY,
                 justify="left", wraplength=430).pack(anchor="w")
        tk.Label(body, text="Объединение, разделение и правка страниц,\n"
                            "защита, метаданные, сжатие и экспорт.",
                 fg=TEXT_DIM, bg=BG, font=FONT_SM,
                 justify="left").pack(anchor="w", pady=(4, 0))

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=12)

        rows = [
            ("Версия", APP_VERSION),
            ("Год создания", APP_YEAR),
            ("Лицензия", __license__),
            ("Среда выполнения", f"Python {sys.version.split()[0]}, Tk {tk.TkVersion}"),
        ]
        if IS_FROZEN:
            rows.append(("Вид поставки", "портативный исполняемый файл"))
        for label, value in rows:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{label}:", fg=TEXT_DIM, bg=BG, font=FONT_SM,
                     width=18, anchor="w").pack(side="left")
            tk.Label(row, text=value, fg=TEXT, bg=BG, font=FONT_SM).pack(side="left")

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=12)
        tk.Label(body, text="Используемые библиотеки и их лицензии",
                 fg=TEXT, bg=BG, font=FONT_H2).pack(anchor="w", pady=(0, 6))

        libs = [
            ("Python / Tkinter", "PSF License, Tcl/Tk (BSD)", True),
            ("pypdf", "BSD-3-Clause", True),
            ("pypdfium2", "BSD-3-Clause / Apache-2.0", HAS_PDFIUM),
            ("Pillow", "MIT-CMU", HAS_PIL),
            ("reportlab", "BSD-3-Clause", HAS_REPORTLAB),
            ("tkinterdnd2", "MIT", app.dnd_enabled),
            ("cryptography", "Apache-2.0 / BSD-3-Clause", HAS_CRYPTO),
        ]
        for name, lic, present in libs:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="●", fg=SUCCESS if present else TEXT_DIM, bg=BG,
                     font=FONT_SM).pack(side="left")
            tk.Label(row, text=name, fg=TEXT, bg=BG, font=FONT_SM, width=18,
                     anchor="w").pack(side="left", padx=4)
            tk.Label(row, text=lic, fg=TEXT_DIM, bg=BG, font=FONT_SM).pack(side="left")
            if not present:
                tk.Label(row, text="— не установлена", fg=WARNING, bg=BG,
                         font=FONT_SM).pack(side="left", padx=6)

        tk.Label(body, text="Все перечисленные лицензии являются разрешительными\n"
                            "и допускают использование библиотек в составе\n"
                            "данной программы без раскрытия её исходного кода.\n"
                            "Полный состав и тексты лицензий — «Тексты лицензий».",
                 fg=TEXT_DIM, bg=BG, font=FONT_SM, justify="left").pack(anchor="w", pady=(10, 0))

        foot = tk.Frame(self, bg=SURFACE, padx=24, pady=12)
        foot.pack(fill="x")
        StyledButton(foot, "Закрыть", self.destroy).pack(side="right")
        notices = resource_path("assets", "THIRD-PARTY-NOTICES.txt")
        if os.path.exists(notices):
            StyledButton(foot, "Тексты лицензий",
                         lambda: LicensesDialog(self, notices),
                         color=SURFACE2).pack(side="right", padx=8)

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + 60
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()


# ── Main application ─────────────────────────────────────────────────────────
class PDFManager(_BaseTk):

    NAV = [
        ("Объединение", [("merge",    "Объединить PDF"),
                         ("img2pdf",  "Изображения → PDF")]),
        ("Страницы",    [("delete",   "Удалить страницы"),
                         ("extract",  "Извлечь диапазон"),
                         ("rotate",   "Повернуть страницы"),
                         ("order",    "Порядок страниц"),
                         ("split",    "Разделить файл")]),
        ("Документ",    [("meta",     "Метаданные"),
                         ("secure",   "Защита паролем"),
                         ("compress", "Сжатие"),
                         ("stamp",    "Нумерация и водяной знак")]),
        ("Экспорт",     [("export",   "Текст и изображения")]),
    ]

    def __init__(self):
        self.dnd_enabled = HAS_DND
        try:
            super().__init__()
        except (RuntimeError, tk.TclError):
            # TkinterDnD.Tk сначала создаёт обычное окно Tk, затем подгружает
            # библиотеку tkdnd. Если не загрузилась она — работаем без DnD.
            if not HAS_DND or getattr(self, "tk", None) is None:
                raise
            self.dnd_enabled = False
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1080x740")
        self.minsize(940, 660)
        self.configure(bg=BG)
        self._apply_icon()
        # Each entry: {"path": str, "range_var": tk.StringVar}
        self._merge_entries = []
        self._image_paths = []
        self._pages = {}
        self._nav_items = {}
        self._current = None
        self._build_ui()
        self._show("merge")

    def _apply_icon(self):
        """Значок окна; отсутствие файла значка не должно мешать запуску."""
        for name, method in (("icon.ico", "iconbitmap"), ("icon.png", "iconphoto")):
            path = resource_path("assets", name)
            if not os.path.exists(path):
                continue
            try:
                if method == "iconbitmap":
                    self.iconbitmap(path)
                else:
                    self._icon_image = tk.PhotoImage(file=path)
                    self.iconphoto(True, self._icon_image)
                return
            except Exception:
                continue

    # ── Layout ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        header = tk.Frame(self, bg=SURFACE, pady=12, padx=20)
        header.pack(fill="x")
        tk.Label(header, text=f"📄 {APP_NAME}", fg=TEXT, bg=SURFACE,
                 font=FONT_H1).pack(side="left")
        tk.Label(header, text="Объединение · Страницы · Защита · Экспорт",
                 fg=TEXT_DIM, bg=SURFACE, font=FONT_SM).pack(side="left", padx=16)
        StyledButton(header, "О программе", self._show_about,
                     color=SURFACE2).pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # status bar first so it always keeps its place at the bottom
        self._status_var = tk.StringVar(value="Готов к работе")
        status = tk.Frame(self, bg=SURFACE, pady=5, padx=16)
        status.pack(fill="x", side="bottom")
        self._status_dot = tk.Label(status, text="●", fg=TEXT_DIM, bg=SURFACE,
                                    font=("Segoe UI", 12))
        self._status_dot.pack(side="left")
        tk.Label(status, textvariable=self._status_var, fg=TEXT_DIM,
                 bg=SURFACE, font=FONT_SM).pack(side="left", padx=6)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=SURFACE, width=215)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

        self._content = tk.Frame(body, bg=BG)
        self._content.pack(side="left", fill="both", expand=True)

        for group, items in self.NAV:
            tk.Label(sidebar, text=group.upper(), fg=TEXT_DIM, bg=SURFACE,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
            for key, label in items:
                item = tk.Label(sidebar, text="  " + label, fg=TEXT, bg=SURFACE,
                                font=FONT_NAV, anchor="w", padx=12, pady=7,
                                cursor="hand2")
                item.pack(fill="x", padx=8, pady=1)
                item.bind("<Button-1>", lambda e, k=key: self._show(k))
                item.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                item.bind("<Leave>", lambda e, k=key: self._hover(k, False))
                self._nav_items[key] = item

        builders = {
            "merge": self._build_merge, "img2pdf": self._build_img2pdf,
            "delete": self._build_delete, "extract": self._build_extract,
            "rotate": self._build_rotate, "order": self._build_order,
            "split": self._build_split, "meta": self._build_meta,
            "secure": self._build_secure, "compress": self._build_compress,
            "stamp": self._build_stamp, "export": self._build_export,
        }
        for key, build in builders.items():
            page = tk.Frame(self._content, bg=BG)
            self._pages[key] = page
            build(page)

    def _page_layout(self, parent, title, subtitle):
        """Заголовок раздела + рабочая область + нижняя панель действий."""
        SectionHeader(parent, title, subtitle).pack(fill="x", padx=20, pady=(16, 10))
        work = tk.Frame(parent, bg=BG)
        work.pack(fill="both", expand=True, padx=20)
        actions = tk.Frame(parent, bg=BG, pady=12)
        actions.pack(fill="x", padx=20, side="bottom")
        return work, actions

    def _hover(self, key, entering):
        if key == self._current:
            return
        self._nav_items[key].config(bg=SURFACE2 if entering else SURFACE)

    def _show(self, key):
        if self._current:
            self._pages[self._current].pack_forget()
            self._nav_items[self._current].config(bg=SURFACE, fg=TEXT,
                                                  font=FONT_NAV)
        self._current = key
        self._pages[key].pack(fill="both", expand=True)
        self._nav_items[key].config(bg=SURFACE2, fg=ACCENT2,
                                    font=("Segoe UI", 10, "bold"))

    def _show_about(self):
        AboutDialog(self)

    def _set_status(self, msg, color=TEXT_DIM):
        self._status_var.set(msg)
        self._status_dot.config(fg=color)
        self.update_idletasks()

    def _busy(self, msg):
        self._set_status(msg, WARNING)
        self.config(cursor="watch")
        self.update_idletasks()

    def _idle(self):
        self.config(cursor="")

    def _fail(self, exc, title="Ошибка", extra=""):
        """Сообщить об ошибке операции; трассировка уходит в журнал."""
        self._idle()
        self._set_status("✖ " + title, DANGER)
        text = str(exc) or type(exc).__name__
        if not isinstance(exc, (ValueError, RuntimeError, OSError)):
            # неожиданное исключение: тип и журнал помогут разобраться
            path = log_exception(type(exc), exc, exc.__traceback__)
            text = f"{type(exc).__name__}: {text}"
            if path:
                text += f"\n\nПодробности записаны в файл:\n{path}"
        messagebox.showerror(title, text + extra)

    def report_callback_exception(self, exc_type, exc, tb):
        """Необработанная ошибка в обработчике Tk.

        По умолчанию Tk печатает её в stderr, которого в портативной
        сборке нет, — пользователь не увидел бы ничего.
        """
        path = log_exception(exc_type, exc, tb)
        self._idle()
        self._set_status("✖ Внутренняя ошибка", DANGER)
        messagebox.showerror(
            "Внутренняя ошибка",
            f"{exc_type.__name__}: {exc}"
            + (f"\n\nПодробности записаны в файл:\n{path}" if path else ""))

    def _done(self, status_msg, info_msg, notes=()):
        """Итог операции; notes — то, что выполнено не так, как просили."""
        self._idle()
        if notes:
            self._set_status("⚠ " + status_msg, WARNING)
            info_msg += "\n\nОбратите внимание:\n" + "\n".join(f"• {n}" for n in notes)
            messagebox.showwarning("Готово с замечаниями", info_msg)
        else:
            self._set_status("✔ " + status_msg, SUCCESS)
            messagebox.showinfo("Готово", info_msg)

    @staticmethod
    def _confirm_unprotected(protection):
        """Предупредить, что копия защищённого файла сохранится без защиты."""
        if protection is None:
            return True
        return messagebox.askyesno(
            "Защита не сохранится",
            f"Исходный файл {protection}. Результат будет сохранён без "
            "защиты: открыть, распечатать и изменить его сможет любой.\n\n"
            "Защиту можно установить заново в разделе «Защита паролем».\n\n"
            "Продолжить?")

    @staticmethod
    def _missing(parent, module, what):
        """Плашка «библиотека не установлена» вместо неработающего раздела."""
        box = tk.Frame(parent, bg=SURFACE2, padx=18, pady=16)
        box.pack(fill="x", pady=10)
        tk.Label(box, text=f"⚠ Раздел «{what}» требует библиотеки {module}",
                 fg=WARNING, bg=SURFACE2, font=FONT_BODY).pack(anchor="w")
        tk.Label(box, text=f"Установите её командой:    pip install {module}",
                 fg=TEXT_DIM, bg=SURFACE2, font=FONT_MONO).pack(anchor="w", pady=(6, 0))

    # ── Drag & drop ─────────────────────────────────────────────────────────
    def _register_drop(self, widget, handler):
        if not self.dnd_enabled:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", handler)
        except Exception:
            pass

    def _dropped_paths(self, event, extensions):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        accepted = [p for p in paths if os.path.splitext(p)[1].lower() in extensions]
        skipped = len(paths) - len(accepted)
        if skipped:
            self._set_status(f"Пропущено файлов неподходящего типа: {skipped}", WARNING)
        return accepted

    # ══ 1. Merge ════════════════════════════════════════════════════════════
    def _build_merge(self, t):
        work, actions = self._page_layout(
            t, "Объединить PDF-файлы",
            "Добавьте файлы, задайте диапазон страниц для каждого (необязательно), "
            "измените порядок" + ("  ·  можно перетащить файлы в окно" if self.dnd_enabled else ""))

        btn_row = tk.Frame(work, bg=BG)
        btn_row.pack(fill="x", pady=(0, 10))
        StyledButton(btn_row, "＋ Добавить файлы", self._merge_add).pack(side="left", padx=(0, 8))
        StyledButton(btn_row, "🗑 Очистить список", self._merge_clear,
                     color=SURFACE2).pack(side="left")

        opts = tk.Frame(work, bg=BG)
        opts.pack(fill="x", pady=(0, 8))
        self._merge_bookmarks = tk.BooleanVar(value=True)
        self._merge_outline = tk.BooleanVar(value=True)
        for text, var in [("Создать закладку на каждый файл", self._merge_bookmarks),
                          ("Сохранять оглавление исходных файлов", self._merge_outline)]:
            tk.Checkbutton(opts, text=text, variable=var, bg=BG, fg=TEXT,
                           selectcolor=BG, activebackground=BG, font=FONT_SM,
                           highlightthickness=0, bd=0).pack(side="left", padx=(0, 18))

        frame = tk.Frame(work, bg=SURFACE, bd=0)
        frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(frame, bg=SURFACE, highlightthickness=0)
        sb = tk.Scrollbar(frame, orient="vertical", command=canvas.yview,
                          bg=SURFACE2, troughcolor=SURFACE,
                          activebackground=ACCENT2, highlightthickness=0,
                          bd=0, relief="flat", width=12)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._merge_inner = tk.Frame(canvas, bg=SURFACE)
        self._merge_win = canvas.create_window((0, 0), window=self._merge_inner, anchor="nw")
        self._merge_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._merge_win, width=e.width))

        self._register_drop(canvas, self._merge_drop)
        self._register_drop(self._merge_inner, self._merge_drop)

        self._merge_summary_var = tk.StringVar(value="")
        tk.Label(actions, textvariable=self._merge_summary_var,
                 fg=TEXT_DIM, bg=BG, font=FONT_SM).pack(side="left")
        StyledButton(actions, "💾 Сохранить объединённый PDF",
                     self._merge_run).pack(side="right")
        self._merge_refresh()

    def _merge_refresh(self):
        for w in self._merge_inner.winfo_children():
            w.destroy()
        if not self._merge_entries:
            tk.Label(self._merge_inner,
                     text="Список пуст — нажмите «Добавить файлы»"
                          + ("\nили перетащите PDF в это окно" if self.dnd_enabled else ""),
                     fg=TEXT_DIM, bg=SURFACE, font=FONT_SM).pack(pady=40)
            self._merge_summary_var.set("")
            return
        for i, entry in enumerate(self._merge_entries):
            card = FileCard(self._merge_inner, path=entry["path"], index=i,
                            remove_cb=self._merge_remove, move_cb=self._merge_move,
                            range_var=entry["range_var"], total=entry["total"],
                            pick_cb=self._merge_pick)
            card.pack(fill="x", pady=3, padx=4)
            tk.Frame(self._merge_inner, bg=BORDER, height=1).pack(fill="x", padx=8)
        n = len(self._merge_entries)
        self._merge_summary_var.set(f"{n} файл(ов) в очереди")

    def _merge_pick(self, path, range_var):
        """Мини-обёртка: собрать временный SourceFile под выбранный файл."""
        try:
            reader, pwd = open_pdf(path, self)
        except Cancelled:
            return
        except Exception as e:
            messagebox.showerror("Не удалось открыть файл", str(e))
            return
        stub = type("Stub", (), {})()
        stub.path, stub.password, stub.total = path, pwd, len(reader.pages)
        stub.require = lambda: True
        picked = ThumbnailPicker(self, stub, range_var.get()).show()
        if picked is not None:
            range_var.set(picked)

    def _merge_add(self, paths=None):
        """Добавить файлы в очередь; вернуть число действительно добавленных."""
        files = paths or filedialog.askopenfilenames(
            title="Выберите PDF-файлы", filetypes=[("PDF", "*.pdf")])
        existing = {e["path"] for e in self._merge_entries}
        added = 0
        for f in files:
            if f not in existing:
                existing.add(f)
                self._merge_entries.append({"path": f, "range_var": tk.StringVar(),
                                            "total": page_count(f)})
                added += 1
        self._merge_refresh()
        return added

    def _merge_drop(self, event):
        files = self._dropped_paths(event, {".pdf"})
        if files:
            added = self._merge_add(files)
            dups = len(files) - added
            self._set_status(f"Добавлено файлов: {added}"
                             + (f", уже были в очереди: {dups}" if dups else ""), SUCCESS)

    def _merge_remove(self, idx):
        self._merge_entries.pop(idx)
        self._merge_refresh()

    def _merge_move(self, idx, direction):
        new = idx + direction
        if 0 <= new < len(self._merge_entries):
            self._merge_entries[idx], self._merge_entries[new] = \
                self._merge_entries[new], self._merge_entries[idx]
            self._merge_refresh()

    def _merge_clear(self):
        self._merge_entries.clear()
        self._merge_refresh()

    def _merge_run(self):
        if len(self._merge_entries) < 2:
            messagebox.showwarning("Нет файлов", "Добавьте минимум 2 PDF-файла.")
            return

        # Pre-validate all ranges and unlock encrypted files up front
        problems, prepared, protected = [], [], []
        for i, entry in enumerate(self._merge_entries):
            try:
                reader, pwd = open_pdf(entry["path"], self)
            except Cancelled:
                return
            except Exception as e:
                problems.append(f"Файл {i + 1} ({short_name(entry['path'])}): {e}")
                continue
            if pwd is not None:
                protected.append(short_name(entry["path"]))
            total = len(reader.pages)
            rng = entry["range_var"].get().strip()
            indices = None
            if rng:
                try:
                    indices = parse_page_range(rng, total)
                except Exception as e:
                    problems.append(f"Файл {i + 1} ({short_name(entry['path'])}): {e}")
                    continue
            prepared.append((entry["path"], reader, indices, total))
        if problems:
            messagebox.showerror("Ошибка диапазона", "\n".join(problems))
            return
        if protected and not self._confirm_unprotected(
                "защищён (" + ", ".join(protected) + ")"):
            return

        out = ask_save_pdf("Сохранить объединённый PDF")
        if not out:
            return
        for path, *_ in prepared:
            if not check_not_same(path, out):
                return

        try:
            self._busy("Объединение…")
            keep_outline = self._merge_outline.get()
            make_bookmarks = self._merge_bookmarks.get()
            notes = []
            writer = None
            if keep_outline or make_bookmarks:
                try:
                    writer = self._merge_build(prepared, keep_outline, make_bookmarks)
                except Exception as e:
                    # собираем заново с нуля — без частично добавленных страниц
                    notes.append(f"закладки не перенесены: {e}")
            if writer is None:
                writer = self._merge_build_plain(prepared, make_bookmarks, notes)
            total_added = len(writer.pages)
            write_pdf(writer, out)
            self._done(f"Объединено {total_added} стр. из {len(prepared)} файлов → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nДобавлено страниц: {total_added}", notes)
        except Exception as e:
            self._fail(e, "Ошибка при объединении")

    @staticmethod
    def _merge_build(prepared, keep_outline, make_bookmarks):
        """append() переносит закладки исходников и умеет создавать
        собственный узел оглавления для каждого файла."""
        writer = PdfWriter()
        for path, reader, indices, _ in prepared:
            title = os.path.splitext(os.path.basename(path))[0]
            writer.append(reader,
                          outline_item=title if make_bookmarks else None,
                          pages=indices,
                          import_outline=keep_outline)
        return writer

    @staticmethod
    def _merge_build_plain(prepared, make_bookmarks, notes):
        """Постраничная сборка — запасной путь для повреждённых оглавлений."""
        writer = PdfWriter()
        for path, reader, indices, total in prepared:
            title = os.path.splitext(os.path.basename(path))[0]
            pages = indices if indices is not None else list(range(total))
            if indices is not None:
                prune_links(reader, pages)
            start = len(writer.pages)
            for idx in pages:
                writer.add_page(reader.pages[idx])
            if make_bookmarks:
                try:
                    writer.add_outline_item(title, start)
                except Exception as e:
                    notes.append(f"закладка «{title}» не создана: {e}")
        return writer

    # ══ 2. Images → PDF ═════════════════════════════════════════════════════
    def _build_img2pdf(self, t):
        work, actions = self._page_layout(
            t, "Изображения → PDF",
            "Соберите PDF из файлов JPG, PNG, BMP, TIFF"
            + ("  ·  можно перетащить файлы в окно" if self.dnd_enabled else ""))
        if not HAS_PIL:
            self._missing(work, "Pillow", "Изображения → PDF")
            return

        btn_row = tk.Frame(work, bg=BG)
        btn_row.pack(fill="x", pady=(0, 10))
        StyledButton(btn_row, "＋ Добавить изображения", self._img_add).pack(side="left", padx=(0, 8))
        StyledButton(btn_row, "🗑 Очистить", self._img_clear, color=SURFACE2).pack(side="left")

        mode_row = tk.Frame(work, bg=BG)
        mode_row.pack(fill="x", pady=(0, 8))
        tk.Label(mode_row, text="Размер страницы:", fg=TEXT_DIM, bg=BG,
                 font=FONT_SM).pack(side="left", padx=(0, 8))
        self._img_mode = tk.StringVar(value="fit")
        for value, text in [("fit", "по размеру изображения"), ("a4", "A4 с полями")]:
            tk.Radiobutton(mode_row, text=text, value=value, variable=self._img_mode,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=FONT_SM, highlightthickness=0,
                           bd=0).pack(side="left", padx=(0, 14))

        frame = tk.Frame(work, bg=SURFACE)
        frame.pack(fill="both", expand=True)
        self._img_list = tk.Listbox(frame, bg=SURFACE, fg=TEXT, font=FONT_BODY,
                                    relief="flat", highlightthickness=0,
                                    selectbackground=SURFACE2, selectforeground=TEXT,
                                    activestyle="none")
        self._img_list.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        side = tk.Frame(frame, bg=SURFACE, padx=8, pady=8)
        side.pack(side="right", fill="y")
        for text, cb in [("↑ Выше", lambda: self._img_move(-1)),
                         ("↓ Ниже", lambda: self._img_move(1)),
                         ("✕ Убрать", self._img_remove),
                         ("A→Я Сортировать", self._img_sort)]:
            StyledButton(side, text, cb, color=SURFACE2).pack(fill="x", pady=3)
        self._register_drop(self._img_list, self._img_drop)

        self._img_summary = tk.StringVar(value="")
        tk.Label(actions, textvariable=self._img_summary, fg=TEXT_DIM, bg=BG,
                 font=FONT_SM).pack(side="left")
        StyledButton(actions, "💾 Создать PDF", self._img_run).pack(side="right")

    def _img_refresh(self):
        self._img_list.delete(0, "end")
        for i, p in enumerate(self._image_paths):
            self._img_list.insert("end", f"  {i + 1}.  {short_name(p, 60)}")
        self._img_summary.set(f"Изображений: {len(self._image_paths)}"
                              if self._image_paths else "")

    def _img_add(self, paths=None):
        files = paths or filedialog.askopenfilenames(
            title="Выберите изображения",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.gif *.webp")])
        for f in files:
            if f not in self._image_paths:
                self._image_paths.append(f)
        self._img_refresh()

    def _img_drop(self, event):
        files = self._dropped_paths(
            event, {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp"})
        if files:
            self._img_add(files)

    def _img_selected(self):
        sel = self._img_list.curselection()
        return sel[0] if sel else None

    def _img_move(self, direction):
        i = self._img_selected()
        if i is None:
            return
        j = i + direction
        if 0 <= j < len(self._image_paths):
            self._image_paths[i], self._image_paths[j] = self._image_paths[j], self._image_paths[i]
            self._img_refresh()
            self._img_list.selection_set(j)

    def _img_remove(self):
        i = self._img_selected()
        if i is not None:
            self._image_paths.pop(i)
            self._img_refresh()

    def _img_sort(self):
        self._image_paths.sort(key=lambda p: os.path.basename(p).lower())
        self._img_refresh()

    def _img_clear(self):
        self._image_paths.clear()
        self._img_refresh()

    def _img_run(self):
        if not self._image_paths:
            messagebox.showwarning("Пусто", "Добавьте хотя бы одно изображение.")
            return
        out = ask_save_pdf("Сохранить PDF")
        if not out:
            return
        for p in self._image_paths:
            if not check_not_same(p, out):
                return
        try:
            self._busy("Сборка PDF из изображений…")
            pages, notes = [], []
            for p in self._image_paths:
                try:
                    frames, skipped = self._img_load(p)
                except Exception as e:
                    raise ValueError(f"{short_name(p)}: {e}") from e
                if skipped:
                    notes.append(f"{short_name(p)}: взят только первый кадр из {skipped + 1}")
                pages.extend(frames)
            with atomic_open(out) as f:
                pages[0].save(f, "PDF", resolution=150.0, save_all=True,
                              append_images=pages[1:], quality=JPEG_QUALITY)
            self._done(f"Создан PDF из {len(pages)} изображений → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nСтраниц: {len(pages)}", notes)
        except Exception as e:
            self._fail(e, "Ошибка при создании PDF")

    def _img_load(self, path):
        """Кадры изображения в виде страниц RGB и число пропущенных кадров.

        Многостраничный TIFF (обычный результат сканирования) даёт все
        страницы, у анимаций берётся первый кадр. Ориентация из EXIF
        применяется — иначе снимки с телефона ложатся боком.
        """
        a4 = (1240, 1754)          # A4 при 150 dpi
        margin = 60
        frames = []
        with Image.open(path) as src:
            n_frames = getattr(src, "n_frames", 1)
            used = n_frames if src.format == "TIFF" else 1
            # MPO (снимки многих телефонов) хранит второй кадр-превью —
            # о нём предупреждать незачем
            skipped = n_frames - used if src.format in ("GIF", "WEBP", "PNG") else 0
            for k in range(used):
                src.seek(k)
                img = ImageOps.exif_transpose(src)
                if img.mode.startswith("I;16") or img.mode in ("I", "F"):
                    # 16/32-битные сканы: convert("RGB") обрезал бы их до белого
                    img = img.convert("I").point(lambda v: v / 256).convert("L")
                if img.mode in ("RGBA", "LA", "P", "PA"):
                    bg = Image.new("RGB", img.size, "white")
                    img = img.convert("RGBA")
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                else:
                    img = img.convert("RGB")
                if self._img_mode.get() == "a4":
                    canvas_img = Image.new("RGB", a4, "white")
                    box = (a4[0] - 2 * margin, a4[1] - 2 * margin)
                    img.thumbnail(box, Image.LANCZOS)
                    canvas_img.paste(img, ((a4[0] - img.width) // 2,
                                           (a4[1] - img.height) // 2))
                    img = canvas_img
                frames.append(img)
        return frames, skipped

    # ══ 3. Delete pages ═════════════════════════════════════════════════════
    def _build_delete(self, t):
        work, actions = self._page_layout(
            t, "Удалить страницы",
            "Укажите страницы для удаления (например: 2, 4-6, 10)")
        self._del_src = SourceFile(work, self, on_load=lambda r: self._del_range.update_preview())
        self._del_src.pack(fill="x", pady=4)

        def describe(pages, total):
            return f"Будет удалено {len(pages)} стр., останется {total - len(pages)} стр."

        self._del_range = RangeField(
            work, self, self._del_src, "Страницы для удаления:",
            "Примеры: 1   •   3,5,7   •   2-5   •   1,3-6,10",
            accent=WARNING, describe=describe)
        self._del_range.pack(fill="x", pady=(10, 2))

        StyledButton(actions, "💾 Сохранить результат", self._del_run).pack(side="right")

    def _del_run(self):
        src = self._del_src
        if not src.require():
            return
        rng = self._del_range.var.get().strip()
        if not rng:
            messagebox.showwarning("Пусто", "Введите номера страниц для удаления.")
            return
        try:
            to_del = set(self._del_range.indices())
        except ValueError as e:
            messagebox.showerror("Ошибка диапазона", str(e))
            return
        if len(to_del) >= src.total:
            messagebox.showwarning("Нельзя", "Нельзя удалить все страницы документа.")
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Удаление страниц…")
            reader = src.reader()
            keep = [i for i in range(src.total) if i not in to_del]
            writer, notes = select_pages(reader, keep)
            write_pdf(writer, out)
            self._done(f"Удалено {len(to_del)} стр. → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nОсталось страниц: {len(keep)}", notes)
        except Exception as e:
            self._fail(e)

    # ══ 4. Extract range ════════════════════════════════════════════════════
    def _build_extract(self, t):
        work, actions = self._page_layout(
            t, "Извлечь диапазон страниц",
            "Выберите страницы для сохранения в новый PDF")
        self._spl_src = SourceFile(work, self, on_load=lambda r: self._spl_range.update_preview())
        self._spl_src.pack(fill="x", pady=4)
        self._spl_range = RangeField(
            work, self, self._spl_src, "Страницы для извлечения:",
            "Примеры: 1-5   •   2,4,6   •   1,3-7,12", accent=SUCCESS,
            describe=lambda pages, total: f"Будет извлечено {len(pages)} стр.")
        self._spl_range.pack(fill="x", pady=(10, 2))
        StyledButton(actions, "💾 Сохранить результат", self._spl_run).pack(side="right")

    def _spl_run(self):
        src = self._spl_src
        if not src.require():
            return
        if not self._spl_range.var.get().strip():
            messagebox.showwarning("Пусто", "Введите номера страниц для извлечения.")
            return
        try:
            to_keep = self._spl_range.indices()
        except ValueError as e:
            messagebox.showerror("Ошибка диапазона", str(e))
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Извлечение страниц…")
            reader = src.reader()
            writer, notes = select_pages(reader, to_keep)
            write_pdf(writer, out)
            self._done(f"Извлечено {len(to_keep)} стр. → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nСтраниц: {len(to_keep)}", notes)
        except Exception as e:
            self._fail(e)

    # ══ 5. Rotate ═══════════════════════════════════════════════════════════
    def _build_rotate(self, t):
        work, actions = self._page_layout(
            t, "Повернуть страницы",
            "Поворот сканов и страниц альбомной ориентации")
        self._rot_src = SourceFile(work, self, on_load=lambda r: self._rot_range.update_preview())
        self._rot_src.pack(fill="x", pady=4)
        self._rot_range = RangeField(
            work, self, self._rot_src, "Страницы для поворота:",
            "Оставьте поле пустым, чтобы повернуть весь документ",
            describe=lambda pages, total: f"Будет повёрнуто {len(pages)} стр. из {total}")
        self._rot_range.pack(fill="x", pady=(10, 2))

        angle_row = tk.Frame(work, bg=BG)
        angle_row.pack(fill="x", pady=(10, 0))
        tk.Label(angle_row, text="Направление:", fg=TEXT, bg=BG,
                 font=FONT_BODY).pack(side="left", padx=(0, 12))
        self._rot_angle = tk.IntVar(value=90)
        for value, text in [(90, "↻ 90° по часовой"), (270, "↺ 90° против часовой"),
                            (180, "⇅ 180°")]:
            tk.Radiobutton(angle_row, text=text, value=value, variable=self._rot_angle,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=FONT_BODY, highlightthickness=0,
                           bd=0).pack(side="left", padx=(0, 16))

        StyledButton(actions, "💾 Сохранить результат", self._rot_run).pack(side="right")

    def _rot_run(self):
        src = self._rot_src
        if not src.require():
            return
        rng = self._rot_range.var.get().strip()
        try:
            targets = set(self._rot_range.indices()) if rng else set(range(src.total))
        except ValueError as e:
            messagebox.showerror("Ошибка диапазона", str(e))
            return
        if not targets:
            messagebox.showwarning("Пусто", "Не выбрано ни одной страницы.")
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Поворот страниц…")
            angle = self._rot_angle.get()
            writer, warning = clone_document(src.reader())
            for i, page in enumerate(writer.pages):
                if i in targets:
                    page.rotate(angle)
            write_pdf(writer, out)
            self._done(f"Повёрнуто {len(targets)} стр. на {angle}° → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nПовёрнуто страниц: {len(targets)}",
                       [warning] if warning else [])
        except Exception as e:
            self._fail(e)

    # ══ 6. Reorder ══════════════════════════════════════════════════════════
    def _build_order(self, t):
        work, actions = self._page_layout(
            t, "Порядок страниц",
            "Задайте новый порядок страниц внутри одного документа")
        self._ord_src = SourceFile(work, self, on_load=self._ord_loaded)
        self._ord_src.pack(fill="x", pady=4)

        tk.Label(work, text="Новый порядок страниц:", fg=TEXT, bg=BG,
                 font=FONT_BODY).pack(anchor="w", pady=(12, 0))
        self._ord_var = tk.StringVar()
        row = tk.Frame(work, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Entry(row, textvariable=self._ord_var, bg=BG, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=FONT_MONO,
                 highlightthickness=1, highlightcolor=ACCENT,
                 highlightbackground=BORDER).pack(side="left", fill="x",
                                                  expand=True, ipady=6)
        for text, cb in [("Сбросить", self._ord_reset),
                         ("Обратный порядок", self._ord_reverse)]:
            StyledButton(row, text, cb, color=SURFACE2).pack(side="left", padx=(8, 0))

        tk.Label(work, text="Порядок соблюдается: «3,1,2» поставит третью страницу первой.\n"
                            "Допустимы диапазоны, в том числе обратные: «10-1» — перевернуть весь документ.",
                 fg=TEXT_DIM, bg=BG, font=FONT_SM, justify="left").pack(anchor="w")
        self._ord_preview = tk.Label(work, text="", fg=ACCENT2, bg=BG, font=FONT_SM,
                                     justify="left")
        self._ord_preview.pack(anchor="w", pady=6)
        self._ord_var.trace_add("write", lambda *_: self._ord_update())

        StyledButton(actions, "💾 Сохранить результат", self._ord_run).pack(side="right")

    def _ord_loaded(self, reader):
        self._ord_reset()

    def _ord_reset(self):
        if self._ord_src.total:
            self._ord_var.set(f"1-{self._ord_src.total}")

    def _ord_reverse(self):
        if self._ord_src.total:
            self._ord_var.set(f"{self._ord_src.total}-1")

    def _ord_update(self):
        total = self._ord_src.total
        text = self._ord_var.get().strip()
        if not total or not text:
            self._ord_preview.config(text="")
            return
        try:
            order = parse_page_order(text, total)
        except Exception as e:
            self._ord_preview.config(text=f"⚠ {e}", fg=DANGER)
            return
        missing = sorted({i + 1 for i in range(total)} - {i + 1 for i in order})
        dups = len(order) - len(set(order))
        parts = [f"В результате будет {len(order)} стр."]
        if missing:
            shown = ", ".join(map(str, missing[:12])) + ("…" if len(missing) > 12 else "")
            parts.append(f"не войдут: {shown}")
        if dups:
            parts.append(f"повторов: {dups}")
        self._ord_preview.config(text="  ·  ".join(parts),
                                 fg=WARNING if (missing or dups) else ACCENT2)

    def _ord_run(self):
        src = self._ord_src
        if not src.require():
            return
        text = self._ord_var.get().strip()
        if not text:
            messagebox.showwarning("Пусто", "Задайте новый порядок страниц.")
            return
        try:
            order = parse_page_order(text, src.total)
        except ValueError as e:
            messagebox.showerror("Ошибка порядка", str(e))
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Перестановка страниц…")
            reader = src.reader()
            writer, notes = select_pages(reader, order)
            write_pdf(writer, out)
            self._done(f"Порядок изменён, {len(order)} стр. → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nСтраниц: {len(order)}", notes)
        except Exception as e:
            self._fail(e)

    # ══ 7. Split ════════════════════════════════════════════════════════════
    def _build_split(self, t):
        work, actions = self._page_layout(
            t, "Разделить файл",
            "Разбиение документа на несколько файлов в выбранной папке")
        self._sp_src = SourceFile(work, self, on_load=self._sp_loaded)
        self._sp_src.pack(fill="x", pady=4)

        tk.Label(work, text="Способ разделения:", fg=TEXT, bg=BG,
                 font=FONT_BODY).pack(anchor="w", pady=(12, 4))
        self._sp_mode = tk.StringVar(value="each")
        for value, text in [("each",  "каждая страница — отдельный файл"),
                            ("every", "по N страниц в файле"),
                            ("marks", "по закладкам верхнего уровня")]:
            tk.Radiobutton(work, text=text, value=value, variable=self._sp_mode,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=FONT_BODY, highlightthickness=0, bd=0,
                           command=self._sp_update).pack(anchor="w")

        n_row = tk.Frame(work, bg=BG)
        n_row.pack(fill="x", pady=(8, 0))
        tk.Label(n_row, text="Страниц в файле (N):", fg=TEXT_DIM, bg=BG,
                 font=FONT_SM).pack(side="left")
        self._sp_n = tk.StringVar(value="10")
        tk.Entry(n_row, textvariable=self._sp_n, width=6, bg=BG, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=FONT_MONO,
                 highlightthickness=1, highlightcolor=ACCENT,
                 highlightbackground=BORDER).pack(side="left", padx=8, ipady=3)
        self._sp_n.trace_add("write", lambda *_: self._sp_update())

        self._sp_preview = tk.Label(work, text="", fg=ACCENT2, bg=BG, font=FONT_SM,
                                    justify="left")
        self._sp_preview.pack(anchor="w", pady=10)

        StyledButton(actions, "📂 Разделить и сохранить", self._sp_run).pack(side="right")

    def _sp_loaded(self, reader):
        self._sp_marks = flatten_outline(reader)
        self._sp_update()

    def _sp_plan(self):
        """Список (имя файла, [индексы страниц]) согласно выбранному режиму."""
        src = self._sp_src
        total = src.total or 0
        stem = os.path.splitext(os.path.basename(src.path or "document"))[0]
        mode = self._sp_mode.get()
        if mode == "each":
            width = len(str(total))
            return [(f"{stem}_стр{str(i + 1).zfill(width)}", [i]) for i in range(total)]
        if mode == "every":
            try:
                n = int(self._sp_n.get())
            except ValueError:
                raise ValueError("N должно быть целым числом") from None
            if n < 1:
                raise ValueError("N должно быть больше нуля")
            plan = []
            for start in range(0, total, n):
                pages = list(range(start, min(start + n, total)))
                plan.append((f"{stem}_{pages[0] + 1}-{pages[-1] + 1}", pages))
            return plan
        marks = [m for m in getattr(self, "_sp_marks", []) if m[2] == 0]
        if not marks:
            raise ValueError("В документе нет закладок верхнего уровня")
        return plan_by_bookmarks(marks, total)

    def _sp_update(self):
        if not self._sp_src.path:
            self._sp_preview.config(text="")
            return
        try:
            plan = self._sp_plan()
        except Exception as e:
            self._sp_preview.config(text=f"⚠ {e}", fg=DANGER)
            return
        sample = ", ".join(name for name, _ in plan[:3])
        more = "…" if len(plan) > 3 else ""
        self._sp_preview.config(
            text=f"Будет создано файлов: {len(plan)}\nНапример: {sample}{more}",
            fg=ACCENT2)

    def _sp_run(self):
        src = self._sp_src
        if not src.require():
            return
        try:
            plan = self._sp_plan()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        if not plan:
            messagebox.showwarning("Пусто", "Нечего сохранять.")
            return
        if not self._confirm_unprotected(src.protection):
            return
        folder = filedialog.askdirectory(title="Папка для сохранения частей")
        if not folder:
            return
        written = 0
        try:
            self._busy(f"Разделение на {len(plan)} файлов…")
            reader = src.reader()
            notes = []
            for name, pages in plan:
                writer, part_notes = select_pages(reader, pages)
                notes.extend(n for n in part_notes if n not in notes)
                write_pdf(writer, unique_path(os.path.join(folder, name + ".pdf")))
                written += 1
                self._set_status(f"Сохранено {written} из {len(plan)}…", WARNING)
            self._done(f"Создано файлов: {written} → {short_name(folder)}",
                       f"Файлы сохранены в папку:\n{folder}\n\nСоздано файлов: {written}",
                       notes)
        except Exception as e:
            self._fail(e, "Ошибка при разделении",
                       f"\n\nСоздано файлов: {written} из {len(plan)}. "
                       "Недописанный файл удалён.")

    # ══ 8. Metadata ═════════════════════════════════════════════════════════
    META_FIELDS = [("/Title", "Заголовок"), ("/Author", "Автор"),
                   ("/Subject", "Тема"), ("/Keywords", "Ключевые слова"),
                   ("/Creator", "Приложение"), ("/Producer", "Производитель")]

    def _build_meta(self, t):
        work, actions = self._page_layout(
            t, "Метаданные документа",
            "Просмотр и правка свойств PDF; можно полностью очистить метаданные")
        self._meta_src = SourceFile(work, self, on_load=self._meta_loaded)
        self._meta_src.pack(fill="x", pady=4)

        grid = tk.Frame(work, bg=BG)
        grid.pack(fill="x", pady=(14, 0))
        grid.columnconfigure(1, weight=1)
        self._meta_vars = {}
        for r, (key, label) in enumerate(self.META_FIELDS):
            tk.Label(grid, text=label + ":", fg=TEXT_DIM, bg=BG, font=FONT_SM,
                     anchor="w", width=18).grid(row=r, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            self._meta_vars[key] = var
            tk.Entry(grid, textvariable=var, bg=BG, fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=FONT_BODY, highlightthickness=1,
                     highlightcolor=ACCENT, highlightbackground=BORDER
                     ).grid(row=r, column=1, sticky="we", pady=4, ipady=4)

        self._meta_extra = tk.Label(work, text="", fg=TEXT_DIM, bg=BG, font=FONT_SM,
                                    justify="left")
        self._meta_extra.pack(anchor="w", pady=12)

        StyledButton(actions, "💾 Сохранить с метаданными",
                     self._meta_run).pack(side="right")
        StyledButton(actions, "🧹 Сохранить без метаданных",
                     lambda: self._meta_run(clear=True),
                     color=SURFACE2).pack(side="right", padx=8)

    def _meta_loaded(self, reader):
        info = reader.metadata or {}
        for key, _ in self.META_FIELDS:
            value = ""
            try:
                value = str(info.get(key) or "")
            except Exception:
                value = ""
            self._meta_vars[key].set(value)
        lines = [f"Страниц: {len(reader.pages)}"]
        try:
            first = reader.pages[0]
            w = float(first.mediabox.width) / 72 * 25.4
            h = float(first.mediabox.height) / 72 * 25.4
            lines.append(f"Размер первой страницы: {w:.0f} × {h:.0f} мм")
        except Exception:
            pass
        raw_dates = []
        for key in ("/CreationDate", "/ModDate"):
            try:
                if info.get(key):
                    raw_dates.append(f"{key.strip('/')}: {info.get(key)}")
            except Exception:
                pass
        lines.extend(raw_dates)
        lines.append("Защита паролем: " + ("да" if self._meta_src.password is not None else "нет"))
        self._meta_extra.config(text="\n".join(lines))

    def _meta_run(self, clear=False):
        src = self._meta_src
        if not src.require():
            return
        if clear and not messagebox.askyesno(
                "Очистить метаданные",
                "Из копии документа будут удалены свойства документа "
                "(автор, заголовок, даты создания и т. д.) и метаданные XMP.\n\n"
                "Сведения внутри страниц и встроенных изображений (например, "
                "EXIF фотографий) сохранятся.\n\nПродолжить?"):
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Запись метаданных…")
            writer, warning = clone_document(src.reader())
            if clear:
                strip_metadata(writer)
            else:
                # поля формы заменяют свои ключи; прочие свойства (даты и т. п.)
                # остаются, очищенное поле удаляет ключ
                info = dict(writer.metadata or {})
                for key, var in self._meta_vars.items():
                    value = var.get().strip()
                    if value:
                        info[key] = value
                    else:
                        info.pop(key, None)
                writer.metadata = info
            write_pdf(writer, out)
            self._done("Метаданные " + ("очищены" if clear else "сохранены"),
                       f"Файл сохранён:\n{out}", [warning] if warning else [])
        except Exception as e:
            self._fail(e)

    # ══ 9. Password ═════════════════════════════════════════════════════════
    def _build_secure(self, t):
        work, actions = self._page_layout(
            t, "Защита паролем",
            "Установка пароля на открытие документа или снятие существующей защиты")
        self._sec_src = SourceFile(work, self, on_load=self._sec_loaded)
        self._sec_src.pack(fill="x", pady=4)

        self._sec_mode = tk.StringVar(value="set")
        mode_row = tk.Frame(work, bg=BG)
        mode_row.pack(fill="x", pady=(14, 6))
        for value, text in [("set", "Установить пароль"), ("remove", "Снять защиту")]:
            tk.Radiobutton(mode_row, text=text, value=value, variable=self._sec_mode,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=FONT_BODY, highlightthickness=0, bd=0,
                           command=self._sec_update).pack(side="left", padx=(0, 20))

        self._sec_fields = tk.Frame(work, bg=BG)
        self._sec_fields.pack(fill="x")
        self._sec_user = tk.StringVar()
        self._sec_owner = tk.StringVar()
        self._sec_repeat = tk.StringVar()
        for label, var, hint in [
                ("Пароль на открытие:", self._sec_user, "запрашивается при открытии файла"),
                ("Повторите пароль:", self._sec_repeat, ""),
                ("Пароль владельца:", self._sec_owner,
                 "необязательно; запрещает правку и копирование")]:
            row = tk.Frame(self._sec_fields, bg=BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, fg=TEXT_DIM, bg=BG, font=FONT_SM,
                     width=22, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var, show="•", bg=BG, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=FONT_BODY, width=28,
                     highlightthickness=1, highlightcolor=ACCENT,
                     highlightbackground=BORDER).pack(side="left", ipady=4)
            if hint:
                tk.Label(row, text=hint, fg=TEXT_DIM, bg=BG,
                         font=FONT_SM).pack(side="left", padx=10)

        self._sec_note = tk.Label(work, text="", fg=TEXT_DIM, bg=BG, font=FONT_SM,
                                  justify="left")
        self._sec_note.pack(anchor="w", pady=12)

        StyledButton(actions, "💾 Сохранить результат", self._sec_run).pack(side="right")
        self._sec_update()

    # С паролем владельца разрешены только печать, заполнение форм и
    # извлечение текста для экранных дикторов; без него — всё.
    # Зарезервированные биты спецификация требует оставлять единицами,
    # поэтому ограничения вычитаются из полного набора.
    ALL_PERMISSIONS = UserAccessPermissions.all()
    RESTRICTED = ALL_PERMISSIONS & ~(UserAccessPermissions.MODIFY
                                     | UserAccessPermissions.EXTRACT
                                     | UserAccessPermissions.ADD_OR_MODIFY
                                     | UserAccessPermissions.ASSEMBLE_DOC)

    @staticmethod
    def _encryption_algorithm():
        """AES доступен только вместе с пакетом cryptography."""
        return "AES-256" if HAS_CRYPTO else "RC4-128"

    def _sec_loaded(self, reader):
        if reader.is_encrypted or self._sec_src.password is not None:
            self._sec_mode.set("remove")
        self._sec_update()

    def _sec_update(self):
        removing = self._sec_mode.get() == "remove"
        if removing:
            self._sec_fields.pack_forget()
            self._sec_note.config(
                text="Пароль исходного файла запрашивается при его открытии.\n"
                     "В сохранённой копии защита будет снята.")
        else:
            self._sec_fields.pack(fill="x")
            note = ("Шифрование AES-256.\nЗабытый пароль восстановить невозможно.\n"
                    "Запрет правки и копирования по паролю владельца соблюдают "
                    "программы просмотра;\nот целенаправленного взлома он не защищает."
                    if HAS_CRYPTO else
                    "Шифрование RC4-128 (устаревшее).\n"
                    "Для стойкого AES-256 установите пакет cryptography:\n"
                    "    pip install cryptography")
            self._sec_note.config(text=note, fg=TEXT_DIM if HAS_CRYPTO else WARNING)

    def _sec_run(self):
        src = self._sec_src
        if not src.require():
            return
        removing = self._sec_mode.get() == "remove"
        if removing and src.password is None:
            messagebox.showinfo("Нет защиты", "Этот файл не защищён паролем.")
            return
        if not removing:
            pwd = self._sec_user.get()
            if not pwd:
                messagebox.showwarning("Пусто", "Введите пароль на открытие.")
                return
            if pwd != self._sec_repeat.get():
                messagebox.showerror("Пароли не совпадают",
                                     "Введённые пароли отличаются.")
                return
            if self._sec_owner.get() == pwd:
                messagebox.showerror(
                    "Одинаковые пароли",
                    "Пароль владельца должен отличаться от пароля на открытие: "
                    "иначе любой, кто открыл файл, снимет ограничения.\n\n"
                    "Оставьте поле пустым, если ограничения не нужны.")
                return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Снятие защиты…" if removing else "Шифрование…")
            writer, warning = clone_document(src.reader())
            if not removing:
                owner = self._sec_owner.get()
                writer.encrypt(user_password=self._sec_user.get(),
                               owner_password=owner or None,
                               algorithm=self._encryption_algorithm(),
                               permissions_flag=(self.RESTRICTED if owner
                                                 else self.ALL_PERMISSIONS))
            write_pdf(writer, out)
            if removing:
                details = "Пароль больше не требуется."
            else:
                details = (f"Алгоритм: {self._encryption_algorithm()}.\n"
                           + ("Правка и копирование запрещены паролем владельца.\n"
                              if self._sec_owner.get() else "")
                           + "Не теряйте пароль — восстановить его нельзя.")
            self._done("Защита снята" if removing else "Документ зашифрован",
                       f"Файл сохранён:\n{out}\n\n{details}",
                       [warning] if warning else [])
        except Exception as e:
            self._fail(e)
        finally:
            # пароли не держим в полях дольше, чем нужно
            self._sec_user.set("")
            self._sec_repeat.set("")
            self._sec_owner.set("")

    # ══ 10. Compress ════════════════════════════════════════════════════════
    def _build_compress(self, t):
        work, actions = self._page_layout(
            t, "Сжатие документа",
            "Сжатие потоков содержимого и удаление дублирующихся объектов")
        self._cmp_src = SourceFile(work, self, on_load=lambda r: self._cmp_reset())
        self._cmp_src.pack(fill="x", pady=4)

        opts = tk.Frame(work, bg=BG)
        opts.pack(fill="x", pady=(14, 0))
        self._cmp_streams = tk.BooleanVar(value=True)
        self._cmp_dedup = tk.BooleanVar(value=True)
        self._cmp_meta = tk.BooleanVar(value=False)
        for text, var in [("Сжимать потоки содержимого страниц", self._cmp_streams),
                          ("Удалять дублирующиеся объекты", self._cmp_dedup),
                          ("Удалить метаданные", self._cmp_meta)]:
            tk.Checkbutton(opts, text=text, variable=var, bg=BG, fg=TEXT,
                           selectcolor=BG, activebackground=BG, font=FONT_BODY,
                           highlightthickness=0, bd=0).pack(anchor="w", pady=2)

        tk.Label(work, text="Сжатие не уменьшает разрешение изображений — это "
                            "обработка без потери качества.",
                 fg=TEXT_DIM, bg=BG, font=FONT_SM).pack(anchor="w", pady=(10, 0))
        self._cmp_result = tk.Label(work, text="", fg=SUCCESS, bg=BG, font=FONT_BODY,
                                    justify="left")
        self._cmp_result.pack(anchor="w", pady=12)

        StyledButton(actions, "💾 Сжать и сохранить", self._cmp_run).pack(side="right")

    def _cmp_reset(self):
        self._cmp_result.config(text="")

    def _cmp_run(self):
        src = self._cmp_src
        if not src.require():
            return
        if not self._confirm_unprotected(src.protection):
            return
        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            before = os.path.getsize(src.path)
            writer, warning = clone_document(src.reader())
            notes = [warning] if warning else []
            total = len(writer.pages)
            failed = 0
            if self._cmp_streams.get():
                # сжимать можно только страницы, уже принадлежащие PdfWriter
                for i, page in enumerate(writer.pages):
                    try:
                        page.compress_content_streams()
                    except Exception:
                        failed += 1     # нестандартный поток — оставляем как есть
                    if i % 10 == 0:
                        self._busy(f"Сжатие… страница {i + 1} из {total}")
            if failed:
                notes.append(f"не сжаты потоки {failed} стр. из {total} "
                             "(нестандартное содержимое)")
            if self._cmp_meta.get():
                strip_metadata(writer)
            if self._cmp_dedup.get():
                self._busy("Удаление дублирующихся объектов…")
                writer.compress_identical_objects()
            write_pdf(writer, out)
            after = os.path.getsize(out)
            saved = before - after
            percent = (saved / before * 100) if before else 0
            if saved <= 0:
                notes.append("файл не уменьшился: документ уже был сжат")
            self._cmp_result.config(
                text=f"Было: {human_size(before)}    Стало: {human_size(after)}\n"
                     f"Экономия: {human_size(abs(saved))} ({percent:+.1f} %)",
                fg=SUCCESS if saved > 0 else WARNING)
            self._done(f"Сжатие завершено ({percent:+.1f} %)",
                       f"Файл сохранён:\n{out}\n\n"
                       f"Было: {human_size(before)}\nСтало: {human_size(after)}", notes)
        except Exception as e:
            self._fail(e, "Ошибка при сжатии")

    # ══ 11. Numbering & watermark ═══════════════════════════════════════════
    def _build_stamp(self, t):
        work, actions = self._page_layout(
            t, "Нумерация и водяной знак",
            "Наложение колонцифр и текстовой подложки на страницы документа")
        if not HAS_REPORTLAB:
            self._missing(work, "reportlab", "Нумерация и водяной знак")
            return

        self._st_src = SourceFile(work, self)
        self._st_src.pack(fill="x", pady=4)

        nb = ttk.Notebook(work)
        nb.pack(fill="both", expand=True, pady=(14, 0))
        num_tab = tk.Frame(nb, bg=BG, padx=14, pady=14)
        wm_tab = tk.Frame(nb, bg=BG, padx=14, pady=14)
        nb.add(num_tab, text="  Нумерация страниц  ")
        nb.add(wm_tab, text="  Водяной знак  ")
        self._st_nb = nb

        # ── numbering ────────────────────────────────────────────────────────
        self._num_on = tk.BooleanVar(value=True)
        self._num_fmt = tk.StringVar(value="{n}")
        self._num_pos = tk.StringVar(value="bc")
        self._num_start = tk.StringVar(value="1")
        self._num_size = tk.StringVar(value="10")
        self._num_skip = tk.BooleanVar(value=False)

        self._field_row(num_tab, "Формат:", self._num_fmt,
                        "{n} — номер, {total} — всего страниц. Например: «{n} / {total}»")
        pos_row = tk.Frame(num_tab, bg=BG)
        pos_row.pack(fill="x", pady=6)
        tk.Label(pos_row, text="Положение:", fg=TEXT_DIM, bg=BG, font=FONT_SM,
                 width=18, anchor="w").pack(side="left")
        for value, text in [("bl", "снизу слева"), ("bc", "снизу по центру"),
                            ("br", "снизу справа"), ("tr", "сверху справа")]:
            tk.Radiobutton(pos_row, text=text, value=value, variable=self._num_pos,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=FONT_SM, highlightthickness=0,
                           bd=0).pack(side="left", padx=(0, 12))
        self._field_row(num_tab, "Начать с номера:", self._num_start, "", width=8)
        self._field_row(num_tab, "Размер шрифта:", self._num_size, "пунктов", width=8)
        tk.Checkbutton(num_tab, text="Не нумеровать первую страницу (титульную)",
                       variable=self._num_skip, bg=BG, fg=TEXT, selectcolor=BG,
                       activebackground=BG, font=FONT_SM, highlightthickness=0,
                       bd=0).pack(anchor="w", pady=6)

        # ── watermark ────────────────────────────────────────────────────────
        self._wm_text = tk.StringVar(value="КОПИЯ")
        self._wm_size = tk.StringVar(value="54")
        self._wm_alpha = tk.StringVar(value="0.12")
        self._wm_angle = tk.StringVar(value="45")
        self._wm_under = tk.BooleanVar(value=False)

        self._field_row(wm_tab, "Текст:", self._wm_text, "")
        self._field_row(wm_tab, "Размер шрифта:", self._wm_size, "пунктов", width=8)
        self._field_row(wm_tab, "Прозрачность:", self._wm_alpha,
                        "от 0.05 (почти незаметно) до 1.0 (сплошной цвет)", width=8)
        self._field_row(wm_tab, "Наклон, градусов:", self._wm_angle, "", width=8)
        tk.Checkbutton(wm_tab, text="Размещать под содержимым страницы",
                       variable=self._wm_under, bg=BG, fg=TEXT, selectcolor=BG,
                       activebackground=BG, font=FONT_SM, highlightthickness=0,
                       bd=0).pack(anchor="w", pady=6)

        StyledButton(actions, "💾 Применить и сохранить", self._st_run).pack(side="right")

    def _field_row(self, parent, label, var, hint, width=None):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label, fg=TEXT_DIM, bg=BG, font=FONT_SM,
                 width=18, anchor="w").pack(side="left")
        entry = tk.Entry(row, textvariable=var, bg=BG, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=FONT_BODY, highlightthickness=1,
                         highlightcolor=ACCENT, highlightbackground=BORDER,
                         **({"width": width} if width else {}))
        entry.pack(side="left", fill=None if width else "x",
                   expand=not width, ipady=4)
        if hint:
            tk.Label(row, text=hint, fg=TEXT_DIM, bg=BG,
                     font=FONT_SM).pack(side="left", padx=10)

    def _overlay_page(self, size, draw):
        """PDF-страница-подложка нужного размера, нарисованная reportlab."""
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=size)
        draw(c, size[0], size[1])
        c.save()
        buf.seek(0)
        return PdfReader(buf).pages[0]

    def _st_run(self):
        src = self._st_src
        if not src.require():
            return
        numbering = self._st_nb.index(self._st_nb.select()) == 0
        font = cyrillic_font()
        text_sample = self._num_fmt.get() if numbering else self._wm_text.get()
        if font == "Helvetica" and any(ord(ch) > 127 for ch in text_sample):
            if not messagebox.askyesno(
                    "Нет шрифта с кириллицей",
                    "Не найден TTF-шрифт, поддерживающий кириллицу.\n"
                    "Русские буквы будут заменены пустыми квадратами.\n\n"
                    "Продолжить всё равно?"):
                return
        try:
            if numbering:
                start = int(self._num_start.get())
                size = float(self._num_size.get())
            else:
                size = float(self._wm_size.get())
                alpha = float(self._wm_alpha.get())
                angle = float(self._wm_angle.get())
                if not self._wm_text.get().strip():
                    messagebox.showwarning("Пусто", "Введите текст водяного знака.")
                    return
        except ValueError:
            messagebox.showerror("Ошибка", "Числовые поля заполнены неверно.")
            return
        fmt = self._num_fmt.get()
        if numbering:
            try:
                fmt.format(n=1, total=1, page=1)
            except (KeyError, IndexError, ValueError, AttributeError) as e:
                messagebox.showerror(
                    "Неверный формат",
                    f"Шаблон «{fmt}» содержит ошибку ({e}).\n\n"
                    "Допустимы подстановки {n} и {total}, например «{n} / {total}».")
                return
        if not self._confirm_unprotected(src.protection):
            return

        out = ask_save_pdf()
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Наложение…")
            writer, warning = clone_document(src.reader())
            total = len(writer.pages)
            stamped = 0
            over = True if numbering else not self._wm_under.get()
            for i, page in enumerate(writer.pages):
                if numbering and self._num_skip.get() and i == 0:
                    continue
                if numbering:
                    label = fmt.format(n=start + i, total=total, page=start + i)

                    def draw(c, pw, ph, label=label, size=size):
                        c.setFont(font, size)
                        c.setFillColorRGB(0, 0, 0)
                        pos = self._num_pos.get()
                        margin = 28
                        if pos == "bl":
                            c.drawString(margin, margin, label)
                        elif pos == "br":
                            c.drawRightString(pw - margin, margin, label)
                        elif pos == "tr":
                            c.drawRightString(pw - margin, ph - margin, label)
                        else:
                            c.drawCentredString(pw / 2, margin, label)
                else:
                    def draw(c, pw, ph, size=size, alpha=alpha, angle=angle):
                        c.saveState()
                        c.setFillAlpha(max(0.02, min(alpha, 1.0)))
                        c.setFont(font, size)
                        c.setFillColorRGB(0.1, 0.1, 0.1)
                        c.translate(pw / 2, ph / 2)
                        c.rotate(angle)
                        c.drawCentredString(0, 0, self._wm_text.get())
                        c.restoreState()

                visible, ctm = visible_frame(page)
                page.merge_transformed_page(self._overlay_page(visible, draw),
                                            ctm, over=over)
                stamped += 1
                if i % 10 == 0:
                    self._set_status(f"Наложение… {i + 1} из {total}", WARNING)
            write_pdf(writer, out)
            what = "Нумерация" if numbering else "Водяной знак"
            self._done(f"{what}: обработано {stamped} стр. → {short_name(out)}",
                       f"Файл сохранён:\n{out}\n\nОбработано страниц: {stamped}",
                       [warning] if warning else [])
        except Exception as e:
            self._fail(e, "Ошибка при наложении")

    # ══ 12. Export text & images ════════════════════════════════════════════
    def _build_export(self, t):
        work, actions = self._page_layout(
            t, "Извлечение текста и изображений",
            "Сохранение текстового слоя в .txt и выгрузка встроенных растровых изображений")
        self._ex_src = SourceFile(work, self, on_load=lambda r: self._ex_range.update_preview())
        self._ex_src.pack(fill="x", pady=4)

        self._ex_range = RangeField(
            work, self, self._ex_src, "Страницы:",
            "Оставьте поле пустым, чтобы обработать весь документ",
            describe=lambda pages, total: f"Будет обработано {len(pages)} стр. из {total}")
        self._ex_range.pack(fill="x", pady=(10, 2))

        opts = tk.Frame(work, bg=BG)
        opts.pack(fill="x", pady=(12, 0))
        self._ex_pagebreaks = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="Разделять страницы заголовками в текстовом файле",
                       variable=self._ex_pagebreaks, bg=BG, fg=TEXT, selectcolor=BG,
                       activebackground=BG, font=FONT_SM, highlightthickness=0,
                       bd=0).pack(anchor="w")

        tk.Label(work, text="Текст извлекается только из документов с текстовым слоем.\n"
                            "Для отсканированных страниц потребуется распознавание (OCR).",
                 fg=TEXT_DIM, bg=BG, font=FONT_SM, justify="left").pack(anchor="w", pady=10)
        self._ex_result = tk.Label(work, text="", fg=SUCCESS, bg=BG, font=FONT_SM,
                                   justify="left")
        self._ex_result.pack(anchor="w")

        StyledButton(actions, "📝 Сохранить текст (.txt)",
                     self._ex_text).pack(side="right")
        StyledButton(actions, "🖼 Извлечь изображения", self._ex_images,
                     color=SURFACE2).pack(side="right", padx=8)

    def _ex_pages(self):
        rng = self._ex_range.var.get().strip()
        if not rng:
            return list(range(self._ex_src.total))
        return self._ex_range.indices()

    def _ex_text(self):
        src = self._ex_src
        if not src.require():
            return
        try:
            pages = self._ex_pages()
        except ValueError as e:
            messagebox.showerror("Ошибка диапазона", str(e))
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Текстовый файл", "*.txt")],
            title="Сохранить текст как…",
            initialfile=os.path.splitext(os.path.basename(src.path))[0] + ".txt")
        if not out or not check_not_same(src.path, out):
            return
        try:
            self._busy("Извлечение текста…")
            reader = src.reader()
            chunks, empty, failed = [], 0, []
            for n, i in enumerate(pages):
                try:
                    text = reader.pages[i].extract_text() or ""
                except Exception:
                    text = ""
                    failed.append(i + 1)
                else:
                    if not text.strip():
                        empty += 1
                if self._ex_pagebreaks.get():
                    chunks.append(f"───── Страница {i + 1} ─────\n{text.rstrip()}\n")
                else:
                    chunks.append(text.rstrip() + "\n")
                if n % 10 == 0:
                    self._set_status(f"Извлечение текста… {n + 1} из {len(pages)}", WARNING)
            # errors="replace": одиночные суррогаты из битых шрифтов не должны
            # обрывать запись
            with atomic_open(out, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(chunks))
            notes = []
            if empty:
                notes.append(f"без текстового слоя (скан?): {empty} стр.")
            if failed:
                shown = ", ".join(map(str, failed[:10])) + ("…" if len(failed) > 10 else "")
                notes.append(f"текст не удалось разобрать на страницах: {shown}")
            self._ex_result.config(
                text=f"Текст сохранён: {short_name(out)}  ·  страниц: {len(pages)}"
                     + "".join(f"  ·  {n}" for n in notes),
                fg=WARNING if notes else SUCCESS)
            self._done(f"Текст извлечён ({len(pages)} стр.) → {short_name(out)}",
                       f"Файл сохранён:\n{out}", notes)
        except Exception as e:
            self._fail(e, "Ошибка при извлечении текста")

    def _ex_images(self):
        src = self._ex_src
        if not src.require():
            return
        try:
            pages = self._ex_pages()
        except ValueError as e:
            messagebox.showerror("Ошибка диапазона", str(e))
            return
        folder = filedialog.askdirectory(title="Папка для изображений")
        if not folder:
            return
        try:
            self._busy("Извлечение изображений…")
            reader = src.reader()
            saved, failed = 0, 0
            for n, i in enumerate(pages):
                try:
                    images = reader.pages[i].images
                    count = len(images)
                except Exception:
                    failed += 1         # изображения страницы не читаются
                    continue
                for k in range(count):
                    try:
                        img = images[k]
                        ext = os.path.splitext(img.name or "")[1] or ".png"
                        data = img.data
                    except Exception:
                        failed += 1     # поток изображения не декодируется
                        continue
                    target = unique_path(os.path.join(
                        folder, f"стр{i + 1:04d}_{k + 1:02d}{ext}"))
                    with atomic_open(target) as f:
                        f.write(data)
                    saved += 1
                if n % 10 == 0:
                    self._set_status(f"Извлечение изображений… {n + 1} из {len(pages)}",
                                     WARNING)
            notes = [f"не удалось извлечь изображений: {failed}"] if failed else []
            if saved:
                self._ex_result.config(
                    text=f"Извлечено изображений: {saved}  →  {short_name(folder)}"
                         + (f"  ·  ошибок: {failed}" if failed else ""),
                    fg=WARNING if failed else SUCCESS)
                self._done(f"Извлечено изображений: {saved}",
                           f"Изображения сохранены в папку:\n{folder}\n\nФайлов: {saved}",
                           notes)
            elif failed:
                raise RuntimeError(f"Ни одно изображение не удалось извлечь "
                                   f"(ошибок: {failed}). Возможно, файл повреждён.")
            else:
                self._idle()
                self._set_status("Изображения не найдены", WARNING)
                self._ex_result.config(text="В выбранных страницах изображений не найдено.",
                                       fg=WARNING)
                messagebox.showinfo("Ничего не найдено",
                                    "В выбранных страницах нет встроенных растровых "
                                    "изображений.")
        except Exception as e:
            self._fail(e, "Ошибка при извлечении изображений")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    try:
        app = PDFManager()
    except Exception:
        # окно не создалось: в сборке без консоли сообщение иначе не увидеть
        path = log_exception(*sys.exc_info())
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, "Программу не удалось запустить."
                             + (f"\n\nПодробности записаны в файл:\n{path}" if path else ""))
        root.destroy()
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
