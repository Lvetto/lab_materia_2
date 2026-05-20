@echo off
:: Forza lo script a eseguire i comandi partendo dalla cartella in cui si trova
cd /d "%~dp0"

:: ==========================================
:: CONFIGURAZIONE UTENTE
:: ==========================================
set CONDA_ENV_NAME=nome_del_tuo_ambiente_conda
set NOTEBOOK_NAME=interfaces/final_interfaces.ipynb
:: ==========================================

echo [1/2] Ricerca e attivazione dell'ambiente Conda: %CONDA_ENV_NAME%...

if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\miniconda3\Scripts\activate.bat" %CONDA_ENV_NAME%
) else if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\anaconda3\Scripts\activate.bat" %CONDA_ENV_NAME%
) else (
    :: Fallback se conda e gia esposto globalmente nel prompt dei comandi
    call conda activate %CONDA_ENV_NAME%
)

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