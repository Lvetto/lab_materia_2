import serial
from serial.tools import list_ports
import time
import threading
from collections import deque
import cv2
import numpy as np

class Bilancia:
    Header = bytes([255, 254])

    comandi = {
        "Remote activation" : bytes([0]),
        "Send monitor config" : bytes([1]),
        "Send film parametes" : bytes([2]),
        "Receive film parameters" : bytes([3]),
        "Send monitor status" : bytes([4]),
        "Config data-logging" : bytes([5]),
    }

    remote_activation_data = {
    "start" : bytes([1]),
    "stop" : bytes([2]),
    "shutter" : bytes([4]),
    }
      
    config_data_logging_data = [
    # byte 1
    ["Displayed rate", "Displayed thickness", "Displayed frequency", "Sensor 1 rate", "Sensor 1 thickness", "Sensor 1 frequency", "Sensor 2 rate", "Sensor 2 thickness"],
    # byte 2
    ["Sensor 2 frequency", "Active sensor number"]
    ]
    
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

        # allow the init of dummy devices without a serial port
        if porta is not None:
            self.ser = serial.Serial(porta, baudrate, timeout=1)
        else:
            self.ser = None

        self.dev_addr = bytes([dev_addr])

        self.read_thread = None
        self.reading = False

        self.decode_thread = None
        self.decoding = False

        self.lock = threading.Lock()

        self.read_buffer = deque()
        self.timestamps = deque()

        self.raw_read_buffer = deque()
        self.raw_timestamps = deque()

    def _data_len(self, data):
        return len(data).to_bytes(1, byteorder='little')
    
    def _checksum(self, instr_code, data):
        lenght = self._data_len(data)

        # 1s complement of the message payload
        checksum = 255 - (sum(instr_code + lenght + data) % 256)

        return checksum.to_bytes(1, byteorder='little') 
    
    def _build_message(self, comando, data=None):

        instr_code = self.comandi[comando]

        if data is not None:
            if comando == "Remote activation":
                data_encoded = self.remote_activation_data[data]
            
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
            data_encoded = bytes()
        
        encoded_command = self.Header + self.dev_addr + instr_code + self._data_len(data_encoded) + data_encoded + self._checksum(instr_code, data_encoded)
        return encoded_command
    
    def _decode_message(self, message):
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
        if self.ser.in_waiting >= num_bytes:
            message = self.ser.read(num_bytes)
            return message
        return None
    
        """rischio della funzione: 
        se il PC è veloce e legge mentre la bilancia sta ancora finendo di inviare il pacchetto,
        read_from_buffer restituirà None e salteremo quella misura. Se leggiamo il numero sbagliato
        di byte, potremmo iniziare a leggere a metà di un messaggio, perdendo l'allineamento
        con l'Header ([255, 254]).
        """
    
    def _decode_ascii_data(self, data, sizes):
        split_message = []

        idx = 0
        for size in sizes:
            split_message.append(data[idx:idx+size].decode('ascii').strip())
            idx += size

        return split_message

    def _handshake_data_logging(self, data):
        self.send_command("Config data-logging", [])

        time.sleep(0.1)

        self.read_buffer.clear()
        self.timestamps.clear()
        self.ser.reset_input_buffer()

        time.sleep(0.1)

        self.send_command("Config data-logging", data)

    def _continuous_read(self, data):

        sizes = [self.data_log_sizes[item] for item in data]
        size = sum(sizes)

        self.ser.reset_input_buffer()

        while self.reading:
            val = self.ser.read_all() # Legge tutto ciò che è disponibile nel buffer seriale
            if val:
                with self.lock:
                    # add each byte to the raw_read_buffer
                    for byte in val:
                        self.raw_read_buffer.append(byte)
                        self.raw_timestamps.append(time.time())
            time.sleep(0.01)

    def _dummy_continuous_read(self, data, chunk_size=16, iterations=100):
        i = 0
        while self.reading and i < iterations * chunk_size:
            val = data[i:i+chunk_size]  # Simula la lettura di chunk di dati
            i = (i + chunk_size) % len(data)  # Loop attraverso i dati
            with self.lock:
                if val:
                    for byte in val:
                        self.raw_read_buffer.append(byte)
                        self.raw_timestamps.append(time.time())
            time.sleep(0.01)
    
    def _decode_raw_buffer(self, sizes):
        while len(self.raw_read_buffer) >= sum(sizes):

            # Controlla se i primi 2 byte sono l'Header
            if self.raw_read_buffer[0] == 255 and self.raw_read_buffer[1] == 254:
                # Rimuovi l'Header e i loro timestamp
                self.raw_read_buffer.popleft()  # Rimuove 255
                self.raw_read_buffer.popleft()  # Rimuove 254

                self.raw_timestamps.popleft()  # Rimuove timestamp di 255
                self.raw_timestamps.popleft()  # Rimuove timestamp di 254

                # Rimuovi i byte di indirizzo, instr_code e data_length +  i timestamp associati (3 byte)
                for _ in range(3):
                    self.raw_read_buffer.popleft()
                    self.raw_timestamps.popleft()

                # Ora estrai i dati basati sui sizes specificati
                data_bytes = []
                for size in sizes:
                    chunk = bytes([self.raw_read_buffer.popleft() for _ in range(size)])
                    data_bytes.append(chunk)

                # Decodifica i dati e aggiungili al buffer di lettura
                decoded_data = [chunk.decode('ascii').strip() for chunk in data_bytes]
                self.read_buffer.append(decoded_data)
                self.timestamps.append(self.raw_timestamps.popleft())
            else:
                # Se non trovi l'Header, rimuovi il primo byte e continua a cercare
                self.raw_read_buffer.popleft()
                self.raw_timestamps.popleft()

    def _decode_thread(self, sizes):
        while self.decoding:
            with self.lock:
                self._decode_raw_buffer(sizes)
            time.sleep(0.05)

    def get_latest_data(self):
        if self.read_buffer:
            with self.lock:
                return self.read_buffer.popleft(), self.timestamps.popleft()
        else:
            return None

    def get_data(self):
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
        self.cap = cv2.VideoCapture(camera_index)

        self.im0 = None  # Immagine di riferimento
        self.masks = None  # Maschere ROI
        self.images = deque(maxlen=keep_frames)  # Buffer per le immagini acquisite
        self.timestamps = deque(maxlen=keep_frames)  # Buffer per i timestamp delle acquisizioni

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.capturing = False

        #self.set_camera_params()

        if not self.cap.isOpened():
            raise RuntimeError("Impossibile aprire la webcam.")
    
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
    
    def _acquire_reference_image(self, avgs=16):
        frames = []
        for _ in range(avgs):
            frame = self.acquire_image()
            frames.append(frame.astype(np.float32))
            time.sleep(0.1) # Breve pausa per dare tempo al sensore
            
        if not frames:
            raise RuntimeError("Acquisizione immagine di riferimento fallita.")
            
        self.im0 = np.mean(frames, axis=0).astype(np.uint8)
        # avg over the channels
        self.im0 = cv2.cvtColor(self.im0, cv2.COLOR_BGR2GRAY) if len(self.im0.shape) == 3 else self.im0
        
        return self.im0.astype(np.uint8)

    def _process_frame(self, im0, masks):

        if im0 is None or not masks:
            raise ValueError("Immagine di riferimento e maschere ROI devono essere inizializzate prima di processare.")

        frame = self.acquire_image()
        im1_float = frame.astype(np.float32)
        diff = im1_float - im0
        heatmap = abs(diff)

        ii = np.mean(255 - diff[masks['total']])
        ii_in = np.mean(255 - diff[masks['in']])
        ii_mid = np.mean(255 - diff[masks['mid']])
        
        ii1 = np.mean(255 - diff[masks['q1']])
        ii2 = np.mean(255 - diff[masks['q2']])
        ii3 = np.mean(255 - diff[masks['q3']])
        ii4 = np.mean(255 - diff[masks['q4']])
        
        return frame, heatmap, ii, ii_in, ii_mid, ii1, ii2, ii3, ii4

    def _continuous_acquisition(self, interval=0.1):
        while self.capturing:
            try:
                frame, heatmap, ii, ii_in, ii_mid, ii1, ii2, ii3, ii4 = self._process_frame(self.im0, self.masks)
                self.images.append((frame, heatmap, ii, ii_in, ii_mid, ii1, ii2, ii3, ii4))
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
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        self.cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb_temp)
    
    def acquire_image(self):
        ret, frame = self.cap.read()
        
        if not ret:
            raise RuntimeError("Impossibile acquisire un frame dalla webcam.")
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else self.im0

        return frame

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


