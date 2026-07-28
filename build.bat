@echo off
REM ===========================================================================
REM  build.bat - bygger TorsdagBot.exe med PyInstaller
REM
REM  Resultatet lander i mappen "dist" som:  dist\TorsdagBot.exe
REM  Dobbeltklik denne fil, eller kor den fra en kommandoprompt.
REM ===========================================================================

REM UTF-8 i konsollen, sa danske tegn vises korrekt
chcp 65001 >nul

setlocal enabledelayedexpansion

REM Arbejd altid i mappen hvor denne .bat-fil ligger
cd /d "%~dp0"

echo.
echo ===========================================================
echo  Bygger TorsdagBot.exe
echo ===========================================================
echo.

REM --- 1. Find Python -------------------------------------------------------
REM (delayed expansion bruges, saa variablen laeses paa det rigtige tidspunkt)
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 set "PY=py -3"
!PY! --version >nul 2>&1
if errorlevel 1 (
    echo [FEJL] Python blev ikke fundet.
    echo        Installer Python 3.10 eller nyere fra https://www.python.org/downloads/
    echo        Husk at saette flueben i "Add Python to PATH" under installationen.
    goto :fejl
)

echo [1/5] Python fundet:
!PY! --version
echo.

REM --- 2. Installer afhaengigheder -----------------------------------------
echo [2/5] Installerer afhaengigheder ...
!PY! -m pip install --upgrade pip
if errorlevel 1 goto :fejl_pip

!PY! -m pip install -r requirements.txt
if errorlevel 1 goto :fejl_pip

!PY! -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fejl_pip
echo.

REM --- 3. Ryd op fra tidligere builds --------------------------------------
echo [3/5] Rydder op efter tidligere builds ...
if exist "build" rmdir /s /q "build"
if exist "TorsdagBot.spec" del /q "TorsdagBot.spec"
if exist "dist\TorsdagBot.exe" del /q "dist\TorsdagBot.exe"
echo.

REM --- 4. Kor PyInstaller ---------------------------------------------------
REM   --onefile        en enkelt .exe-fil
REM   --console        almindeligt konsolvindue (logningen kan laeses)
REM   --clean          ryd PyInstallers cache
REM   --noconfirm      overskriv dist uden at spoerge
REM   --collect-all tzdata   tidszone-databasen skal med i .exe-filen,
REM                          ellers kan Europe/Copenhagen ikke slas op
echo [4/5] Koerer PyInstaller ...
!PY! -m PyInstaller ^
    --onefile ^
    --console ^
    --clean ^
    --noconfirm ^
    --name TorsdagBot ^
    --collect-all tzdata ^
    --collect-submodules discord ^
    --hidden-import dotenv ^
    bot.py
if errorlevel 1 goto :fejl_build
echo.

REM --- 5. Laeg .env.example ved siden af .exe-filen -------------------------
echo [5/5] Kopierer hjaelpefiler til dist ...
if exist ".env.example" copy /y ".env.example" "dist\.env.example" >nul
if exist "config.example.json" copy /y "config.example.json" "dist\config.example.json" >nul
if exist "start_bot.bat" copy /y "start_bot.bat" "dist\start_bot.bat" >nul
if exist ".env" (
    if not exist "dist\.env" copy /y ".env" "dist\.env" >nul
)
echo.

echo ===========================================================
echo  FAERDIG!
echo.
echo  Din fil ligger her:  %~dp0dist\TorsdagBot.exe
echo.
echo  Husk: .env-filen SKAL ligge i samme mappe som .exe-filen.
echo        Aabn mappen "dist", omdoeb ".env.example" til ".env"
echo        og udfyld DISCORD_TOKEN, CHANNEL_ID og OWNER_ID.
echo ===========================================================
echo.
pause
exit /b 0

:fejl_pip
echo.
echo [FEJL] Kunne ikke installere afhaengighederne.
echo        Tjek din internetforbindelse, eller proev at koere denne fil
echo        som administrator.
goto :fejl

:fejl_build
echo.
echo [FEJL] PyInstaller kunne ikke bygge .exe-filen.
echo        Laes fejlbeskeden ovenfor. Proev evt. at slette mapperne
echo        "build" og "dist" og koere build.bat igen.
goto :fejl

:fejl
echo.
pause
exit /b 1
