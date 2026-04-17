import serial
import time
import numpy as np
import cv2

class SCPIInstrument:
    """ Representation of a generic SCPI instrument communicating via PySerial. """

    commands = {
        "identify": "*IDN?",
        "reset": "*RST",
        "clear": "*CLS"
    }
    
    def __init__(self, port, baudrate=9600, timeout=2, terminator='\r\n'):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.terminator = terminator
        
        # Init the serial connection
        self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self.reset_buffers()

    def reset_buffers(self):
        """Reset internal buffers"""
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def send_command(self, command):
        """Sends a raw SCPI command (automatically appends the terminator)."""
        complete_command = f"{command}{self.terminator}"
        self.serial.write(complete_command.encode('ascii'))

    def query(self, command, delay=0.05):
        """Sends a query and reads the instrument's response."""
        self.send_command(command)
        time.sleep(delay)
        response = self.serial.readline()
        
        # decode and clean up the response
        return response.decode('ascii', errors='ignore').strip()

    def identify(self):
        """Sends a universal SCPI command to identify the instrument."""
        return self.query(command=self.commands["identify"])

    def reset(self):
        """Sends a universal SCPI command to reset the instrument to factory defaults."""
        self.send_command(self.commands["reset"])
        self.send_command(self.commands["clear"])

    def close(self):
        """Sends a command to close the communication cleanly."""
        if self.serial.is_open:
            self.serial.close()

    def __delete__(self, instance):
        """Ensure the serial connection is closed when the object is deleted."""
        self.close()

class KeithleyElectrometer(SCPIInstrument):
    """Implementation for the Keithley 6517A."""

    # specific SCPI commands for the Keithley 6517A
    commands = {
        "zero_check_on": "SYST:ZCH ON",
        "zero_check_off": "SYST:ZCH OFF",
        "configure_current": "CONF:CURR:DC",
        "configure_voltage": "CONF:VOLT:DC",
        "configure_resistance": "CONF:RES",
        "configure_power": "CONF:POW",
        "configure_all": "CONF:ALL",
        "read": "READ?"
    }
    
    def __init__(self, port, baudrate=9600, timeout=2):
        # create a serial connection with the correct terminator for the Keithley (typically \r\n)
        super().__init__(port, baudrate, timeout, terminator='\r\n')

        # combine the base class commands with the Keithley-specific commands
        self.commands = {**SCPIInstrument.commands, **self.__class__.commands}

    def init_current_reading(self):
        """Set up the electrometer in a safe way to read currents."""
        self.reset()
        time.sleep(0.5)
        self.send_command(self.commands["zero_check_on"])
        self.send_command(self.commands["configure_current"])

    def read_current(self):
        """Reads a single current measurement."""
        self.send_command(self.commands["zero_check_off"])
        time.sleep(0.1) 
        
        raw_value = self.query(self.commands["read"])
        
        self.send_command(self.commands["zero_check_on"])
        
        try:
            # Il Keithley restituisce stringhe tipo "+1.23456E-09A, +000..."
            clean_value = float(raw_value.split(',')[0].replace('A', ''))
            return clean_value
        except (ValueError, IndexError):
            return raw_value  # Return the raw value for debugging if parsing fails

class MaxtekProtocol:
    """Base class to handle the Maxtek binary packet protocol."""
    
    # Fixed header for all packets as per the manual
    SYNC = b'\xff\xfe'
    
    def __init__(self, port, baudrate=9600, timeout=2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self.reset_buffers()

    def reset_buffers(self):
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
    
    def reset_input_buffer(self):
        self.serial.reset_input_buffer()
    
    def reset_output_buffer(self):
        self.serial.reset_output_buffer()

    def _compute_checksum(self, length, msg_type, data_bytes):
        """
        Compute the checksum as required by the manual:
        The remainder (modulo 256) of the 2's complement of the sum of Length, Type, and Data.
        """
        somma = length + msg_type + sum(data_bytes)
        checksum = (256 - (somma % 256)) % 256
        return checksum

    def send_packet(self, msg_type, data=b''):
        """
        Constructs and sends a packet following the specifications in the manual.
        """
        # Secondo il manuale, LENGTH = byte da Message Type a Checksum inclusi.
        # Quindi: 1 (Type) + len(data) + 1 (Checksum) = len(data) + 2
        lunghezza = len(data) + 2 
        
        checksum = self._compute_checksum(lunghezza, msg_type, data)
        
        packet = self.SYNC + bytes([lunghezza, msg_type]) + data + bytes([checksum])
        self.serial.write(packet)

    def send_raw(self, raw_bytes):
        """
        Sends raw bytes directly. Useful for hardcoded commands
        that we know already work.
        """
        self.serial.write(raw_bytes)

    def close(self):
        if self.serial.is_open:
            self.serial.close()

    def __delete__(self, instance):
        self.close()

class MaxtekScale(MaxtekProtocol):
    """Specific implementation for the Maxtek TM-350/400 scale."""
    
    # Manteniamo i comandi originali testati. Nota: sono già in formato bytes, quindi non serve convertirli ulteriormente.
    comandi_testati = {
        "identificazione": b'\xff\xfe\x01\x01\x00\xfe',
        "iniziazione_misure": b'\xff\xfe\x01\x05\x02\xf8\x01\xff',
        "stop": b'\xff\xfe\x01\x05\x02\x00\x00\xf8'
    }

    def __init__(self, port, baudrate=9600, timeout=2):
        super().__init__(port, baudrate, timeout)

    def identify(self):
        self.reset_buffers()
        self.send_raw(self.comandi_testati["identificazione"])
        response = self.serial.read(60)
        self.reset_buffers()
        return response.decode('ascii', errors='ignore').strip()
    
    def read_single_measurement(self):
        
        self.reset_input_buffer()

        self.start_measurements()
        #self.send_raw(self.comandi_testati["iniziazione_misure"])

        time.sleep(0.2)  # Breve pausa per dare tempo alla bilancia di rispondere

        self.send_raw(self.comandi_testati["stop"])

        response = self.read_measurement()

        self.reset_output_buffer()

        return response

    def start_measurements(self):
        self.send_raw(self.comandi_testati["iniziazione_misure"])
        self.serial.read(8)
    
    def read_measurement(self):
        """
        Read a single measurement packet and parse out the rate and thickness.
        """
        header = self.serial.read(5)
        if not header: # Se si pianta
            return None, None

        rate_string = self.serial.read(5) 
        thickness_string = self.serial.read(6)    
        tail = self.serial.read(32)

        try:
            rate = float(rate_string.decode('ascii').replace(",", "."))
            thickness = float(thickness_string.decode('ascii').replace(",", "."))
            return rate, thickness
        except ValueError:
            rate_str = rate_string.decode('ascii', errors='ignore').strip()
            thickness_str = thickness_string.decode('ascii', errors='ignore').strip()
            return None#rate_str, thickness_str  # Return raw strings for debugging if parsing fails
    
    def stop_measurements(self):
        self.reset_buffers()
        self.send_raw(self.comandi_testati["stop"])
        self.reset_buffers()
        self.close()

class Camera:
    def __init__(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)

        self.im0 = None  # Immagine di riferimento

        if not self.cap.isOpened():
            raise RuntimeError("Impossibile aprire la webcam.")
    
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
    
    def build_roi_masks(self, im0, center_x, center_y, radius):
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
    
    def acquire_reference_image(self, avgs=16):
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
        #self.im0 = cv2.cvtColor(self.im0, cv2.COLOR_BGR2GRAY)
        
        return self.im0.astype(np.uint8)

    def process_frame(self, im0, masks):

        if im0 is None or not masks:
            raise ValueError("Immagine di riferimento e maschere ROI devono essere inizializzate prima di processare.")

        frame = self.acquire_image()
        im1_float = frame.astype(np.float32)
        diff = im1_float - im0
        heatmap = np.linalg.norm(diff, axis=-1)

        ii = np.mean(255 - diff[masks['total']])
        ii_in = np.mean(255 - diff[masks['in']])
        ii_mid = np.mean(255 - diff[masks['mid']])
        
        ii1 = np.mean(255 - diff[masks['q1']])
        ii2 = np.mean(255 - diff[masks['q2']])
        ii3 = np.mean(255 - diff[masks['q3']])
        ii4 = np.mean(255 - diff[masks['q4']])
        
        return frame, heatmap, ii, ii_in, ii_mid, ii1, ii2, ii3, ii4

    def release(self):
        self.cap.release()
    
    def __delete__(self, instance):
        self.release()


