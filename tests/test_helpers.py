"""Модульные тесты чистых функций main.py (без окна Tk)."""

import os
import stat

import pytest
from pypdf import PdfReader, PdfWriter

import main
from conftest import raw_contains


# ── диапазоны страниц ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("1", [0]), ("3,1", [0, 2]), ("2-4", [1, 2, 3]), ("1, 3-4, 3", [0, 2, 3]),
])
def test_parse_page_range_returns_sorted_unique_indices(text, expected):
    assert main.parse_page_range(text, 5) == expected


@pytest.mark.parametrize("text", [",", " , ,", ""])
def test_parse_page_range_rejects_input_without_pages(text):
    with pytest.raises(ValueError, match="ни одной страницы"):
        main.parse_page_range(text, 5)


@pytest.mark.parametrize("text", ["0", "6", "4-2", "a", "1-x"])
def test_parse_page_range_rejects_out_of_bounds_and_garbage(text):
    with pytest.raises(ValueError):
        main.parse_page_range(text, 5)


def test_parse_page_order_keeps_order_repeats_and_reverse_ranges():
    assert main.parse_page_order("3,1,1,5-4", 5) == [2, 0, 0, 4, 3]


def test_parse_page_order_rejects_input_without_pages():
    with pytest.raises(ValueError, match="ни одной страницы"):
        main.parse_page_order(",", 5)


def test_compress_ranges_round_trips_with_parse():
    assert main.compress_ranges([0, 1, 2, 4, 6, 7]) == "1-3,5,7-8"
    assert main.parse_page_range("1-3,5,7-8", 8) == [0, 1, 2, 4, 6, 7]


# ── имена файлов ─────────────────────────────────────────────────────────────
def test_safe_stem_removes_path_and_control_characters():
    assert main.safe_stem('a/b\\c:d*?"<>|\x00\x07\x1fe') == "a_b_c_d_e"
    assert main.safe_stem("  ..  ") == "page"


def test_unique_path_appends_counter(tmp_path):
    first = tmp_path / "x.pdf"
    first.write_bytes(b"")
    assert main.unique_path(str(first)) == str(tmp_path / "x (2).pdf")


# ── атомарная запись ─────────────────────────────────────────────────────────
def test_atomic_open_keeps_original_when_writing_fails(tmp_path):
    target = tmp_path / "dest.pdf"
    target.write_bytes(b"ORIGINAL")
    with pytest.raises(RuntimeError):
        with main.atomic_open(str(target)) as f:
            f.write(b"PARTIAL")
            raise RuntimeError("сбой посреди записи")
    assert target.read_bytes() == b"ORIGINAL"
    assert os.listdir(tmp_path) == ["dest.pdf"]      # временный файл удалён


def test_atomic_open_creates_file_with_regular_permissions(tmp_path):
    target = tmp_path / "new.txt"
    with main.atomic_open(str(target), "w", encoding="utf-8") as f:
        f.write("текст")
    assert target.read_text(encoding="utf-8") == "текст"
    assert stat.S_IMODE(os.stat(target).st_mode) == main._FILE_MODE


# ── закладки ─────────────────────────────────────────────────────────────────
def test_plan_by_bookmarks_keeps_pages_before_first_bookmark():
    plan = main.plan_by_bookmarks([("Ch1", 2, 0), ("Ch2", 4, 0)], 6)
    assert [pages for _, pages in plan] == [[0, 1], [2, 3], [4, 5]]
    assert plan[0][0] == "01_начало"


def test_plan_by_bookmarks_merges_bookmarks_on_same_page():
    plan = main.plan_by_bookmarks([("A", 0, 0), ("B", 0, 0), ("C", 2, 0)], 4)
    assert [pages for _, pages in plan] == [[0, 1], [2, 3]]


def test_plan_by_bookmarks_rejects_marks_outside_document():
    with pytest.raises(ValueError):
        main.plan_by_bookmarks([("X", 10, 0)], 3)


def test_flatten_outline_skips_bookmark_without_target(pdf_factory):
    from pypdf.generic import ArrayObject, NameObject, NullObject
    path = pdf_factory(n=3, outline=[("Ch1", 1)])
    w = PdfWriter(clone_from=PdfReader(path))
    w.add_outline_item("Broken", 0)
    # подменяем цель второй закладки на null
    item = w.outline[1].indirect_reference.get_object()
    item.pop("/A", None)
    item[NameObject("/Dest")] = ArrayObject([NullObject(), NameObject("/Fit")])
    broken = os.path.join(os.path.dirname(path), "broken.pdf")
    with open(broken, "wb") as f:
        w.write(f)
    marks = main.flatten_outline(PdfReader(broken))
    assert [(title, page) for title, page, _ in marks] == [("Ch1", 1)]


# ── копирование страниц ──────────────────────────────────────────────────────
def test_select_pages_does_not_leak_removed_page_through_link(pdf_factory, tmp_path):
    path = pdf_factory(n=3, link_to=2, meta={"/Title": "T"})
    writer, notes = main.select_pages(PdfReader(path), [0, 1])
    out = str(tmp_path / "out.pdf")
    main.write_pdf(writer, out)
    assert notes == []
    assert len(PdfReader(out).pages) == 2
    assert not raw_contains(out, "SECRETTEXT3")
    assert PdfReader(out).metadata["/Title"] == "T"


def test_prune_links_stops_leak_in_page_by_page_copy(pdf_factory, tmp_path):
    path = pdf_factory(n=3, link_to=2)
    reader = PdfReader(path)
    main.prune_links(reader, [0, 1])
    writer = PdfWriter()
    for i in (0, 1):
        writer.add_page(reader.pages[i])
    out = str(tmp_path / "out.pdf")
    main.write_pdf(writer, out)
    assert not raw_contains(out, "SECRETTEXT3")


def test_prune_links_keeps_links_to_kept_pages(pdf_factory):
    path = pdf_factory(n=3, link_to=1)
    reader = PdfReader(path)
    main.prune_links(reader, [0, 1])
    assert len(reader.pages[0]["/Annots"]) == 1


def test_select_pages_supports_repeats_and_reordering(pdf_factory):
    path = pdf_factory(n=3)
    writer, _ = main.select_pages(PdfReader(path), [2, 0, 0])
    texts = [p.extract_text().strip() for p in writer.pages]
    assert texts == ["SECRETTEXT3", "SECRETTEXT1", "SECRETTEXT1"]


def test_strip_metadata_removes_info_including_producer(pdf_factory, tmp_path):
    path = pdf_factory(meta={"/Author": "A"})
    writer, _ = main.clone_document(PdfReader(path))
    main.strip_metadata(writer)
    out = str(tmp_path / "out.pdf")
    main.write_pdf(writer, out)
    assert PdfReader(out).metadata is None


# ── шифрование ───────────────────────────────────────────────────────────────
def _encrypted(path, tmp_path, user, owner):
    w = PdfWriter(clone_from=PdfReader(path))
    w.encrypt(user, owner_password=owner, algorithm="AES-256")
    out = str(tmp_path / "enc.pdf")
    with open(out, "wb") as f:
        w.write(f)
    return out


def test_open_pdf_does_not_prompt_for_owner_only_restrictions(pdf_factory, tmp_path, monkeypatch):
    enc = _encrypted(pdf_factory(), tmp_path, "", "owner")
    monkeypatch.setattr(main.simpledialog, "askstring",
                        lambda *a, **kw: pytest.fail("пароль запрошен зря"))
    reader, pwd = main.open_pdf(enc)
    assert pwd == "" and len(reader.pages) == 3


def test_open_pdf_asks_password_and_raises_cancelled(pdf_factory, tmp_path, monkeypatch):
    enc = _encrypted(pdf_factory(), tmp_path, "secret", None)
    monkeypatch.setattr(main.simpledialog, "askstring", lambda *a, **kw: None)
    with pytest.raises(main.Cancelled):
        main.open_pdf(enc)
    monkeypatch.setattr(main.simpledialog, "askstring", lambda *a, **kw: "secret")
    assert main.open_pdf(enc)[1] == "secret"


# ── нумерация на повёрнутых и смещённых страницах ───────────────────────────
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_visible_frame_maps_visible_bottom_centre_to_visual_bottom(pdf_factory, rotate):
    path = pdf_factory(n=1, rotate=rotate, mediabox=[100, 100, 500, 700])
    page = PdfReader(path).pages[0]
    (vw, vh), ctm = main.visible_frame(page)
    x, y = ctm.apply_on((vw / 2, 0))
    # точка «снизу по центру» в видимых координатах должна оказаться на краю
    # страницы, который после поворота при показе станет нижним
    # /Rotate — поворот по часовой: при 90° низом становится правый край
    expected = {0: (300, 100), 90: (500, 400), 180: (300, 700), 270: (100, 400)}[rotate]
    assert (round(x), round(y)) == expected
    assert (vw, vh) == ((400, 600) if rotate in (0, 180) else (600, 400))


# ── повреждённые аннотации и повторы страниц (регрессии ревью) ─────────────
def _with_broken_annots(path, tmp_path):
    from pypdf.generic import ArrayObject, NullObject, NumberObject, NameObject
    w = PdfWriter(clone_from=PdfReader(path))
    w.pages[1][NameObject("/Annots")] = ArrayObject([NullObject(), NumberObject(7)])
    out = str(tmp_path / "broken_annots.pdf")
    with open(out, "wb") as f:
        w.write(f)
    return out


def test_select_pages_survives_broken_annotation_entries(pdf_factory, tmp_path):
    path = _with_broken_annots(pdf_factory(n=3), tmp_path)
    writer, notes = main.select_pages(PdfReader(path), [0, 1])
    assert len(writer.pages) == 2


def test_prune_links_ignores_non_dictionary_entries(pdf_factory, tmp_path):
    path = _with_broken_annots(pdf_factory(n=3), tmp_path)
    main.prune_links(PdfReader(path), [0, 1])


def test_select_pages_keeps_links_on_every_copy_of_repeated_page(pdf_factory):
    path = pdf_factory(n=3, link_to=1)
    writer, _ = main.select_pages(PdfReader(path), [0, 1, 0])
    annots = [len(p.get("/Annots") or []) for p in writer.pages]
    assert annots == [1, 0, 1]


def test_restricted_permissions_keep_reserved_bits():
    from pypdf.constants import UserAccessPermissions as U
    restricted = main.PDFManager.RESTRICTED
    assert restricted & U.PRINT and not restricted & U.MODIFY
    assert restricted & U.R7 and restricted & U.R13
