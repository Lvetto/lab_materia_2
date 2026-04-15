import pyvisa
import numpy as np
import time
import serial
from serial.tools import list_ports
import matplotlib.pyplot as plt
import cv2

import ipywidgets as widgets
from lib.drivers import *
import threading

class BaseLabWidget(widgets.VBox):
    
    def __init__(self, instruments, acquire_hz=10, render_hz=5, window=100, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.instruments = instruments
        self.acquire_interval = 1.0 / acquire_hz
        self.render_interval  = 1.0 / render_hz
        self.running = False
        self.data  = {k: [] for k in instruments}
        self.times = {k: [] for k in instruments}
        self._lock = threading.Lock()

        self.start_btn = widgets.Button(description="Start")
        self.stop_btn  = widgets.Button(description="Stop")
        self.start_btn.on_click(self.start)
        self.stop_btn.on_click(self.stop)
        self.exp_slider = widgets.IntSlider(value=-5, min=-13, max=-1, description='Exp')
        self.wb_slider = widgets.IntSlider(value=3900, min=2800, max=6500, description='WB')
        self.plot_output = widgets.Output()

        self.layout = widgets.Layout(display='flex', flex_flow='column', align_items='center')
        self.children = [widgets.HBox([self.start_btn, self.stop_btn]), widgets.HBox([self.exp_slider, self.wb_slider]), self.plot_output]

        
        with self.plot_output:
            with plt.ioff():
                self.fig, self.axs = plt.subplots(1, 2, figsize=(10, 5))
            display(self.fig.canvas)
 
    def start(self, _):
        if not self.running:
            self.running = True
            threading.Thread(target=self._acquire_loop, daemon=True).start()
            threading.Thread(target=self._render_loop, daemon=True).start()
    
    def stop(self, _):
        self.running = False
    
    def _acquire_loop(self):
        pass

    def _render_loop(self):
        pass


class LabWidget(BaseLabWidget):
    
    def __init__(self, camera_indx=0, bilancia_port="", acquire_hz=10, render_hz=5, *args, **kwargs):
        super().__init__(instruments=["camera", "bilancia"], acquire_hz=acquire_hz, render_hz=render_hz, *args, **kwargs)

        self.camera_indx = camera_indx
        self.bilancia_port = bilancia_port

        try:
            self.camera = Camera(camera_indx)
        except Exception as e:
            print(f"Errore durante l'inizializzazione della fotocamera: {e}")
            self.camera = None

        try:
            self.bilancia = MaxtekScale(bilancia_port)
        except Exception as e:
            print(f"Errore durante l'inizializzazione della bilancia: {e}")
            self.bilancia = None

        self.axs[0].set_title("Spessore")
        self.axs[0].set_xlabel("Tempo (s)")
        self.axs[0].set_ylabel("Spessore (kAngstrom)")
        self.axs[1].set_title("Immagine")
        self.axs[1].axis('off')

    def _acquire_loop(self):
        while self.running:
            start_time = time.time()
            with self._lock:
                if self.bilancia is not None:
                    self.data["bilancia"].append(self.bilancia.read_measurement())
                    self.times["bilancia"].append(time.time())

                if self.camera is not None:
                    self.data["camera"].append(self.camera.acquire_image())
                    self.times["camera"].append(time.time())
            elapsed = time.time() - start_time
            time.sleep(max(0, self.acquire_interval - elapsed))
    
    def _render_loop(self):
        while self.running:
            start_time = time.time()
            with self._lock:
                bilancia_times = list(self.times["bilancia"])
                bilancia_data  = list(self.data["bilancia"])
                camera_data    = list(self.data["camera"])

            if bilancia_data and self.bilancia is not None:
                self.axs[0].clear()
                self.axs[0].plot(bilancia_times, bilancia_data, label="Peso")
                self.axs[0].set_xlabel("Tempo (s)")
                self.axs[0].set_ylabel("Peso (g)")
                self.axs[0].legend()

            if camera_data and self.camera is not None:
                self.axs[1].clear()
                self.axs[1].imshow(camera_data[-1])
                self.axs[1].set_title("Ultima immagine acquisita")

            self.fig.canvas.draw_idle()  # aggiorna il canvas in-place, niente copie

            elapsed = time.time() - start_time
            time.sleep(max(0, self.render_interval - elapsed))
    
    def __del__(self):
        if self.camera is not None:
            self.camera.release()
        if self.bilancia is not None:
            self.bilancia.close()
    
    def stop(self, _):
        super().stop(_)
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        if self.bilancia is not None:
            self.bilancia.close()
            self.bilancia = None
    
    def start(self, _):

        if self.camera is None:
            try:
                self.camera = Camera(self.camera_indx)
            except Exception as e:
                print(f"Errore durante l'inizializzazione della fotocamera: {e}")
                self.camera = None

        if self.bilancia is None:
            try:
                self.bilancia = MaxtekScale(self.bilancia_port)
            except Exception as e:
                print(f"Errore durante l'inizializzazione della bilancia: {e}")
                self.bilancia = None

        super().start(_)
