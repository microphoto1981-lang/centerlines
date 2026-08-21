@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo CENTERLINES - BUILD EXE
echo ========================================
echo.
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

echo [1/5] Checking Python...
%PY% --version
if errorlevel 1 goto :error

echo [2/5] Installing build dependencies...
%PY% -m pip install -U pyinstaller ezdxf ifcopenshell
if errorlevel 1 goto :error

echo [3/5] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist CENTERLINES.spec del /q CENTERLINES.spec

echo [4/5] Building CENTERLINES.exe...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name CENTERLINES --add-data "centerlines.py;." --hidden-import agent --hidden-import unified_sdnf_writer --hidden-import ifc_writer --collect-submodules ezdxf --collect-submodules ifcopenshell centerlines_launcher.py
if errorlevel 1 goto :error

echo [5/5] Checking result...
if not exist "dist\CENTERLINES.exe" goto :error

echo.
echo ========================================
echo BUILD OK
echo ========================================
echo EXE: %CD%\dist\CENTERLINES.exe
echo.
echo Only CENTERLINES.exe is required on the target PC.
echo DXF files are selected through the GUI.
echo.
pause
exit /b 0

:error
echo.
echo ========================================
echo BUILD ERROR
echo ========================================
echo See the message above.
echo.
pause
exit /b 1
