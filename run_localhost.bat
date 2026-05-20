@echo off
:: Forza lo script a eseguire i comandi partendo dalla cartella in cui si trova
cd /d "%~dp0"

:: ==========================================
:: CONFIGURAZIONE UTENTE
:: ==========================================
set CONDA_ENV_NAME=lab_materia_2
set NOTEBOOK_NAME=interfaces/final_interfaces.ipynb
:: ==========================================

echo [1/2] Ricerca e attivazione dell'ambiente Conda: %CONDA_ENV_NAME%...

call conda activate %CONDA_ENV_NAME%

:: Controllo se l'attivazione ha avuto successo
if %errorlevel% neq 0 (
    echo.
    echo ERRORE: Impossibile attivare l'ambiente '%CONDA_ENV_NAME%'.
    echo Verifica il nome dell'ambiente o il percorso di installazione di Conda.
    pause
    exit /b
)

echo [2/2] Avvio di Voila per il notebook: %NOTEBOOK_NAME%...
voila %NOTEBOOK_NAME%

pause