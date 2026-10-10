"""Интеграционные тесты: операции разделов через окно программы.

Диалоги подменяются фикстурой dialogs, поэтому проверяются настоящие
методы _*_run() на настоящих PDF. Запуск: xvfb-run -a pytest tests
"""

import io
import os

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from reportlab.pdfgen import canvas

import main
from conftest import make_pdf, raw_contains


def load(src, path):
    src.choose(path)
    assert src.path == path


def test_delete_removes_page_without_leaking_it(app, dialogs, pdf_factory, tmp_path):
    path = pdf_factory(n=3, link_to=2, meta={"/Title": "Отчёт"})
    load(app._del_src, path)
    app._del_range.var.set("3")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._del_run()
    out = PdfReader(dialogs.save_path)
    assert len(out.pages) == 2
    assert not raw_contains(dialogs.save_path, "SECRETTEXT3")
    assert out.metadata["/Title"] == "Отчёт"
    assert dialogs.last()[0] == "showinfo"


def test_extract_rejects_range_of_only_commas(app, dialogs, pdf_factory, tmp_path):
    load(app._spl_src, pdf_factory(n=3))
    app._spl_range.var.set(",")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._spl_run()
    assert dialogs.last()[0] == "showerror"
    assert not os.path.exists(dialogs.save_path)


def test_protected_source_requires_confirmation(app, dialogs, pdf_factory, tmp_path):
    w = PdfWriter(clone_from=PdfReader(pdf_factory(n=2)))
    w.encrypt("pw", algorithm="AES-256")
    enc = str(tmp_path / "enc.pdf")
    with open(enc, "wb") as f:
        w.write(f)
    dialogs.password = "pw"
    load(app._rot_src, enc)
    dialogs.yes = False
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._rot_run()
    assert dialogs.messages[-1][0] == "askyesno"
    assert not os.path.exists(dialogs.save_path)


def _dark_bbox(path, page_index=0):
    """Рамка тёмных пикселей отрисованной страницы (с учётом /Rotate)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    img = doc[page_index].render(scale=1).to_pil().convert("L")
    doc.close()
    mask = img.point(lambda v: 255 if v < 128 else 0)
    return img.size, mask.getbbox()


@pytest.mark.parametrize("rotate", [0, 90, 270])
def test_numbering_lands_bottom_centre_on_rotated_pages(app, dialogs, tmp_path, rotate):
    # пустая страница со смещённой рамкой: тёмным будет только номер
    path = make_pdf(tmp_path / "blank.pdf", n=1, text="", rotate=rotate,
                    mediabox=[100, 100, 500, 700])
    load(app._st_src, path)
    app._st_nb.select(0)
    app._num_fmt.set("{n}")
    app._num_pos.set("bc")
    app._num_size.set("20")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._st_run()
    (w, h), bbox = _dark_bbox(dialogs.save_path)
    assert bbox is not None, "номер не виден"
    cx, bottom = (bbox[0] + bbox[2]) / 2, bbox[3]
    assert abs(cx - w / 2) < 15
    assert h - 60 < bottom <= h


def test_numbering_rejects_broken_template(app, dialogs, pdf_factory, tmp_path):
    load(app._st_src, pdf_factory(n=1))
    app._st_nb.select(0)
    app._num_fmt.set("{n")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._st_run()
    assert dialogs.last()[1] == "Неверный формат"
    assert not os.path.exists(dialogs.save_path)


def test_compress_really_compresses_content_streams(app, dialogs, tmp_path):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=0)
    for _ in range(5):
        for y in range(50, 800, 12):
            c.drawString(40, y, "несжатый поток содержимого " * 3)
        c.showPage()
    c.save()
    path = tmp_path / "raw.pdf"
    path.write_bytes(buf.getvalue())
    load(app._cmp_src, str(path))
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._cmp_run()
    assert os.path.getsize(dialogs.save_path) < os.path.getsize(path) / 2
    assert dialogs.last()[0] == "showinfo"


def test_split_by_bookmarks_keeps_leading_pages(app, dialogs, pdf_factory, tmp_path):
    path = pdf_factory(n=6, outline=[("Глава 1", 2), ("Глава 2", 4)])
    load(app._sp_src, path)
    app._sp_mode.set("marks")
    folder = tmp_path / "parts"
    folder.mkdir()
    dialogs.folder = str(folder)
    app._sp_run()
    counts = {name: len(PdfReader(str(folder / name)).pages)
              for name in sorted(os.listdir(folder))}
    assert counts == {"01_начало.pdf": 2, "02_Глава 1.pdf": 2, "03_Глава 2.pdf": 2}


def test_text_export_refuses_to_overwrite_source(app, dialogs, pdf_factory):
    path = pdf_factory(n=1)
    before = open(path, "rb").read()
    load(app._ex_src, path)
    dialogs.save_path = path
    app._ex_text()
    assert open(path, "rb").read() == before
    assert dialogs.last()[1] == "Нельзя перезаписать исходник"


def test_images_to_pdf_applies_exif_orientation(app, dialogs, tmp_path):
    from PIL import Image
    img = Image.new("RGB", (300, 100), "red")
    exif = Image.Exif()
    exif[0x0112] = 6                      # «повернуть на 90° по часовой»
    photo = tmp_path / "photo.jpg"
    img.save(photo, exif=exif)
    app._image_paths[:] = [str(photo)]
    app._img_mode.set("fit")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._img_run()
    box = PdfReader(dialogs.save_path).pages[0].mediabox
    assert float(box.height) > float(box.width)
    app._image_paths.clear()


def test_merge_combines_files_with_ranges(app, dialogs, pdf_factory, tmp_path):
    a, b = pdf_factory(n=3, text="A"), pdf_factory(n=2, text="B")
    app._merge_entries.clear()
    app._merge_add([a, b])
    app._merge_entries[0]["range_var"].set("2-3")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._merge_run()
    texts = [p.extract_text().strip() for p in PdfReader(dialogs.save_path).pages]
    assert texts == ["A2", "A3", "B1", "B2"]
    app._merge_clear()


def test_merge_cards_do_not_accumulate_traces(app, pdf_factory):
    app._merge_entries.clear()
    app._merge_add([pdf_factory(n=1), pdf_factory(n=1)])
    for _ in range(5):
        app._merge_move(0, 1)
    var = app._merge_entries[0]["range_var"]
    assert len(var.trace_info()) == 1
    app._merge_clear()


def test_owner_password_restricts_permissions(app, dialogs, pdf_factory, tmp_path):
    load(app._sec_src, pdf_factory(n=1))
    app._sec_mode.set("set")
    app._sec_user.set("u")
    app._sec_repeat.set("u")
    app._sec_owner.set("o")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._sec_run()
    r = PdfReader(dialogs.save_path)
    assert r.decrypt("u")
    perms = r.user_access_permissions
    assert not perms & UserAccessPermissions.MODIFY
    assert perms & UserAccessPermissions.PRINT
    assert app._sec_user.get() == ""          # поля паролей очищены


def test_owner_password_equal_to_user_password_is_rejected(app, dialogs, pdf_factory, tmp_path):
    load(app._sec_src, pdf_factory(n=1))
    app._sec_mode.set("set")
    for var in (app._sec_user, app._sec_repeat, app._sec_owner):
        var.set("same")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._sec_run()
    assert dialogs.last()[1] == "Одинаковые пароли"
    assert not os.path.exists(dialogs.save_path)


def test_clear_metadata_leaves_no_producer(app, dialogs, pdf_factory, tmp_path):
    load(app._meta_src, pdf_factory(meta={"/Author": "Иванов"}))
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._meta_run(clear=True)
    assert PdfReader(dialogs.save_path).metadata is None


def test_thumbnail_picker_cancels_pending_render_on_close(app, pdf_factory):
    path = pdf_factory(n=40)
    load(app._del_src, path)
    picker = main.ThumbnailPicker(app, app._del_src)
    for _ in range(5):
        app.update()
    assert picker._after_id is not None
    picker._cancel()
    assert picker._after_id is None
    for _ in range(5):
        app.update()


def test_callback_exception_is_logged_and_shown(app, dialogs, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        raise KeyError("сломалось")
    except KeyError as e:
        app.report_callback_exception(type(e), e, e.__traceback__)
    log = tmp_path / main.APP_NAME / "errors.log"
    assert "KeyError" in log.read_text(encoding="utf-8")
    assert dialogs.last()[1] == "Внутренняя ошибка"


def test_images_to_pdf_keeps_16bit_scan_visible(app, dialogs, tmp_path):
    from PIL import Image
    scan = tmp_path / "scan16.tif"
    Image.new("I;16", (60, 80), 8000).save(scan)       # тёмно-серый, 16 бит
    app._image_paths[:] = [str(scan)]
    app._img_mode.set("fit")
    dialogs.save_path = str(tmp_path / "out.pdf")
    app._img_run()
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(dialogs.save_path)
    pixel = doc[0].render(scale=1).to_pil().convert("L").getpixel((20, 20))
    doc.close()
    assert pixel < 100, "16-битный скан превратился в белую страницу"
    app._image_paths.clear()
