"""Общие фикстуры: тестовые PDF и окно программы без участия пользователя."""

import io
import os
import sys

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def make_pdf(path, n=3, outline=(), link_to=None, meta=None, rotate=0,
             mediabox=None, text="SECRETTEXT"):
    """PDF из n страниц с текстом «{text}{номер}».

    outline — [(заголовок, индекс страницы)], link_to — индекс страницы,
    на которую ведёт ссылка со страницы 1.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(n):
        c.drawString(100, 700, f"{text}{i + 1}")
        c.showPage()
    c.save()
    buf.seek(0)
    w = PdfWriter(clone_from=PdfReader(buf))
    for title, page in outline:
        w.add_outline_item(title, page)
    if link_to is not None:
        annot = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): RectangleObject([0, 0, 50, 50]),
            NameObject("/Dest"): ArrayObject([w.pages[link_to].indirect_reference,
                                              NameObject("/Fit")])})
        w.pages[0][NameObject("/Annots")] = ArrayObject([w._add_object(annot)])
    for page in w.pages:
        if rotate:
            page.rotate(rotate)
        if mediabox:
            page.mediabox = RectangleObject(mediabox)
            page.cropbox = RectangleObject(mediabox)
    if meta:
        w.add_metadata(meta)
    with open(path, "wb") as f:
        w.write(f)
    return str(path)


def raw_contains(path, word):
    """Есть ли слово в любом потоке файла (в т. ч. в «невидимых» объектах)."""
    r = PdfReader(path)
    for num in range(1, int(r.trailer["/Size"])):
        try:
            obj = r.get_object(num)
        except Exception:
            continue
        if hasattr(obj, "get_data"):
            try:
                if word.encode() in obj.get_data():
                    return True
            except Exception:
                continue
    return False


@pytest.fixture
def pdf_factory(tmp_path):
    counter = {"n": 0}

    def factory(**kw):
        counter["n"] += 1
        return make_pdf(tmp_path / f"src{counter['n']}.pdf", **kw)
    return factory


class Dialogs:
    """Подмена диалогов Tk: ответы задаются заранее, сообщения копятся."""

    def __init__(self):
        self.save_path = None
        self.folder = None
        self.password = None
        self.yes = True
        self.messages = []

    def install(self, monkeypatch):
        fd, mb, sd = main.filedialog, main.messagebox, main.simpledialog
        monkeypatch.setattr(fd, "asksaveasfilename", lambda **kw: self.save_path)
        monkeypatch.setattr(fd, "askdirectory", lambda **kw: self.folder)
        monkeypatch.setattr(sd, "askstring", lambda *a, **kw: self.password)
        for kind in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(mb, kind, self._recorder(kind))
        monkeypatch.setattr(mb, "askyesno", self._ask)

    def _recorder(self, kind):
        def record(title, text="", **kw):
            self.messages.append((kind, title, text))
        return record

    def _ask(self, title, text="", **kw):
        self.messages.append(("askyesno", title, text))
        return self.yes

    def kinds(self):
        return [m[0] for m in self.messages]

    def last(self):
        return self.messages[-1] if self.messages else None


@pytest.fixture(scope="session")
def app():
    if not os.environ.get("DISPLAY"):
        pytest.skip("нужен X-сервер: запускайте через xvfb-run")
    application = main.PDFManager()
    application.withdraw()
    yield application
    application.destroy()


@pytest.fixture
def dialogs(monkeypatch):
    d = Dialogs()
    d.install(monkeypatch)
    return d
