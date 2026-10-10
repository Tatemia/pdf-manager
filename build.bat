@echo off
rem Пустой элемент в начале PATH (";C:\...") ломает поиск программ в cmd:
rem не находятся даже chcp и py. Убираем пустые элементы до первого вызова.
if "%PATH:~0,1%"==";" set "PATH=%PATH:~1%"
set "PATH=%PATH:;;=;%"
chcp 65001 >nul
setlocal

rem ===========================================================================
rem  Сборка портативного исполняемого файла «PDF Manager» для Windows
rem
rem  Требуется Python 3.10 или новее (python.org): этого требует Pillow 12.
rem  Он ищется через лаунчер py, который ставится вместе с Python, а если
rem  лаунчера нет, берётся python из PATH. Программа заявлена для Windows
rem  10 и 11, поэтому подходят и современные версии Python (3.12+).
rem
rem  Версии Python и Tcl/Tk, вошедших в сборку, указаны
rem  в assets\THIRD-PARTY-NOTICES.txt — при смене Python обновите их там.
rem
rem  Результат: dist\PDF Manager.exe — один файл, не требующий установки.
rem ===========================================================================

cd /d "%~dp0"

echo.
echo [1/4] Поиск Python 3.10 или новее...
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo ОШИБКА: не найден Python 3.10 или новее.
    echo Установите Python с https://python.org
    pause
    exit /b 1
)
%PY% --version

echo.
echo [2/4] Создание изолированного окружения сборки...
if exist build-venv (
    build-venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
        echo Окружение build-venv создано другой версией Python, пересоздаю...
        rmdir /s /q build-venv
    )
)
if not exist build-venv (
    %PY% -m venv build-venv || goto :error
)

echo.
echo [3/4] Установка и обновление зависимостей...
build-venv\Scripts\python.exe -m pip install --upgrade pip >nul
build-venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt pyinstaller || goto :error

echo.
echo [4/4] Сборка исполняемого файла...
build-venv\Scripts\pyinstaller.exe --clean --noconfirm pdfmanager.spec || goto :error

echo.
echo ===========================================================================
echo  Готово:  "%cd%\dist\PDF Manager.exe"
echo  Этот файл можно скопировать на любой компьютер с Windows и запустить.
echo ===========================================================================
echo.
pause
exit /b 0

:error
echo.
echo СБОРКА НЕ ВЫПОЛНЕНА. См. сообщения выше.
pause
exit /b 1
