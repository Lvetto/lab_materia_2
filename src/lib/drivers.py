"""Driver hardware per microbilancia, camera e elettrometro.

Il modulo implementa:
1. protocollo seriale Maxtek per microbilancia al quarzo;
2. acquisizione immagini con OpenCV e gestione ROI;
3. comandi SCPI per elettrometro Keithley 6517A.
"""

import serial
from serial.tools import list_ports
import time
import threading
from collections import deque
import cv2
import numpy as np
import platform
from pathlib import Path


_PROTOCOL_DOCS_DIR = Path(__file__).with_name("protocol_docs")


def _load_protocol_doc(filename: str) -> str:
    """Legge un documento Markdown da usare come docstring runtime.
        Serve per la documentazione.
        """
    return (_PROTOCOL_DOCS_DIR / filename).read_text(encoding="utf-8").strip()

class Bilancia:
    """
    Rappresenta una microbilancia maxtek, implementando il protocollo di comunicazione seriale per inviare comandi e ricevere dati.
    """

    Header = bytes([255, 254])
    """
    Header fisso, identifica l'inizio di un messaggio valido inviato o ricevuto
    """

    comandi = {
        "Remote activation" : bytes([0]),
        "Send monitor config" : bytes([1]),
        "Send film parametes" : bytes([2]),
        "Receive film parameters" : bytes([3]),
        "Send monitor status" : bytes([4]),
        "Config data-logging" : bytes([5]),
    }
    """
    comandi supportati con i loro codici istruzione
    """

    remote_activation_data = {
    "start" : bytes([1]),
    "stop" : bytes([2]),
    "shutter" : bytes([4]),
    }
    """
    le opzioni valide per il comando "Remote activation" e i loro codici, usati per costruire il messaggio da inviare alla bilancia
    """
    
    config_data_logging_data = [
    # byte 1
    ["Displayed rate", "Displayed thickness", "Displayed frequency", "Sensor 1 rate", "Sensor 1 thickness", "Sensor 1 frequency", "Sensor 2 rate", "Sensor 2 thickness"],
    # byte 2
    ["Sensor 2 frequency", "Active sensor number"]
    ]
    """
    Cofig data logging richiede due byte di dati, in cui ogni bit=1 rappresenta un valore restituito dalla bilancia quando il data logging è attivo.
    Questi sono i nomi dei valori con la loro posizione nei due byte
    """
    
    # dimensioni in byte dei dati loggati per ogni voce (per la decodifica)
    data_log_sizes = {
        "Displayed rate": 5,
        "Displayed thickness": 5,
        "Displayed frequency": 11,
        "Sensor 1 rate": 5,
        "Sensor 1 thickness": 5,
        "Sensor 1 frequency": 11,
        "Sensor 2 rate": 5,
        "Sensor 2 thickness": 5,
        "Sensor 2 frequency": 11,
        "Active sensor number": 1
    }
    """
    dimensioni in byte dei valori restituiti dalla bilancia
    """

    def __init__(self, porta, baudrate=9600, dev_addr=1):
        """
        Inizializza la microbilancia.

        Args:
            porta (str): La porta seriale a cui è connessa la microbilancia.
            baudrate (int, optional): Il baudrate della comunicazione seriale. Defaults to 9600.
            dev_addr (int, optional): L'indirizzo del dispositivo. Defaults to 1.
        """

        # permette di inizializzare un oggetto Bilancia senza una porta seriale, utile per testare la logica senza hardware
        if porta is not None:
            self.ser = serial.Serial(porta, baudrate, timeout=1)
        else:
            self.ser = None

        # l'indirizzo del dispositivo, quasi sempre 1, ma è meglio renderlo configurabile
        self.dev_addr = bytes([dev_addr])

        # thread e flag per la lettura continua dei dati
        self.read_thread = None
        self.reading = False

        self.decode_thread = None
        self.decoding = False

        self.lock = threading.Lock()

        # buffer per i dati letti e i loro timestamp, usati nella lettura continua
        self.read_buffer = deque()
        self.timestamps = deque()

        # buffer per i dati grezzi letti dal seriale, prima della decodifica, e i loro timestamp
        self._raw_read_buffer = deque()
        self._raw_timestamps = deque()

    # -- costruzione del messaggio secondo il protocollo della bilancia --

    def _data_len(self, data):
        """
        Calcola la lunghezza dei dati. Usato nella costruzione del messaggio da inviare alla bilancia.

        Args:
            data (bytes): Payload da includere nel messaggio.

        Returns:
            bytes: La lunghezza dei dati in formato byte.
        """
        return len(data).to_bytes(1, byteorder='little')
    
    def _checksum(self, instr_code, data):
        """
        Calcola il checksum per un messaggio, basato sul codice di istruzione e sui dati.
        Il checksum è il complemento a 1 della somma di tutti i byte del messaggio (escluso l'Header), modulo 256.
        
        Args:
            instr_code (bytes): Il codice di istruzione del messaggio.
            data (bytes): I dati del messaggio.

        Returns:
            bytes: Il checksum calcolato in formato byte.

        """

        lenght = self._data_len(data)

        # il checksum è calcolato su instr_code + lenght + data, escludendo l'Header e l'indirizzo
        checksum = 255 - (sum(instr_code + lenght + data) % 256)

        return checksum.to_bytes(1, byteorder='little') 
    
    def _build_message(self, comando, data=None):
        """
        Costruisce un messaggio da inviare alla bilancia, basato sul comando e sui dati forniti.

        Args:
            comando (str): Il comando da inviare, deve essere una chiave presente in self.comandi.
            data (varia, optional): I dati associati al comando, se richiesti. La forma e il contenuto dei dati dipendono dal comando specifico.
        
        Returns:
            bytes: Il messaggio completo da inviare alla bilancia, in formato byte.
        """

        # ogni istruzione ha un codice specifico, che è definito in self.comandi. Se il comando non è riconosciuto, solleva un errore.
        instr_code = self.comandi[comando]

        # alcuni comandi hanno argomenti specifici che devono essere codificati in un certo modo. Qui gestiamo la codifica dei dati in base al comando.
        if data is not None:
            # remote activation ha un byte di dati che dipende dall'azione (start, stop, shutter)
            if comando == "Remote activation":
                data_encoded = self.remote_activation_data[data]
            
            # data-logging ha due byte di dati che rappresentano una configurazione di quali parametri loggare, codificati come bit in due byte
            elif comando == "Config data-logging":

                byte1 = 0
                byte2 = 0

                for item in self.config_data_logging_data[0]:
                    if item in data:
                        byte1 |= (1 << self.config_data_logging_data[0].index(item))

                for item in self.config_data_logging_data[1]:
                    if item in data:
                        byte2 |= (1 << self.config_data_logging_data[1].index(item))

                data_encoded = bytes([byte1, byte2])

            else:
                raise ValueError("Comando non supportato o dati non validi")
        else:
            # se il comando non richiede dati, usiamo un payload vuoto
            data_encoded = bytes()
        
        # componiamo e restituiamo il messaggio completo, che include l'Header, l'indirizzo del dispositivo, il codice di istruzione, la lunghezza dei dati, i dati stessi e il checksum
        encoded_command = self.Header + self.dev_addr + instr_code + self._data_len(data_encoded) + data_encoded + self._checksum(instr_code, data_encoded)
        return encoded_command

    def send_command(self, comando, data=None):
        """Invia un comando alla bilancia e legge il pacchetto di stato.

        Args:
            comando (str): Nome comando supportato da ``self.comandi``.
            data (object | None): Payload associato al comando.

        Returns:
            dict | None: Risposta decodificata di stato, oppure ``None`` se la
            risposta non e disponibile o incompleta.
        """
        if self.ser is None:
            print("Comando inviato a dispositivo dummy:", comando, data)
            return
        
        self.ser.reset_input_buffer()
        message = self._build_message(comando, data)
        self.ser.write(message)

        response = self.ser.read(8) 

        if len(response) == 8:
            return self._decode_message(response)
        else:
            print("Errore: Risposta non ricevuta o parziale dal dispositivo.")
            return None
 
    # -- decodifica dei messaggi ricevuti dalla bilancia --

    def _decode_message(self, message):
        """
        Decodifica un messaggio di risposta dalla bilancia, estraendo le informazioni chiave come l'indirizzo, il codice di istruzione, la lunghezza dei dati, i dati stessi e il checksum ricevuto.

        Args:
            message (bytes): Il messaggio di risposta da decodificare.

        Returns:
            dict: Un dizionario contenente le informazioni estratte dal messaggio.
        """

        if len(message) < 8 or message[3] != 253:
            return None # Non è un messaggio di status valido

        return {
            "header": message[0:2],
            "address": message[2],
            "status_instr_code": message[3], # Sarà sempre 253
            "data_length": message[4],       # Sarà sempre 2
            "sent_instr_code": message[5],   # Il comando inviato
            "receive_code": message[6],      # 0 = OK, 1 = Error, ecc.
            "received_checksum": message[7]
        }
    
    def _decode_ascii_data(self, data, sizes):
        """
        Decodifica un messaggio di dati ASCII diviso in parti di dimensioni specificate, restituendo una lista di stringhe decodificate e pulite da spazi bianchi.

        Args:
            data (bytes): Il messaggio di dati ASCII da decodificare.
            sizes (list of int): Una lista delle dimensioni per ogni parte del messaggio.

        Returns:
            list of str: Una lista di stringhe decodificate e pulite da spazi bianchi.
        """

        split_message = []

        # divide un messaggio di dati ASCII in base alle dimensioni specificate per ogni voce, decodifica ogni parte e la aggiunge alla lista dei risultati. Restituisce una lista di stringhe decodificate e pulite da spazi bianchi.
        idx = 0
        for size in sizes:
            split_message.append(data[idx:idx+size].decode('ascii').strip())
            idx += size

        return split_message

    def _decode_binary_data(self, data, types, sizes):
        """
        Decodifica un messaggio di dati binari, restituendo una lista di interi rappresentati dai byte del messaggio.

        Non è testata e supporta decodifica solo di interi e stringhe ASCII.

        Args:
            data (bytes): Il messaggio di dati binari da decodificare.
            types (list of type): Una lista dei tipi di dati da decodificare.
            sizes (list of int): Una lista delle dimensioni per ogni parte del messaggio.

        Returns:
            list: Una lista di valori decodificati, il cui tipo dipende dai tipi specificati.
        """

        decoded_values = []

        # decodifica un messaggio di dati binari, interpretando i byte del messaggio come valori interi o float a seconda dei tipi specificati. Restituisce una lista di valori decodificati.
        idx = 0
        for t, size in zip(types, sizes):

            bits = data[idx:idx+size]
            idx += size

            if t == int:
                value = int.from_bytes(bits, byteorder='little')
 
            elif t == str:
                value = bits.decode('ascii').strip()

            else:
                raise ValueError("Tipo di dato non supportato per la decodifica")



        return decoded_values

    # -- lettura dei dati loggati dalla bilancia --
 
    def _read_from_buffer(self, num_bytes):
        """
        Legge un certo numero di byte dal buffer seriale, se disponibili. Se non ci sono abbastanza byte disponibili, restituisce None.

        Args:
            num_bytes (int): Il numero di byte da leggere.

        Returns:
            bytes or None: I byte letti dal buffer seriale, o None se non ci sono abbastanza byte disponibili.
        """

        # leggiamo solo se ci sono abbastanza byte disponibili nel buffer seriale, altrimenti restituiamo None per indicare che non abbiamo dati completi da leggere
        if self.ser.in_waiting >= num_bytes:
            message = self.ser.read(num_bytes)
            return message
        return None
    
    def _continuous_read(self, data, interval=0.01):
        """
        Legge continuamente i dati dal buffer seriale, separando i byte e associando un timestamp a ciascuno, e li aggiunge a un buffer interno di lettura.
        Questo metodo viene eseguito in un thread separato per permettere la lettura continua senza bloccare il thread principale.

        Args:
            data (list of str): I dati per la configurazione del data-logging, usati per eseguire l'handshake iniziale e assicurarsi che la bilancia stia inviando i dati desiderati.
            interval (float, optional): L'intervallo di tempo tra ogni lettura. Defaults to 0.01.
        """

        # leggiamo l'intero buffer setiale e lo aggiungiamo al buffer interno di lettura, con il timestamp associato
        while self.reading:
            val = self.ser.read_all()
            if val:
                with self.lock:
                    # separiamo i byte
                    for byte in val:
                        self._raw_read_buffer.append(byte)
                        self._raw_timestamps.append(time.time())
            
            time.sleep(interval)
 
    def start_continuous_read(self, data=["Displayed rate", "Displayed thickness"]):
        """Avvia lettura e decodifica continue in thread separati.

        Args:
            data (list[str]): Campi da richiedere nel data-logging.
        """
        if self.read_thread is None or not self.read_thread.is_alive():

            self.send_command("Config data-logging", data)
    
            self.read_thread = threading.Thread(target=self._continuous_read, args=(data,))
            self.read_thread.daemon = True
            self.reading = True
            self.read_thread.start()

        if self.decode_thread is None or not self.decode_thread.is_alive():
            sizes = [self.data_log_sizes[item] for item in data]
            self.decode_thread = threading.Thread(target=self._decode_thread, args=(sizes,))
            self.decode_thread.daemon = True
            self.decoding = True
            self.decode_thread.start()

    def stop_continuous_read(self):
        """Ferma thread di lettura/decodifica e chiude il data-logging."""
        self.reading = False
        self.send_command("Config data-logging", [])
        if self.read_thread is not None:
            self.read_thread.join()
        self.decoding = False
        if self.decode_thread is not None:
            self.decode_thread.join()

    def _handshake_data_logging(self, data):
        """
        Esegue un handshake per la configurazione del data-logging, inviando prima un comando di configurazione vuoto per resettare eventuali configurazioni precedenti, pulendo il buffer di lettura e poi inviando il comando con i dati desiderati.

        Args:
            data (list of str): I dati per la configurazione del data-logging.
        """

        self.send_command("Config data-logging", [])

        time.sleep(0.1)

        self.read_buffer.clear()
        self.timestamps.clear()
        self.ser.reset_input_buffer()

        time.sleep(0.1)

        self.send_command("Config data-logging", data)


    # -- decodifica dei dati grezzi letti dal buffer seriale --

    def _decode_raw_buffer(self, sizes):
        """
        Decodifica i dati grezzi letti dal buffer seriale, cercando l'Header, estraendo i byte di indirizzo, codice di istruzione, lunghezza dei dati e i dati stessi, decodificando i dati in stringhe ASCII e aggiungendoli al buffer di lettura decodificato con il timestamp associato.

        Args:
            sizes (list of int): Le dimensioni dei chunk di dati da decodificare.
        """
        while len(self._raw_read_buffer) >= sum(sizes) + 2 + 3 + 1: # Header (2) + address+instr_code+data_length (3) + data + checksum (1)

            # Controlla se i primi 2 byte sono l'Header
            if self._raw_read_buffer[0] == 255 and self._raw_read_buffer[1] == 254:
                # Rimuovi l'Header e i loro timestamp
                self._raw_read_buffer.popleft()  # Rimuove 255
                self._raw_read_buffer.popleft()  # Rimuove 254

                self._raw_timestamps.popleft()  # Rimuove timestamp di 255
                self._raw_timestamps.popleft()  # Rimuove timestamp di 254

                # Rimuovi i byte di indirizzo, instr_code e data_length +  i timestamp associati (3 byte)
                for _ in range(3):
                    self._raw_read_buffer.popleft()
                    self._raw_timestamps.popleft()

                # Ora estrai i dati basati sui sizes specificati
                data_bytes = []
                for size in sizes:
                    chunk = bytes([self._raw_read_buffer.popleft() for _ in range(size)])
                    data_bytes.append(chunk)

                # Decodifica i dati e aggiungili al buffer di lettura
                decoded_data = [chunk.decode('ascii').strip() for chunk in data_bytes]
                self.read_buffer.append(decoded_data)
                self.timestamps.append(self._raw_timestamps.popleft())
            else:
                # Se non trovi l'Header, rimuovi il primo byte e continua a cercare
                self._raw_read_buffer.popleft()
                self._raw_timestamps.popleft()

    def _decode_thread(self, sizes):
        """
        Esegue la decodifica dei dati grezzi in un thread separato, chiamando continuamente il metodo _decode_raw_buffer per processare i dati letti dal buffer seriale.

        Args:
            sizes (list of int): Le dimensioni dei chunk di dati da decodificare.
        """
        while self.decoding:
            with self.lock:
                self._decode_raw_buffer(sizes)
            time.sleep(0.05)

    #-- metodi per accedere ai dati decodificati --

    def get_latest_data(self):
        """
        Legge l'ultimo dato decodificato dal buffer di lettura, restituendo sia il dato
        che il timestamp associato. Se non ci sono dati disponibili, restituisce None.
        
        Returns:
            tuple or None: Una tupla contenente il dato decodificato e il suo timestamp, o None se non ci sono dati disponibili.
        """
        
        if self.read_buffer: 
            with self.lock:
                return self.read_buffer.popleft(), self.timestamps.popleft()
        else:
            return None

    def get_data(self):
        """
        Legge dal buffer una lista di dati e timestamps per poi svuotarli

        Returns:
            lista di float (?): rate, spessore e timestamp associato
        """
        
        data = list(self.read_buffer)
        timestamps = list(self.timestamps)

        self.read_buffer.clear()
        self.timestamps.clear()

        return data, timestamps

    # -- chiusura della connessione seriale --

    def close(self):
        """Chiude in modo sicuro lettura continua e porta seriale."""
        self.stop_continuous_read()
        if self.ser is not None and self.ser.is_open:
            self.ser.close()

    def __del__(self):
        """Assicura la chiusura della porta seriale alla distruzione dell'oggetto."""
        self.close()

class DummyBilancia(Bilancia):
    """Versione dummy della Bilancia Maxtek per test senza hardware."""

    def __init__(self, samples=None, dev_addr=1):
        super().__init__(porta=None, baudrate=9600, dev_addr=dev_addr)
        self._dummy_samples = list(samples) if samples is not None else [[0.0, 0.0]]
        self._dummy_sample_idx = 0
        self._dummy_active_fields = ["Displayed rate", "Displayed thickness"]
        self._dummy_remote_state = "stop"

    def set_dummy_samples(self, samples):
        """Aggiorna la sequenza di campioni usata nelle letture dummy."""
        self._dummy_samples = list(samples)
        self._dummy_sample_idx = 0

    def _normalize_dummy_sample(self, sample, fields):

        if isinstance(sample, dict):
            values = [sample.get(name, 0.0) for name in fields]

        elif isinstance(sample, (tuple, list)):
            if len(sample) >= len(fields):
                values = list(sample[:len(fields)])
            else:
                values = list(sample) + [0.0] * (len(fields) - len(sample))
        else:
            values = [sample] + [0.0] * (len(fields) - 1)

        return [str(val).strip() for val in values]

    def _next_dummy_reading(self, fields):
        if not self._dummy_samples:
            reading = ["0.0" for _ in fields]
        else:
            sample = self._dummy_samples[self._dummy_sample_idx % len(self._dummy_samples)]
            self._dummy_sample_idx += 1
            reading = self._normalize_dummy_sample(sample, fields)

        return reading, time.time()

    def send_command(self, comando, data=None):
        if comando == "Remote activation":
            self._dummy_remote_state = data if data is not None else "stop"
        elif comando == "Config data-logging":
            self._dummy_active_fields = list(data) if data else []

        instr_code = self.comandi.get(comando, bytes([0]))
        return {
            "header": self.Header,
            "address": self.dev_addr[0],
            "status_instr_code": 253,
            "data_length": 2,
            "sent_instr_code": instr_code[0],
            "receive_code": 0,
            "received_checksum": 0,
        }

    def _continuous_read(self, data, interval=0.01):
        while self.reading:
            values, ts = self._next_dummy_reading(data)
            with self.lock:
                self.read_buffer.append(values)
                self.timestamps.append(ts)
            time.sleep(interval)

    def start_continuous_read(self, data=["Displayed rate", "Displayed thickness"], interval=0.01):
        if self.read_thread is None or not self.read_thread.is_alive():
            self.send_command("Config data-logging", data)
            self.reading = True
            self.read_thread = threading.Thread(target=self._continuous_read, args=(data, interval))
            self.read_thread.daemon = True
            self.read_thread.start()

        self.decoding = False

    def stop_continuous_read(self):
        self.reading = False
        self.send_command("Config data-logging", [])
        if self.read_thread is not None:
            self.read_thread.join()
        self.decoding = False

    def _handshake_data_logging(self, data):
        self.read_buffer.clear()
        self.timestamps.clear()
        self.send_command("Config data-logging", data)

    def read_single(self, data=["Displayed rate", "Displayed thickness"], index=None):
        """Simula una singola lettura e restituisce ``(valori, timestamp)``."""
        if index is not None and self._dummy_samples:
            self._dummy_sample_idx = index % len(self._dummy_samples)
        return self._next_dummy_reading(data)


class SCPIInstrument:
    """
        Generico strumento con protocollo SCPI.
        Implementa le basi per la comunicazione secondo il protocollo e alcuni comandi comuni.
    """

    commands = {
        "identify": "*IDN?",
        "reset": "*RST",
        "clear": "*CLS",
        "operation_complete" : "*OPC"
    }
    
    def __init__(self, port, baudrate=9600, timeout=2, terminator='\r\n'):
        """Inizializza connessione seriale SCPI.

        Args:
            port (str): Porta seriale strumento.
            baudrate (int): Baudrate seriale.
            timeout (float): Timeout lettura/scrittura seriale in secondi.
            terminator (str): Terminatore comandi SCPI.
        """

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.terminator = terminator
        
        # permette inizializzazione senza porta seriale (modalita dummy)
        if self.port is not None:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.reset_buffers()
        else:
            self.serial = None

    def reset_buffers(self):
        """Reset internal buffers"""
        if self.serial is None:
            return
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def send_command(self, command):
        """Sends a raw SCPI command (automatically appends the terminator)."""
        if self.serial is None:
            print("Comando SCPI inviato a dispositivo dummy:", command)
            return
        complete_command = f"{command}{self.terminator}"
        self.serial.write(complete_command.encode('ascii'))
        time.sleep(0.1)  # breve pausa per assicurarsi che il comando sia inviato prima di procedere

    def query(self, command, delay=0.1):
        """Sends a query and reads the instrument's response."""
        if self.serial is None:
            print("Query SCPI inviata a dispositivo dummy:", command)
            return ""
        self.send_command(command)
        time.sleep(delay)
        response = self.serial.readline().decode('ascii', errors='ignore').strip()
        #response = self.sio.readline()
        # con readline(), dopo la lettura di una misura, il buffer del pc la elimina (non usiamo il buffer del keithley grazie alla funzione READ?)
        
        #print(f"Query: {command} -> Response: {response.strip()}")

        # decode and clean up the response
        return response#response.decode('ascii', errors='ignore').strip()

    def identify(self):
        """Sends a universal SCPI command to identify the instrument."""
        return self.query(command=self.commands["identify"])

    def reset(self):
        """Sends a universal SCPI command to reset the instrument to factory defaults."""
        self.send_command(self.commands["reset"])
        self.send_command(self.commands["clear"])
        self.send_command(self.commands["operation_complete"])

    def close(self):
        """Sends a command to close the communication cleanly."""
        if self.serial is not None and self.serial.is_open:
            self.serial.close()

class ElettrometroKeithley(SCPIInstrument):
    """Implementation for the Keithley 6517A."""

    commands = {
        # attiva o disattiva lo zero check
        "zero_check_on": "SYST:ZCH {state}",
        "query_zero_check" : "SYST:ZCH?",

        # configura la funzione di lettura (es. CURR:DC, RES, VOLT:DC)
        "configure_reading": "CONF:{FUNC}",

        # configura il formato degli elementi restituiti nelle letture (es. solo valore e timestamp, senza unità)
        "format_elements": "FORM:ELEM {FORMAT}",

        # azzera il timer interno del Keithley, utile per avere un riferimento temporale nelle letture
        "reset_time": "SYST:TST:REL:RES",

        # specifica la tensione di sourcing del Keithley e attiva l'output
        "specify_voltage": ":SOUR:VOLT:LEV:IMM:AMPL {voltage}",
        "enable_output": "OUTP:STAT {state}",

        # gestisce l'autorange e il range manuale
        "set_current_range": ":SENS:{FUNC}:RANG:UPP {range}",
        "query_autorange": ":SENS:{FUNC}:RANG:AUTO?",
        "set_autorange": ":SENS:{FUNC}:RANG:AUTO {state}"    
        
    }
    """
    comandi specifici per il Keithley 6517A, che si aggiungono a quelli generici definiti nella classe base SCPIInstrument.
    Questi comandi permettono di configurare e interrogare le funzionalità specifiche dell'elettrometro, come lo zero check,
    la configurazione della lettura, il formato dei dati restituiti, la gestione del timer interno,
    la specifica della tensione di sourcing e la gestione dell'autorange per le misure di corrente o resistenza.
    """
    
    def __init__(self, port, baudrate=9600, timeout=2):
        """Inizializza driver Keithley e buffer di lettura continua.

        Args:
            port (str): Porta seriale strumento.
            baudrate (int): Baudrate seriale.
            timeout (float): Timeout operazioni seriali.
        """
        # create a serial connection with the correct terminator for the Keithley (typically \r\n)
        super().__init__(port, baudrate, timeout, terminator='\r\n')

        # combine the base class commands with the Keithley-specific commands
        self.commands = {**SCPIInstrument.commands, **self.__class__.commands}
        
        self.read_buffer = deque()
        self.time_buffer = deque()
        self.read_thread = None
        self.reading = False

        self.reading_func = None
    
    def _build_command(self, command, args):
        """Costruisce una stringa SCPI formattando il template comando.

        Args:
            command (str): Chiave comando in ``self.commands``.
            args (dict[str, object]): Parametri di sostituzione del template.

        Returns:
            str: Comando SCPI pronto da inviare.
        """
        completed_command = self.commands[command].format(**args)
        return completed_command

    # -- metodi per i comandi specifici del Keithley 6517A --

    def set_zero_check(self, state: bool):
        """Attiva (True) o disattiva (False) lo Zero Check."""
        cmd = self._build_command("zero_check_on", {"state": int(state)})
        self.send_command(cmd)

    def set_source_voltage (self, voltage):
        """Imposta la tensione della sorgente del Keithley.

        Args:
            voltage (float): Tensione target in volt.
        """
        command = self._build_command("specify_voltage", {"voltage": voltage})
        self.send_command(command)

    def set_output(self, state: bool):
        """Abilita (True) o disabilita (False) l'output del Keithley."""
        cmd = self._build_command("enable_output", {"state": int(state)})
        self.send_command(cmd)
   
    def set_autorange(self, func="CURR:DC", state=True):
        """Abilita (True) o disabilita (False) l'autorange per la funzione di misura specificata."""
        cmd = self._build_command("set_autorange", {"FUNC": func, "state": int(state)})
        self.send_command(cmd)
    
    def set_manual_range(self, func="CURR:DC", range_val=1e-6):
        """Imposta manualmente il range di misura per la funzione specificata (es. 1e-6 A per la corrente)."""
        cmd = self._build_command("set_current_range", {"FUNC": func, "range": range_val})
        self.send_command(cmd)

    def set_format_elements(self, format_str="READ,TST"):
        """Configura il formato degli elementi restituiti nelle letture (es. solo valore e timestamp, senza unità)."""
        cmd = self._build_command("format_elements", {"FORMAT": format_str})
        self.send_command(cmd)

    def reset_time(self):
        """Azzera il timer interno del Keithley, utile per avere un riferimento temporale nelle letture."""
        self.send_command(self.commands["reset_time"])

    # -- metodi per leggere dati --

    def query_zero_check(self):
        """Restituisce lo stato attuale dello Zero Check (1 per attivo, 0 per inattivo)."""
        response = self.query(self.commands["query_zero_check"])
        try:
            return int(response)
        except ValueError:
            print(f"Errore nella conversione della risposta dello Zero Check: '{response}'")
            return None
    
    def query_autorange(self, func="CURR:DC"):
        """Restituisce lo stato attuale dell'autorange per la funzione specificata (1 per attivo, 0 per inattivo)."""
        cmd = self._build_command("query_autorange", {"FUNC": func})
        response = self.query(cmd)
        try:
            return int(response)
        except ValueError:
            print(f"Errore nella conversione della risposta dell'autorange: '{response}'")
            return None
    
    def query_source_voltage(self):
        """Restituisce il livello di tensione attualmente impostato per la sorgente."""
        cmd = self._build_command("specify_voltage", {"voltage": ""})[:-1] + "?"
        response = self.query(cmd)
        try:
            return float(response)
        except ValueError:
            print(f"Errore nella conversione della risposta del livello di tensione: '{response}'")
            return None

    def read(self):
        """Invia READ? e restituisce la stringa grezza"""
        return self.query("READ?") #query usa readline()

    # -- metodi per interpretare i dati --

    def strip_units(self, value_str):
        """
        Rimuove caratteri alfabetici da una stringa di misura.

            (Nora: meglio non usarla, perchè non è testata)

        Args:
            value_str (str): Valore raw eventualmente contenente unita.

        Returns:
            str: Stringa ripulita da lettere e spazi laterali.
        """
        alphabet = list("abcdefghijklmnopqrstuvwxyzABCDFGHIJKLMNOPQRSTUVWXYZ")
        for char in alphabet:
            value_str = value_str.replace(char, '')
        return value_str.strip()
    
    def parse_reading(self, raw_value, types, units=False):
        """Funzione di utility per pulire i dati."""
        try:
            raw_value = raw_value.strip()
            parts = raw_value.split(',')

            if len(parts) != len(types):
                raise ValueError(f"Numero di parti nella lettura ({len(parts)}) non corrisponde al numero di tipi attesi ({len(types)}). Lettura: '{raw_value}'")
            
            parsed_values = []
            for part, typ in zip(parts, types):

                if units:
                    clean_part = self.strip_units(part)
                else:
                    clean_part = part

                parsed_values.append(typ(clean_part))

            return tuple(parsed_values)
        
        except (ValueError, IndexError) as e:
            print(f"Errore nella conversione della lettura: '{raw_value}'. Dettagli: {e}")
            return None

    # -- inizializza lo strumento per leggere una grandezza e i tempi di acquisizione, senza unità di misura --

    def configure_reading(self, func="CURR:DC"):
        """Configura la funzione di misura del Keithley (es. corrente DC o resistenza)"""
        cmd = self._build_command("configure_reading", {"FUNC": func})
        self.send_command(cmd)
        self.reading_func = func
 
    def init_current_reading(self, auto_range=True, output=True, source_voltage=0.1, reset=True): 
        """Set up the electrometer in a safe way to read currents."""
        
        if reset:
            self.reset()
        self.set_zero_check(True)
        self.configure_reading(func="CURR:DC")
        self.set_zero_check(False)
        self.set_format_elements()
        self.reset_time()
        self.set_autorange(func="CURR:DC", state=auto_range)
        self.set_source_voltage(source_voltage)
        self.set_output(output)

    def init_resistance_reading(self, auto_range=True, output=True, source_voltage=1.0, reset=True):
        """Set up the electrometer in a safe way to read resistances."""
        
        if reset:
            self.reset()
        self.set_zero_check(True)
        self.configure_reading(func="RES")
        self.set_zero_check(False)
        self.set_format_elements()
        self.reset_time()
        self.set_autorange(func="RES", state=auto_range)
        self.set_source_voltage(source_voltage)
        self.set_output(output)
    
    def init_voltage_reading(self, auto_range=True, output=True, reset=True):
        """Set up the electrometer in a safe way to read voltages."""
        
        if reset:
            self.reset()
        self.set_zero_check(True)
        self.configure_reading(func="VOLT:DC")
        self.set_zero_check(False)
        self.set_format_elements()
        self.reset_time()
        self.set_autorange(func="VOLT:DC", state=auto_range)
        self.set_output(output)

    # -- metodi per lettura continua in thread in background --

    def _continuous_read(self):
        """Loop di lettura continua che popola buffer valori e tempi."""
        
        while self.reading:
            raw = self.read()

            vals = self.parse_reading(raw, types=(float, float), units=False) # types è una tupla che specifica i tipi di dato attesi per ciascuna parte della lettura, in questo caso un float per il valore e un float per il timestamp
            times = vals[-1] if vals else time.time() # se la lettura è valida, prendi il timestamp restituito dal Keithley, altrimenti usa il timestamp corrente del PC

            self.read_buffer.append(vals[0]) # aggiungi i valori misurati al buffer di lettura
            self.time_buffer.append(times) # aggiungi i timestamp al buffer dei tempi

            time.sleep(0.1)

    def start_continuous_read(self):
        """Avvia il thread di lettura continua dal Keithley."""
        if self.read_thread is None or not self.read_thread.is_alive():
            self.reading = True
            self.read_thread = threading.Thread(target=self._continuous_read)
            self.read_thread.daemon = True
            self.read_thread.start()

    def stop_continuous_read(self):
        """Ferma la lettura continua e riporta lo strumento in stato sicuro."""
        self.reading = False

        if self.read_thread is not None:
            self.read_thread.join()
        
        self.set_output(False)
        self.set_zero_check(True)
    
    # -- chiusura pulita del driver --

    def close(self):
        """Chiude il driver interrompendo prima la lettura continua."""
        self.stop_continuous_read()
        super().close()

    def __del__(self):
        """Assicura la chiusura pulita del driver alla distruzione dell'istanza."""
        self.close()


class DummyElettrometroKeithley(ElettrometroKeithley):
    """Versione dummy del Keithley 6517A per test senza hardware."""

    def __init__(self, samples=None):
        super().__init__(port=None, baudrate=9600, timeout=0)

        self._dummy_zero_check = True
        self._dummy_output = False
        self._dummy_source_voltage = 0.0
        self._dummy_autorange = {"CURR:DC": True, "RES": True, "VOLT:DC": True}
        self._dummy_manual_range = {}
        self._dummy_format = "READ,TST"

        self._dummy_t0 = time.time()
        self._dummy_samples = list(samples) if samples is not None else [1e-9]
        self._dummy_sample_idx = 0

    def set_dummy_samples(self, samples):
        """Aggiorna la sequenza di campioni usata da ``read()``."""
        self._dummy_samples = list(samples)
        self._dummy_sample_idx = 0

    def _next_dummy_sample(self):
        if not self._dummy_samples:
            return 0.0, time.time() - self._dummy_t0

        sample = self._dummy_samples[self._dummy_sample_idx % len(self._dummy_samples)]
        self._dummy_sample_idx += 1

        if isinstance(sample, str):
            parsed = self.parse_reading(sample, types=(float, float), units=False)
            if parsed is not None:
                return parsed
            return 0.0, time.time() - self._dummy_t0

        if isinstance(sample, (tuple, list)) and len(sample) >= 2:
            try:
                return float(sample[0]), float(sample[1])
            except (TypeError, ValueError):
                return 0.0, time.time() - self._dummy_t0

        try:
            return float(sample), time.time() - self._dummy_t0
        except (TypeError, ValueError):
            return 0.0, time.time() - self._dummy_t0

    def identify(self):
        return "KEITHLEY INSTRUMENTS INC.,MODEL 6517A,DUMMY,0.0"

    def reset(self):
        self._dummy_zero_check = True
        self._dummy_output = False
        self._dummy_source_voltage = 0.0
        self._dummy_autorange = {"CURR:DC": True, "RES": True, "VOLT:DC": True}
        self._dummy_manual_range.clear()
        self._dummy_format = "READ,TST"
        self._dummy_t0 = time.time()
        self._dummy_sample_idx = 0
        self.read_buffer.clear()
        self.time_buffer.clear()

    def set_zero_check(self, state: bool):
        self._dummy_zero_check = bool(state)

    def set_source_voltage(self, voltage):
        self._dummy_source_voltage = float(voltage)

    def set_output(self, state: bool):
        self._dummy_output = bool(state)

    def set_autorange(self, func="CURR:DC", state=True):
        self._dummy_autorange[func] = bool(state)

    def set_manual_range(self, func="CURR:DC", range_val=1e-6):
        self._dummy_manual_range[func] = float(range_val)

    def set_format_elements(self, format_str="READ,TST"):
        self._dummy_format = str(format_str)

    def reset_time(self):
        self._dummy_t0 = time.time()

    def query_zero_check(self):
        return int(self._dummy_zero_check)

    def query_autorange(self, func="CURR:DC"):
        return int(self._dummy_autorange.get(func, True))

    def query_source_voltage(self):
        return float(self._dummy_source_voltage)

    def configure_reading(self, func="CURR:DC"):
        self.reading_func = func

    def read(self):
        value, tst = self._next_dummy_sample()
        return f"{value},{tst}"

    def read_single(self):
        """Restituisce una singola lettura dummy come ``(valore, timestamp)``."""
        return self.parse_reading(self.read(), types=(float, float), units=False)

    def close(self):
        self.stop_continuous_read()

    def __del__(self):
        self.close()





class Camera:
    """Driver camera con acquisizione continua e gestione ROI circolare."""

    def __init__(self, camera_index=0, keep_frames=100): 
            """Inizializza camera, buffer frame e lock dei parametri auto.

            Args:
                camera_index (int): Indice dispositivo video OpenCV.
                keep_frames (int): Numero massimo di frame mantenuti in buffer.

            Raises:
                RuntimeError: Se la webcam non e apribile.
            """
            if platform.system() == 'Windows':
                self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) # DirectShow
            elif platform.system() == 'Linux':
                self.cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)  # Video4Linux2
            else:
                self.cap = cv2.VideoCapture(camera_index)

            self.im0 = None  
            self.masks = None  
            self.images = deque(maxlen=keep_frames)  
            self.timestamps = deque(maxlen=keep_frames)  

            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 
            self.capturing = False

            if not self.cap.isOpened():
                raise RuntimeError("Impossibile aprire la webcam.")

            self.lock_camera_after_auto()

    def set_auto_exposure(self, enabled: bool):
        """Imposta l'auto esposizione in base all'OS"""
        sys_os = platform.system()
        
        if sys_os == 'Windows':
            # In DirectShow: -8 o 1 per Auto, 0 o -1 per Manuale (dipende dalla cam)
            val = -8 if enabled else 0
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, val)
        elif sys_os == 'Linux':
            # In V4L2: 3 è Auto, 1 è Manuale
            val = 3 if enabled else 1
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, val)

    def lock_camera_after_auto(self, warmup_sec=3.0):
        """Esegue warmup in auto e poi blocca i parametri acquisiti.

        Args:
            warmup_sec (float, optional): Tempo di warmup in secondi.

        Returns:
            dict[str, float]: Snapshot dei principali parametri bloccati.
        """
        
        self.set_auto_exposure(True)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)

        print("Riscaldamento fotocamera (Auto mode)...")
        t0 = time.time()
        while time.time() - t0 < warmup_sec:
            ret, _ = self.cap.read()
            # ret è un valore booleano, indica se la cattura è andata a buon fine (vale True)
            # frame è l'immagine catturata sotto forma di matrice NumPy
            # la funzione read() restituisce la tupla (ret, frame)
            if not ret:
                break
            cv2.waitKey(10) # Da tempo al buffer di svuotarsi

        print("Blocco dei parametri...")
        self.set_auto_exposure(False)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

        locked = {
            "exposure": self.cap.get(cv2.CAP_PROP_EXPOSURE),
            "auto_exposure": self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
        }
        print(f"Stato attuale: {locked}")
        return locked

    def _build_roi_masks(self, im0, center_x, center_y, radius):
        """Costruisce le maschere booleane delle regioni di interesse.

        Args:
            im0 (np.ndarray): Immagine di riferimento.
            center_x (int): Coordinata x del centro ROI.
            center_y (int): Coordinata y del centro ROI.
            radius (int): Raggio ROI in pixel.

        Returns:
            dict[str, np.ndarray]: Maschere booleane (total, mid, in, q1-q4).
        """
        h, w = im0.shape[:2]
        Y, X = np.ogrid[:h, :w] #Y è una colonna che contiene tutti gli indici di riga, X è una riga che contiene tutti gli indici di colonna
        dist_from_center = np.sqrt((X - center_x)**2 + (Y - center_y)**2) # non è un numero, ma una matrice della stessa dimensione della reference_image pari a h x w
        
        masks = {
            'total': dist_from_center <= radius,
            'mid': dist_from_center <= (radius / 2),
            'in': dist_from_center <= (radius / 4),
            'q1': (dist_from_center <= radius) & (Y < center_y) & (X > center_x),
            'q2': (dist_from_center <= radius) & (Y < center_y) & (X < center_x),
            'q3': (dist_from_center <= radius) & (Y > center_y) & (X < center_x),
            'q4': (dist_from_center <= radius) & (Y > center_y) & (X > center_x)
        }
        
        return masks
    
    def update_roi(self, center_x, center_y, radius):
        """Aggiorna dinamicamente le maschere ROI durante l'acquisizione.

        Args:
            center_x (int): Nuova coordinata x centro ROI.
            center_y (int): Nuova coordinata y centro ROI.
            radius (int): Nuovo raggio ROI in pixel.
        """
        if self.im0 is not None:
            self.masks = self._build_roi_masks(self.im0, center_x, center_y, radius)
    
    def acquire_image(self):
        """Acquisisce un frame e lo converte in scala di grigi.

        Raises:
            RuntimeError: Se non e possibile leggere un frame dalla webcam.

        Returns:
            np.ndarray: Frame in scala di grigi.
        """
        ret, frame = self.cap.read() 
        
        if not ret:
            raise RuntimeError("Impossibile acquisire un frame dalla webcam.")
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else self.im0
        # if len(frame.shape) == 3 controlla se l'immagine ha 3 canali di colore

        return frame
    
    def _acquire_reference_image(self, avgs=16):
        """Acquisisce una reference image mediando piu frame consecutivi.

        Args:
            avgs (int, optional): Numero frame usati per la media.

        Returns:
            np.ndarray: Immagine di riferimento in scala di grigi.

        Raises:
            RuntimeError: Se non vengono acquisiti frame validi.
        """
        frames = []
        for _ in range(avgs):
            frame = self.acquire_image()
            frames.append(frame.astype(np.float32))
            time.sleep(0.1) # Breve pausa per dare tempo al sensore
            
        if not frames:
            raise RuntimeError("Acquisizione immagine di riferimento fallita.")
        
        # frames è una lista di 16 immagini 2D 
           
        self.im0 = np.mean(frames, axis=0).astype(np.uint8)
        # scegliendo axis=0 faccio la media su tutte le immagini, pixel per pixel
        
        # avg over the channels
        self.im0 = cv2.cvtColor(self.im0, cv2.COLOR_BGR2GRAY) if len(self.im0.shape) == 3 else self.im0
        
        return self.im0.astype(np.uint8)

    def _process_frame(self, im0, masks):
        """Acquisisce un frame e ne estrae la ROI mascherata.

        Args:
            im0 (np.ndarray): Immagine di riferimento.
            masks (dict[str, np.ndarray]): Maschere ROI booleane.

        Raises:
            ValueError: Se reference image o maschere non sono inizializzate.

        Returns:
            tuple[np.ndarray, np.ndarray]: Frame corrente e frame mascherato.
        """

        if im0 is None or not masks:
            raise ValueError("Immagine di riferimento e maschere ROI devono essere inizializzate prima di processare.")

        frame = self.acquire_image()
        
        roi = frame * masks['total']
        
        return frame, roi

    def _continuous_acquisition(self, interval=0.1):
        """Loop di acquisizione continua in background thread.

        Args:
            interval (float): Pausa tra frame consecutivi in secondi.
        """
        while self.capturing:
            try:
                frame, roi = self._process_frame(self.im0, self.masks)
                self.images.append((frame, roi))
                self.timestamps.append(time.time())

                if len(self.images) > self.images.maxlen:
                    self.images.popleft()
                    self.timestamps.popleft()

            except Exception as e:
                print(f"Errore durante l'acquisizione continua: {e}")
                continue

            time.sleep(interval)

    def start_acquisition(self, center_x, center_y, radius, interval=0.1):
        """Avvia acquisizione continua costruendo reference image e ROI.

        Args:
            center_x (int): Coordinata x del centro ROI.
            center_y (int): Coordinata y del centro ROI.
            radius (int): Raggio ROI in pixel.
            interval (float): Intervallo tra letture in secondi.
        """
        if self.capturing:
            print("Acquisizione già in corso.")
            return
        
        self._acquire_reference_image()
        self.masks = self._build_roi_masks(self.im0, center_x, center_y, radius)

        self.capturing = True
        self.acquisition_thread = threading.Thread(target=self._continuous_acquisition, args=(interval,))
        self.acquisition_thread.daemon = True
        self.acquisition_thread.start()
    
    def stop_acquisition(self):
        """Ferma il thread di acquisizione continua, se presente."""
        self.capturing = False
        if hasattr(self, 'acquisition_thread'):
            self.acquisition_thread.join()

    def set_camera_params(self, exposure=-5, wb_temp=3900):
        """Imposta manualmente esposizione e temperatura white balance.

        Args:
            exposure (float): Valore esposizione OpenCV.
            wb_temp (int): Temperatura bilanciamento bianco (Kelvin).
        """
        
        # disabilita esposizione automatica e bilancamento del bianco automatico 
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        self.cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb_temp)
    
    def get_latest_image(self):
        """Raccoglie il frame piu anziano e lo elimina dal buffer.

        Returns:
            tuple[tuple[np.ndarray, np.ndarray], float] | None: Coppia
            ``((frame, roi), timestamp)`` oppure ``None`` se il buffer e vuoto.
        """
        if self.images:
            return self.images.popleft(), self.timestamps.popleft()
        else:
            return None

    def release(self):
        """Rilascia la risorsa ``VideoCapture`` associata alla camera."""
        self.cap.release()

    def get_all_images(self):
        """Restituisce e svuota l'intero buffer frame+timestamp.

        Returns:
            tuple[list[tuple[np.ndarray, np.ndarray]], list[float]]: Frame
            acquisiti (con relativa ROI) e timestamp associati.
        """
        images = list(self.images)
        timestamps = list(self.timestamps)

        self.images.clear()
        self.timestamps.clear()

        return images, timestamps




# Collega documentazione protocollo esterna alle classi (visibile in pdoc).
Bilancia.__doc__ = _load_protocol_doc("bilancia_maxtek.md")
SCPIInstrument.__doc__ = _load_protocol_doc("scpi_base.md")
ElettrometroKeithley.__doc__ = _load_protocol_doc("keithley_6517a.md")
