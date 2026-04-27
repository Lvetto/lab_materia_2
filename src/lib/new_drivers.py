import serial
from serial.tools import list_ports
import time
import threading
from collections import deque
import cv2
import numpy as np
import platform

class Bilancia:
    """
    Rappresenta una microbilancia maxtek, implementando il protocollo di comunicazione seriale per inviare comandi e ricevere dati.
    """

    # Il protocollo prevede un messaggio con Header (2 byte), Address (1 byte), Instruction Code (1 byte), Data Length (1 byte), Data (variabile) e Checksum (1 byte).
    Header = bytes([255, 254])

    # I comandi supportati e i loro codici di istruzione
    comandi = {
        "Remote activation" : bytes([0]),
        "Send monitor config" : bytes([1]),
        "Send film parametes" : bytes([2]),
        "Receive film parameters" : bytes([3]),
        "Send monitor status" : bytes([4]),
        "Config data-logging" : bytes([5]),
    }

    # I dati per il comando "Remote activation" e i loro codici
    remote_activation_data = {
    "start" : bytes([1]),
    "stop" : bytes([2]),
    "shutter" : bytes([4]),
    }
    
    # I dati per il comando "Config data-logging" e la loro posizione nei byte di configurazione
    config_data_logging_data = [
    # byte 1
    ["Displayed rate", "Displayed thickness", "Displayed frequency", "Sensor 1 rate", "Sensor 1 thickness", "Sensor 1 frequency", "Sensor 2 rate", "Sensor 2 thickness"],
    # byte 2
    ["Sensor 2 frequency", "Active sensor number"]
    ]
    
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

    def _data_len(self, data):
        """
        Calcola la lunghezza dei dati. Usato nella costruzione del messaggio da inviare alla bilancia.

        Args:
            data (_type_): I dati per cui calcolare la lunghezza.

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

    def _dummy_continuous_read(self, data, chunk_size=16, iterations=100):
        """
        Simula la lettura continua di dati, prendendo chunk di dati da una lista predefinita e aggiungendoli al buffer interno di lettura con un timestamp associato, per testare la logica di decodifica senza hardware reale.

        Args:
            data (list of bytes): I dati da simulare.
            chunk_size (int, optional): La dimensione di ciascun chunk di dati. Defaults to 16.
            iterations (int, optional): Il numero di iterazioni da eseguire. Defaults to 100.
        """
        i = 0
        while self.reading and i < iterations * chunk_size:
            val = data[i:i+chunk_size]  # Simula la lettura di chunk di dati
            i = (i + chunk_size) % len(data)  # Loop attraverso i dati
            with self.lock:
                if val:
                    for byte in val:
                        self._raw_read_buffer.append(byte)
                        self._raw_timestamps.append(time.time())
            time.sleep(0.01)
    
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

    def send_command(self, comando, data=None):
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
 
    def start_continuous_read(self, data=["Displayed rate", "Displayed thickness"]):
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
    
    def dummy_start_continuous_read(self, data, data_name=["Displayed rate", "Displayed thickness"], chunk_size=16, iterations=100):
        if self.read_thread is None or not self.read_thread.is_alive():
            
            self.send_command("Config data-logging", data_name)

            self.read_thread = threading.Thread(target=self._dummy_continuous_read, args=(data, chunk_size, iterations))
            self.read_thread.daemon = True
            self.reading = True
            self.read_thread.start()

        if self.decode_thread is None or not self.decode_thread.is_alive():
            sizes = [self.data_log_sizes[item] for item in data_name]
            self.decode_thread = threading.Thread(target=self._decode_thread, args=(sizes,))
            self.decode_thread.daemon = True
            self.decoding = True
            self.decode_thread.start()
    
    def stop_continuous_read(self):
        self.reading = False
        self.send_command("Config data-logging", [])
        if self.read_thread is not None:
            self.read_thread.join()
        self.decoding = False
        if self.decode_thread is not None:
            self.decode_thread.join()

    def close(self):
        self.stop_continuous_read()
        if self.ser.is_open:
            self.ser.close()

class Bilancia2(Bilancia):
    def __init__(self, porta, baudrate=9600, dev_addr=1):
        super().__init__(porta, baudrate, dev_addr)
        
    def get_safe_reading(self):
        # cerco l'Header [255, 254]
        while True:
            # leggo un byte alla volta finché non trovo l'inizio
            b = self.ser.read(1)
            if b == bytes([255]):
                b2 = self.ser.read(1)
                if b2 == bytes([254]):
                    break

        # leggi i 3 byte successivi: address, instr_code, length
        header_info = self.ser.read(3)
        addr = header_info[0]
        instr_code = header_info[1]
        instr_bytes = bytes([instr_code])
        length = header_info[2]

        # 3. leggi il corpo del messaggio (data) e il checksum finale
        payload = self.ser.read(length)
        received_chk = self.ser.read(1)[0]

        # 4. verifica del checksum
        calculated_chk_bytes = self.checksum(instr_bytes, payload) #checksum vuole dati in bytes
        calculated_chk = calculated_chk_bytes[0]

        if received_chk != calculated_chk:
            print("Errore: Checksum non corrisponde! Pacchetto scartato.")
            return None

        # 5. Decodifica i dati (se sono ASCII)
        
        try:
            valori_divisi = self.decode_ascii_data(payload, [length])
            return valori_divisi 
        except Exception as e:
            print(f"Errore nella decodifica ASCII: {e}")
            return None
   

class Camera:
    def __init__(self, camera_index=0, keep_frames=100): 
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
        # Attiva l'auto per far regolare la telecamera
        self.set_auto_exposure(True)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)

        print("Riscaldamento fotocamera (Auto mode)...")
        t0 = time.time()
        while time.time() - t0 < warmup_sec:
            ret, _ = self.cap.read()
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
        h, w = im0.shape[:2]
        Y, X = np.ogrid[:h, :w]
        dist_from_center = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        
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
        """
        Aggiorna le maschere ROI dinamicamente durante l'acquisizione.
        """
        if self.im0 is not None:
            self.masks = self._build_roi_masks(self.im0, center_x, center_y, radius)
    
    def acquire_image(self):
        ret, frame = self.cap.read() 
        #ret è un valore booleano, indica se la cattura è andata a buon fine (vale True)
        
        if not ret:
            raise RuntimeError("Impossibile acquisire un frame dalla webcam.")
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else self.im0

        return frame
    
    def _acquire_reference_image(self, avgs=16):
        frames = []
        for _ in range(avgs):
            frame = self.acquire_image()
            frames.append(frame.astype(np.float32))
            time.sleep(0.1) # Breve pausa per dare tempo al sensore
            
        if not frames:
            raise RuntimeError("Acquisizione immagine di riferimento fallita.")
        
        # frames è una lista di 16 immagini 2D 
           
        self.im0 = np.mean(frames, axis=0).astype(np.uint8)
        # scegliendo axis=0 per fissato pixel in ogni frame, prendo la media di quel pixel su tutti i frame
        
        # avg over the channels
        self.im0 = cv2.cvtColor(self.im0, cv2.COLOR_BGR2GRAY) if len(self.im0.shape) == 3 else self.im0
        
        return self.im0.astype(np.uint8)

    def _process_frame(self, im0, masks):

        if im0 is None or not masks:
            raise ValueError("Immagine di riferimento e maschere ROI devono essere inizializzate prima di processare.")

        frame = self.acquire_image()
        
        roi = frame * masks['total']
        
        return frame, roi

    def _continuous_acquisition(self, interval=0.1):
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
        self.capturing = False
        if hasattr(self, 'acquisition_thread'):
            self.acquisition_thread.join()

    def set_camera_params(self, exposure=-5, wb_temp=3900):
        
        # disabilita esposizione automatica e bilancamento del bianco automatico 
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        self.cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb_temp)
    
    def get_latest_image(self):
        if self.images:
            return self.images.popleft(), self.timestamps.popleft()
        else:
            return None

    def release(self):
        self.cap.release()

    def get_all_images(self):
        images = list(self.images)
        timestamps = list(self.timestamps)

        self.images.clear()
        self.timestamps.clear()

        return images, timestamps


