@echo off
REM ===========================================================================
REM  start_bot.bat - starter TorsdagBot
REM
REM  Filen virker bade:
REM    * i projektmappen (starter bot.py med Python), og
REM    * i mappen "dist" ved siden af TorsdagBot.exe (starter .exe-filen).
REM
REM  Botten genstarter sig selv hvis den skulle lukke uventet.
REM ===========================================================================

chcp 65001 >nul
title TorsdagBot
cd /d "%~dp0"

REM --- Advar hvis .env mangler ---------------------------------------------
if not exist ".env" (
    echo.
    echo [ADVARSEL] Der er ingen .env-fil i denne mappe:
    echo            %~dp0
    echo.
    echo            Kopier ".env.example" til ".env" og udfyld
    echo            DISCORD_TOKEN, CHANNEL_ID og OWNER_ID.
    echo.
    pause
)

:start
echo.
echo === Starter TorsdagBot (%date% %time%) ===
echo.

if exist "TorsdagBot.exe" (
    REM Vi ligger i dist-mappen ved siden af den byggede .exe-fil
    "TorsdagBot.exe"
) else if exist "dist\TorsdagBot.exe" (
    REM Vi ligger i projektmappen, men .exe-filen er allerede bygget.
    REM .env og poll_state.json skal ligge ved siden af .exe-filen.
    cd /d "%~dp0dist"
    "TorsdagBot.exe"
    cd /d "%~dp0"
) else (
    REM Ingen .exe - kor kildekoden direkte
    python bot.py
    if errorlevel 9009 (
        echo [FEJL] Python blev ikke fundet. Installer Python, eller byg
        echo        foerst .exe-filen med build.bat.
        pause
        exit /b 1
    )
)

echo.
echo === TorsdagBot stoppede (afslutningskode %errorlevel%) ===
echo === Genstarter om 15 sekunder. Luk vinduet for at stoppe helt. ===
timeout /t 15 /nobreak >nul
goto :start
