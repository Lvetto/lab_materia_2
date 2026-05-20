#!/bin/bash

# Sposta l'esecuzione nella cartella in cui risiede lo script
cd "$(dirname "$0")"

VENV_DIR="./.venv"
NOTEBOOK_NAME="interfaces/final_interfaces.ipynb"

echo "[1/2] Verifica del Virtual Environment locale..."
if [ ! -d "$VENV_DIR" ]; then
    echo "ERRORE: La cartella del venv '$VENV_DIR' non è stata trovata."
    exit 1
fi

echo "[2/2] Avvio di Voilà in ambiente isolato..."

# Forza TUTTE le directory di Jupyter dentro il venv per evitare PermissionError
export JUPYTER_CONFIG_DIR="$VENV_DIR/etc/jupyter"
export JUPYTER_DATA_DIR="$VENV_DIR/share/jupyter"
export JUPYTER_RUNTIME_DIR="$VENV_DIR/share/jupyter/runtime"

# Disabilita esplicitamente il tentativo di migrazione di vecchie configurazioni
export JUPYTER_NO_CONFIG=1

"$VENV_DIR/bin/voila" "$NOTEBOOK_NAME"