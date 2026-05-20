@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI\"
set "VENV_DIR=%ROOT_DIR%.venv"
set "CONDA_ENV=lab_materia_2"

where conda >nul 2>&1
if %errorlevel%==0 (
    echo Conda rilevato. Uso ambiente "%CONDA_ENV%".
    conda env list | findstr /i /c:"%CONDA_ENV%" >nul 2>&1
    if not %errorlevel%==0 (
        echo Creo ambiente conda "%CONDA_ENV%".
        conda create -y -n "%CONDA_ENV%" python
    )
    conda run -n "%CONDA_ENV%" python -m pip install --upgrade pip
    conda run -n "%CONDA_ENV%" python -m pip install -r "%ROOT_DIR%requirements.txt"
    conda run -n "%CONDA_ENV%" python -m pip install -e "%ROOT_DIR%"
) else (
    echo Conda non trovato. Uso venv locale.
    py -m venv "%VENV_DIR%"
    call "%VENV_DIR%\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r "%ROOT_DIR%requirements.txt"
    python -m pip install -e "%ROOT_DIR%"
)

echo Installazione completata (Windows).
