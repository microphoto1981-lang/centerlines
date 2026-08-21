@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo CENTERLINES - BUILD EXE
echo ========================================
echo.
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py"
) else (
    set "PY=python"
)

echo [1/5] Checking Python...
%PY% --version
if errorlevel 1 goto :error

echo [2/5] Installing/updating build dependencies...
%PY% -m pip install -U pyinstaller ezdxf ifcopenshell
if errorlevel 1 goto :error

echo [3/5] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist CENTERLINES.spec del /q CENTERLINES.spec

echo [4/5] Building CENTERLINES.exe...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name CENTERLINES --collect-submodules ezdxf --collect-submodules ifcopenshell building_setup.py
if errorlevel 1 goto :error

echo [5/5] Checking result...
if not exist "dist\CENTERLINES.exe" goto :error

echo.
echo ========================================
echo BUILD OK
echo ========================================
echo EXE: %CD%\dist\CENTERLINES.exe
echo.
echo The EXE can be copied to another Windows PC.
echo Input DXF files are selected through the GUI.
echo.
pause
exit /b 0

:error
echo.
echo ========================================
echo BUILD ERROR
echo ========================================
echo See the message above.
pause
exit /b 1
