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

- Finire di documentare il codice aggiungendo i docstring. Seguite la struttura nella bilancia, che vorrei usare pdoc per generare la documentazione in modo automatico.
- Caricare tutto quello che abbiamo in docs (aggiunti i paper inviati dalla Prof)
- La camera ha bisogno di un po' di lavoro sulle roi.
- Le interfacce devono essere riordinate, probabilmente creando una classe base per le finestre che usiamo.
