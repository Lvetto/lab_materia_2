# Protocollo SCPI base

Classe `SCPIInstrument`: wrapper minimale per strumenti SCPI su seriale.

## Regole operative

- i comandi vengono inviati come testo ASCII;
- viene aggiunto automaticamente il terminatore (default `\r\n`);
- `query()` invia il comando e legge una riga di risposta (`readline`).

## Comandi comuni supportati

- `*IDN?` (identify)
- `*RST` (reset)
- `*CLS` (clear status)
- `*OPC` (operation complete)
