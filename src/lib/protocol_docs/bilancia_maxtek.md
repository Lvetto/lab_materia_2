# Protocollo bilancia Maxtek (seriale binario)

Protocollo frame-oriented su seriale, usato dalla classe `Bilancia`.

## Struttura messaggio

`Header(2) + Address(1) + InstrCode(1) + DataLen(1) + Data(N) + Checksum(1)`

- `Header`: `0xFF 0xFE`
- `DataLen`: lunghezza payload in byte
- `Checksum`: `255 - ((InstrCode + DataLen + Data) mod 256)`

## Comandi implementati

- `Remote activation` (`0x00`) con payload `start/stop/shutter`
- `Send monitor config` (`0x01`)
- `Send film parametes` (`0x02`)
- `Receive film parameters` (`0x03`)
- `Send monitor status` (`0x04`)
- `Config data-logging` (`0x05`)

## Data logging

`Config data-logging` usa 2 byte bitmask per selezionare i campi (rate/thickness/frequency sensori).
La decodifica del flusso continuo cerca l'header, estrae i chunk ASCII secondo `data_log_sizes` e salva valore + timestamp.
