# -*- mode: python ; coding: utf-8 -*-
# Спецификация PyInstaller: портативный однофайловый исполняемый файл
# «PDF Manager» для Windows.
#
#   pyinstaller --clean --noconfirm pdfmanager.spec   → dist\PDF Manager.exe
#
# Собирать только на Windows (PyInstaller не умеет кросс-компиляцию).
# Обычно сборку запускает build.bat.

import os

from PyInstaller.utils.hooks import collect_all

# SPECPATH — каталог этого файла; от него считаются все пути ниже,
# поэтому сборку можно запускать из любого текущего каталога.
ROOT = SPECPATH


def project_path(*parts):
    return os.path.join(ROOT, *parts)


# ── Ресурсы ──────────────────────────────────────────────────────────────────
# main.py ищет их через resource_path("assets", <имя>), т. е. в каталоге
# assets\ внутри sys._MEIPASS. Список явный: пропавший файл остановит сборку,
# а не всплывёт у пользователя.
ASSETS = [
    "icon.ico",                  # значок окна (iconbitmap)
    "icon.png",                  # запасной значок (iconphoto)
    "DejaVuSans.ttf",            # кириллица для нумерации и водяных знаков
    "DejaVuSans-LICENSE.txt",    # лицензия шрифта обязана сопровождать его
    "THIRD-PARTY-NOTICES.txt",   # окно «О программе» → «Тексты лицензий»
]
datas = [(project_path("assets", name), "assets") for name in ASSETS]
binaries = []
hiddenimports = []


# ── Сторонние пакеты ─────────────────────────────────────────────────────────
# pypdfium2 (pdfium.dll) и tkinterdnd2 (бинарники tkdnd) обслуживаются хуками
# из pyinstaller-hooks-contrib (hook-pypdfium2*, hook-tkinterdnd2). Хук
# tkinterdnd2 берёт только каталог tkdnd для текущей платформы (win-x64),
# а не все 13 вариантов. Если хука нет (слишком старый hooks-contrib),
# забираем пакет целиком через collect_all, чтобы не потерять бинарники.
def has_contrib_hook(module):
    try:
        import _pyinstaller_hooks_contrib as contrib
    except ImportError:
        return False
    base = os.path.dirname(contrib.__file__)
    return any(
        os.path.isfile(os.path.join(base, sub, f"hook-{module}.py"))
        for sub in ("stdhooks", os.path.join("hooks", "stdhooks"))
    )


for module in ("pypdfium2", "pypdfium2_raw", "tkinterdnd2"):
    if has_contrib_hook(module):
        continue
    print(f"pdfmanager.spec: нет хука для {module}, используется collect_all")
    mod_datas, mod_binaries, mod_hidden = collect_all(module)
    datas += mod_datas
    binaries += mod_binaries
    hiddenimports += mod_hidden

# reportlab, cryptography и Pillow собираются штатными хуками.


a = Analysis(
    [project_path("main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDF Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX не используется: сжатые им файлы чаще дают ложные срабатывания
    # антивирусов.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=project_path("assets", "icon.ico"),
    version=project_path("version_info.txt"),
)
