# Laboratorio di Fisica della Materia 2

Questa repo contiene tutte le risorse, i dati e il codice relativi al laboratorio di Fisica della Materia 2.

## Struttura repository

Di seguito è presentata la struttura delle cartelle del progetto e il loro contenuto:

```text
.
├── data/
│   ├── processed/
│   └── raw/
├── docs/
│   ├── notes/
│   ├── paper/
│   └── references/
├── interfaces/
├── src/
├── temp/
└── README.md
```

## Descrizione cartelle

- **data**: contiene tutti i dati raccolti.
  - **data/raw**: dati grezzi, direttamente dagli strumenti.
  - **data/processed**: dati elaborati, pronti per l'analisi.
- **docs**: contiene la documentazione e tutte le risorse raccolte durante il corso, come appunti, manuali e riferimenti bibliografici.
  - **notes**: appunti e note di laboratorio.
  - **references**: manuali, codice e risorse esterne utili per il corso.
  - **paper**: articoli scientifici e pubblicazioni rilevanti per il corso.
- **interfaces**: include le interfacce software sviluppate per la comunicazione con gli strumenti e la gestione degli esperimenti.
- **src**: contiene il codice sorgente, organizzato (o in fase di riorganizzazione) come pacchetto Python per l'analisi e l'automazione.
- **temp**: destinata a file temporanei, script di prova e materiale in corso di lavorazione.

## Cose da fare

- Riorganizzare il codice in `src` in un pacchetto Python ben strutturato, con moduli e classi per la gestione degli strumenti, l'analisi dei dati e l'automazione degli esperimenti.
- Documentare il codice con docstring e commenti per facilitare la comprensione e la manutenzione futura. Vorrei usare pdocs per generare una documentazione HTML a partire dalle docstring, in modo da avere una risorsa facilmente consultabile per chiunque voglia capire o contribuire al codice.
- Popolare le cartelle `data` e `docs` con i dati raccolti e le risorse utili per il corso, mantenendo una buona organizzazione e chiarezza.
- La camera ha bisogno di un po' di lavoro sulle roi.
- Le interfacce devono essere riordinate, probabilmente creando una classe base per le finestre che usiamo.
- Un po' meno ai nel readme...

