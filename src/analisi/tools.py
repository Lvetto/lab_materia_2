import numpy as np
import matplotlib.pyplot as plt
import cv2
import os
from math import sqrt
import time
import re
from scipy import signal
import ipywidgets as widgets


# conversione dei timestamp nello stesso formato tra bilancia e immagini (sarebbe il caso di sistemarlo anche nell'interfaccia...)

FORMATO_COMUNE = "%Y-%m-%d %H:%M:%S"

def bilancia_timestamp_to_common(timestamp_unix, fmt=FORMATO_COMUNE):
    """
    Timestamp bilancia (Unix epoch) -> formato comune.
    Supporta secondi (10 cifre) e millisecondi (13 cifre).
    """
    ts = float(timestamp_unix)
    if ts > 1e12:  # il ts è in millisecondi
        ts /= 1000.0 # lo converto in secondi perché le funzioni standard di Python (come time.localtime(ts)) si aspettano il tempo espresso in secondi
    return time.strftime(fmt, time.localtime(ts))


def image_timestamp_to_common(image_name_or_timestamp, fmt=FORMATO_COMUNE):
    """
    Timestamp immagini -> formato comune.
    Accetta:
    - 'frame_YYYYMMDD_HHMMSS.png'
    - 'YYYYMMDD_HHMMSS'
    - 'YYYY-MM-DD_HH-MM-SS' (nome cartella sessione)
    """
    s = str(image_name_or_timestamp)
    base = os.path.basename(s)

    m1 = re.search(r"(\d{8}_\d{6})", base)
    if m1:
        t = time.strptime(m1.group(1), "%Y%m%d_%H%M%S")
        return time.strftime(fmt, t)

    m2 = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", base)
    if m2:
        t = time.strptime(m2.group(1), "%Y-%m-%d_%H-%M-%S")
        return time.strftime(fmt, t)

    raise ValueError("Formato timestamp immagine non riconosciuto")

# caricamento dati dalle immagini

base_img_folder = "data/raw"

def load_images_from_folder(folder):
    """
    Carica tutte le immagini PNG da una cartella, restituendo una lista di immagini e i loro timestamp in formato comune.
    """
    images = []
    timestamps = []
    for filename in os.listdir(folder):
        if filename.endswith(".png"):
            img_path = os.path.join(folder, filename)
            img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                images.append(img)
                timestamps.append(image_timestamp_to_common(filename))
    return images, timestamps

def load_images_from_folders(folders):
    """
    Carica immagini da più cartelle, restituendo liste aggregate di immagini e timestamp.
    """
    all_images = []
    all_timestamps = []
    for folder in folders:
        images, timestamps = load_images_from_folder(folder)
        all_images.extend(images)
        all_timestamps.extend(timestamps)
    return all_images, all_timestamps

def sort_images_and_timestamps(images, timestamps):
    """
    Ordina immagini e timestamp in base ai timestamp.
    """
    combined = list(zip(timestamps, images)) #lista di tuple con l'immagine associata al suo timestamp
    combined.sort(key=lambda x: x[0]) #key fornisce il criterio di ordinamento cronologico rispetto alla prima coppia immagazzinata
    sorted_timestamps, sorted_images = zip(*combined) #spacchetto le coppie di tuple in due liste separate ma ora ordinate cronologicamente
    return list(sorted_images), list(sorted_timestamps)


# carica timestamp, rate, thickness dalla bilancia

def load_bilancia_data(file_path):
    """
    Carica dati dalla bilancia, restituendo liste di timestamp (formato comune), rate e thickness.
    """
    timestamps = []
    rates = []
    thicknesses = []
    with open(file_path, 'r') as f:
        for line in f:
            parts = line.strip().split('\t') # lista di tre stringhe
            # strip() rimuove gli spazi bianchi e i caratteri invisibili
            # split('\t') divide la stringa in una lista di sottostringhe usando il tab come delimitatore
            if len(parts) >= 3:
                ts_common = bilancia_timestamp_to_common(parts[0])
                timestamps.append(ts_common)
                rates.append(float(parts[1]))
                thicknesses.append(float(parts[2]))
    return timestamps, rates, thicknesses

def extract_common_timestamp_points(image_timestamps, bilancia_timestamps, max_diff_seconds=1.0):
    """
    Trova timestamp comuni tra immagini e bilancia, restituendo indici corrispondenti.
    """
    common_image_indices = []
    common_bilancia_indices = []
    
    for i, img_ts in enumerate(image_timestamps):
        img_time = time.strptime(img_ts, FORMATO_COMUNE)
        img_seconds = time.mktime(img_time)
        
        for j, bil_ts in enumerate(bilancia_timestamps):
            bil_time = time.strptime(bil_ts, FORMATO_COMUNE)
            bil_seconds = time.mktime(bil_time)
            
            if abs(img_seconds - bil_seconds) <= max_diff_seconds: # max_diffs_seconds è una finestra di accettabilità per considerare i timestamp "corrispondenti"
                common_image_indices.append(i)
                common_bilancia_indices.append(j)
                break  # Assumiamo un match unico per ogni immagine
    
    return common_image_indices, common_bilancia_indices

def interpolate_timestamps(image_timestamps, bilancia_timestamps, bilancia_values):
    """
    Interpola i valori della bilancia per i timestamp delle immagini.
    Restituisce una lista di valori interpolati corrispondenti ai timestamp delle immagini.
    """
    image_seconds = [time.mktime(time.strptime(ts, FORMATO_COMUNE)) for ts in image_timestamps]
    bilancia_seconds = [time.mktime(time.strptime(ts, FORMATO_COMUNE)) for ts in bilancia_timestamps]
    
    interpolated_values = np.interp(image_seconds, bilancia_seconds, bilancia_values)
    return interpolated_values

def moving_average_images(images, window_size):
    """
    Applica una media mobile alle immagini, restituendo una nuova lista di immagini filtrate.
    """

    if window_size == 1:
        return images  # nessun filtro se la finestra è 1 (meglio che sia un numero dispari)
    # con finestra si intende il numero di immagini su cui mediare: il fotogramma centrale e quelle immediatamente vicine

    moving_avg_imgs = []

    for i in range(len(images)):
        start_idx = max(0, i - window_size//2) # // è la divisione intera, senza parte decimale
        # start_idx = max(0, i - window_size//2 + 1)
        # tolto il +1 perché altrimenti la media non è centrata sull'i-esimo fotogramma 
        end_idx = min(len(images), i + window_size//2 + 1)
        window_imgs = images[start_idx:end_idx]
        moving_avg_img = np.mean(window_imgs, axis=0).astype(np.uint8)
        moving_avg_imgs.append(moving_avg_img)

    return moving_avg_imgs


def moving_average_images_gaussian_weights(images, window_size, sigma):
    """
    applica una media mobile alle immagini, dove ognuna è moltiplicata per un peso gaussiano
    """

    if window_size == 1:
        return images  # nessun filtro se la finestra è 1 (meglio che sia un numero dispari)

    moving_avg_imgs = []
    half_window = window_size // 2
    weights = np.zeros(window_size)
    weights = np.exp(-0.5 * (np.arange(-half_window, half_window + 1) / sigma) ** 2) # calcola i pesi gaussiani per ogni posizione nella finestra
    weights /= np.sum(weights)  # normalizza i pesi

    for i in range(len(images)):
        start_idx = max(0, i - half_window)
        end_idx = min(len(images), i + half_window + 1)
        window_imgs = images[start_idx:end_idx]

        # Se la finestra è più piccola di window_size (ad esempio all'inizio o alla fine), adatta i pesi
        if len(window_imgs) < window_size:
            adjusted_weights = weights[half_window - (i - start_idx):half_window + (end_idx - i)]
            adjusted_weights /= np.sum(adjusted_weights)  # normalizza i pesi adattati
        else:
            adjusted_weights = weights

        weighted_avg_img = np.zeros_like(images[0], dtype=np.float32)
        for img, w in zip(window_imgs, adjusted_weights):
            weighted_avg_img += img.astype(np.float32) * w

        moving_avg_imgs.append(weighted_avg_img.astype(np.uint8))

    return moving_avg_imgs


def extract_roi_from_images(images, roi_center, roi_radius):
    """
    Estrae una regione di interesse (ROI) circolare da ogni immagine, restituendo una lista di immagini ROI.
    """
    roi_images = []

    for img in images:
        mask = np.zeros_like(img, dtype=np.uint8) #crea un foglio nero (matrice di 0 delle dimensioni dell'immagine)
        cv2.circle(mask, roi_center, roi_radius, 255, -1) #crea un cerchio bianco sull'immagine nera
        roi_img = cv2.bitwise_and(img, img, mask=mask)
        #L'operatore AND bit a bit confronta l'immagine originale con la maschera:
        # dove la maschera è bianca: l'immagine originale "passa" e rimane identica.
        # dove la maschera è nera: l'immagine originale viene cancellata e diventa nera
        roi_images.append(roi_img)

    return roi_images

def compute_difference_from_reference(images, reference_image):
    """
    Calcola la differenza assoluta tra ogni immagine e un'immagine di riferimento, restituendo una lista di immagini differenza.
    """
    difference_images = []

    for img in images:
        diff_img = cv2.absdiff(img, reference_image)
        difference_images.append(diff_img)

    return difference_images

def compute_average_intensity(images):
    """
    Calcola l'intensità media di ogni immagine, restituendo una lista di valori di intensità media.
    """
    avg_intensities = []

    for img in images:
        avg_intensity = np.mean(img)
        avg_intensities.append(avg_intensity)

    return avg_intensities

def extract_line_profile_np(image, x0, y0, x1, y1, num_samples=None):
    """
    Estrae i valori lungo il segmento tra due punti con campionamento uniforme.
    Restituisce un array 1D di lunghezza fissa, gli elementi rappresentano la luminosità incontrata.
    """
    if num_samples is None:
        num_samples = int(np.hypot(x1 - x0, y1 - y0)) + 1 # il +1 per risolvere il "fencepost error"

    xs = np.linspace(x0, x1, num_samples)
    ys = np.linspace(y0, y1, num_samples)

    h, w = image.shape[:2]
    xs = np.clip(xs, 0, w - 1)
    ys = np.clip(ys, 0, h - 1)

    x0f = np.floor(xs).astype(int) # floor arrotonda per difetto
    y0f = np.floor(ys).astype(int)
    x1f = np.clip(x0f + 1, 0, w - 1)
    y1f = np.clip(y0f + 1, 0, h - 1)

    dx = xs - x0f
    dy = ys - y0f

    return (
        (1 - dx) * (1 - dy) * image[y0f, x0f] +
        dx * (1 - dy) * image[y0f, x1f] +
        (1 - dx) * dy * image[y1f, x0f] +
        dx * dy * image[y1f, x1f]
    ) # ciascun elemento è una media pesata delle coordinate dei 4 pixel più vicini al punto campionato, con pesi che dipendono dalla distanza del punto campionato da ciascuno di questi pixel (dx e dy)

def extract_line_profiles_np(images, x0, y0, x1, y1, num_samples=None):
    return [extract_line_profile_np(img, x0, y0, x1, y1, num_samples) for img in images]


def extract_line_profiles_circle_np(images, center, radius, num_profiles=10, num_samples=None):
    """
    Estrae num_profiles profili lungo diametri della circonferenza.
    Tutti i profili hanno la stessa lunghezza.
    """
    angles = np.linspace(0, 2 * np.pi, num_profiles, endpoint=False)
    all_profiles = []

    for img in images:
        profiles_for_image = []
        for angle in angles:
            x0 = center[0] + radius * np.cos(angle)
            y0 = center[1] + radius * np.sin(angle)
            x1 = center[0] - radius * np.cos(angle)
            y1 = center[1] - radius * np.sin(angle)

            profile = extract_line_profile_np(
                img,
                x0, y0, x1, y1,
                num_samples=num_samples
            )
            profiles_for_image.append(profile)
        all_profiles.append(np.stack(profiles_for_image, axis=0))

    return np.stack(all_profiles, axis=0)

def extract_average_line_profile_circle_np(images, center, radius, num_profiles=10):
    """
    Estrae i line profile lungo diametri di una circonferenza definita da un centro e un raggio, restituendo un array di profili medi.
    Usa la versione numpy dell'estrazione dei line profile.
    """

    line_profiles = extract_line_profiles_circle_np(images, center, radius, num_profiles)
    avg_line_profiles = np.mean(line_profiles, axis=0) if line_profiles else None
    return avg_line_profiles

def extract_line_profiles_circle(images, center, radius, num_profiles=10):
    """
    Estrae i line profile lungo diametri di una circonferenza definita da un centro e un raggio, restituendo una lista di array di profili.
    """

    line_profiles = []
    angles = np.linspace(0, 2 * np.pi, num_profiles, endpoint=False)

    for img in images:
        profiles_for_image = []
        for angle in angles:
            x0 = int(center[0] + radius * np.cos(angle))
            y0 = int(center[1] + radius * np.sin(angle))
            x1 = int(center[0] - radius * np.cos(angle))
            y1 = int(center[1] - radius * np.sin(angle))
            line_profile = img[y0:y1, x0:x1]
            profiles_for_image.append(line_profile)
        line_profiles.append(profiles_for_image)

    return line_profiles


class RoiSelectorWidget:
    def __init__(self, image):
        self.image = image
        self.roi_center = (image.shape[1] // 2, image.shape[0] // 2)
        self.roi_radius = min(image.shape) // 4

        with plt.ioff():
            self.fig, self.ax = plt.subplots()
            self.ax.imshow(image, cmap='gray')
            self.circle = plt.Circle(self.roi_center, self.roi_radius, color='r', fill=False)
            self.ax.add_patch(self.circle)
            self.ax.set_title("Clicca con sinistro per spostare, destro per ridimensionare")

        self.cid_click = self.fig.canvas.mpl_connect('button_press_event', self.on_click)

        self.draw()

    def on_click(self, event):
        # se tasto sinistro, cambia il centro
        if event.button == 1:
            self.roi_center = (int(event.xdata), int(event.ydata))
            self.update_circle()
        
        # se tasto destro, cambia il raggio
        elif event.button == 3:
            dx = event.xdata - self.roi_center[0]
            dy = event.ydata - self.roi_center[1]
            self.roi_radius = int(sqrt(dx**2 + dy**2))
            self.update_circle()

    def update_circle(self):
        self.circle.center = self.roi_center
        self.circle.radius = self.roi_radius
        self.fig.canvas.draw()
    
    def draw(self):
        self.fig.show()
    
    @property
    def roi(self):
        return self.roi_center, self.roi_radius

