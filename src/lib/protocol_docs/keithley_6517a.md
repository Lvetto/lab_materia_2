# Protocollo operativo Keithley 6517A

Classe `ElettrometroKeithley`: estensione SCPI dedicata al 6517A.

## Comandi principali usati

- `SYST:ZCH {state}` / `SYST:ZCH?` (zero check relay)
- `CONF:{FUNC}` (selezione misura, es. `CURR:DC`, `RES`)
- `FORM:ELEM READ,TST` (valore + timestamp)
- `SYST:TST:REL:RES` (reset timer relativo)
- `:SOUR:VOLT:LEV:IMM:AMPL {voltage}` (sorgente tensione)
- `OUTP:STAT {state}` (abilita output)
- `:SENS:{FUNC}:RANG:AUTO {state}` / `?` (autorange)
- `:SENS:{FUNC}:RANG:UPP {range}` (range manuale)
- `READ?` (acquisizione sample)

## Sequenza tipica nel codice

`init_current_reading()` esegue: reset -> zero check off -> config funzione -> formato output -> reset timer -> autorange -> sorgente 0.1 V -> output on.
