# Laboratorio di Fisica della Materia 2

Repository per acquisizione e analisi dati del laboratorio (microbilancia al quarzo + camera + elettrometro).

La documentazione del codice è disponibile al [link](https://lvetto.github.io/lab_materia_2/lib.html).

## Struttura repository

```text
.
├── data/
├── documents/
│   ├── notes/
│   ├── paper/
│   └── references/
├── install_scripts/
│   ├── install_linux.sh
│   └── install_windows.bat
├── interfaces/
├── src/
│   ├── analisi/
│   └── lib/
├── temp/
├── requirements.txt
├── setup.py
└── README.md
```

## Contenuto directory

- `data/`: dati sperimentali (`raw` grezzi, `processed` elaborati).
- `documents/`: materiale di supporto (note, paper, riferimenti).
- `install_scripts/`: script di setup ambiente per Linux e Windows.
- `interfaces/`: notebook/interfacce per controllo strumenti e test acquisizione.
- `src/lib/`: driver strumenti e interfacce Python riusabili.
- `src/analisi/`: utility di analisi e correlazione segnali/immagini.
- `temp/`: prove, prototipi e file temporanei non stabili.

## Installazione rapida

Gli script creano/riusano un ambiente Python, installano dipendenze e il progetto in editable mode (`pip install -e .`).

### Linux

```bash
bash install_scripts/install_linux.sh
```

### Windows

```bat
install_scripts\install_windows.bat
```

Su Windows, se `conda` è disponibile viene usato l'ambiente `lab_materia_2`; altrimenti viene creato `.venv` locale.
