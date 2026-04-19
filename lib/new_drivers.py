import serial
from serial.tools import list_ports
import time
import threading
from collections import deque

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
        self.ser = serial.Serial(porta, baudrate, timeout=1)
        self.dev_addr = bytes([dev_addr])

        self.read_thread = None
        self.reading = False

        self.read_buffer = deque()
        self.timestamps = deque()

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

    def _continuous_read(self, sizes):
        size = sum(sizes)

        self.ser.reset_input_buffer()

        while self.reading:
            val = self._read_from_buffer(size)
            if val:
                try:
                    decoded_val = self._decode_ascii_data(val, sizes)

                    decoded_val = [float(x) if x.replace('.','',1).isdigit() else x for x in decoded_val]
                                        
                    self.read_buffer.append(decoded_val)
                    self.timestamps.append(time.time())
                    
                except (UnicodeDecodeError, ValueError) as e:
                    print("Disallineamento rilevato, ripristino il flusso...")
                    self.ser.reset_input_buffer()
                    time.sleep(0.1)
                    continue
            
            time.sleep(0.02)

    def get_latest_data(self):
        if self.read_buffer:
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
        self.ser.reset_input_buffer()
        message = self._build_message(comando, data)
        self.ser.write(message)

        response = self.ser.read(8) 

        if len(response) == 8:
            return self._decode_message(response)
        else:
            print("Errore: Risposta non ricevuta o parziale dal dispositivo.")
            return None
    
    # proposta altra funzione per leggere
    
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
    
    def start_continuous_read(self, data=["Displayed rate", "Displayed thickness"]):
        if self.read_thread is None or not self.read_thread.is_alive():

            self.send_command("Config data-logging", data)

            sizes = [self.data_log_sizes[item] for item in data]
    
            self.read_thread = threading.Thread(target=self._continuous_read, args=(sizes,))
            self.read_thread.daemon = True
            self.reading = True
            self.read_thread.start()
    
    def stop_continuous_read(self):
        self.reading = False
        self.send_command("Config data-logging", [])
        if self.read_thread is not None:
            self.read_thread.join()

    def close(self):
        self.stop_continuous_read()
        if self.ser.is_open:
            self.ser.close()
