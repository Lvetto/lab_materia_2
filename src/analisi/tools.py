"""Utility per analisi congiunta di microbilancia al quarzo e immagini.

Questo modulo raccoglie funzioni per:
1. allineare timestamp tra segnali da microbilancia e immagini camera;
2. preprocessare stack di immagini (ROI, medie mobili, differenze);
3. estrarre feature fotometriche da correlare con spessore/rate misurati.
"""

import numpy as np
import matplotlib.pyplot as plt
import cv2
import os
from math import sqrt
import time
import re


# conversione dei timestamp nello stesso formato tra bilancia e immagini (sarebbe il caso di sistemarlo anche nell'interfaccia...)

FORMATO_COMUNE = "%Y-%m-%d %H:%M:%S"
""" Formato comune per timestamp di bilancia e immagini, usato per allineamento e confronto. """

def bilancia_timestamp_to_common(timestamp_unix, fmt=FORMATO_COMUNE):
    """Converte un timestamp Unix della bilancia nel formato comune.

    Args:
        timestamp_unix (float | int | str): Timestamp in secondi o millisecondi
            dal Unix epoch.
        fmt (str): Formato di output usato da ``time.strftime``.

    Returns:
        str: Timestamp formattato secondo ``fmt``.
    """
    ts = float(timestamp_unix)
    if ts > 1e12:  # il ts è in millisecondi
        ts /= 1000.0 # lo converto in secondi perché le funzioni standard di Python (come time.localtime(ts)) si aspettano il tempo espresso in secondi
    return time.strftime(fmt, time.localtime(ts))

def image_timestamp_to_common(image_name_or_timestamp, fmt=FORMATO_COMUNE):
    """Converte timestamp da nome file/cartella immagine al formato comune.

    Formati supportati:
    - ``frame_YYYYMMDD_HHMMSS.png``
    - ``YYYYMMDD_HHMMSS``
    - ``YYYY-MM-DD_HH-MM-SS``

    Args:
        image_name_or_timestamp (str): Nome file o stringa timestamp.
        fmt (str): Formato di output usato da ``time.strftime``.

    Returns:
        str: Timestamp normalizzato nel formato comune.

    Raises:
        ValueError: Se il formato non e riconosciuto.
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

def keithley_timestamp_to_common(timestamp_unix, fmt=FORMATO_COMUNE):
    """Converte timestamp da formato Keithley al formato comune.

    Args:
        timestamp_unix (float | int | str): Timestamp in secondi o millisecondi
            dal Unix epoch.
        fmt (str): Formato di output usato da ``time.strftime``.

    Returns:
        str: Timestamp normalizzato nel formato comune.
    """
    ts = float(timestamp_unix)
    if ts > 1e12:  # il ts è in millisecondi
        ts /= 1000.0 # lo converto in secondi perché le funzioni standard di Python (come time.localtime(ts)) si aspettano il tempo espresso in secondi
    return time.strftime(fmt, time.localtime(ts))

# caricamento dati dalle immagini

base_img_folder = "data/raw"

def load_images_from_folder(folder):
    """Carica tutte le immagini PNG in scala di grigi da una cartella.

    Args:
        folder (str): Percorso della cartella contenente immagini PNG.

    Returns:
        tuple[list[np.ndarray], list[str]]: Coppia con immagini caricate e
            timestamp normalizzati estratti dai nomi file.
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
    """Carica immagini da piu cartelle aggregando output in un unico dataset.

    Args:
        folders (list[str]): Elenco di cartelle da scandire.

    Returns:
        tuple[list[np.ndarray], list[str]]: Coppia con immagini aggregate e
            timestamp normalizzati corrispondenti.
    """
    all_images = []
    all_timestamps = []
    for folder in folders:
        images, timestamps = load_images_from_folder(folder)
        all_images.extend(images)
        all_timestamps.extend(timestamps)
    return all_images, all_timestamps

def sort_images_and_timestamps(images, timestamps):
    """Ordina immagini e timestamp usando il timestamp come chiave.

    Args:
        images (list[np.ndarray]): Immagini da ordinare.
        timestamps (list[str]): Timestamp associati alle immagini.

    Returns:
        tuple[list[np.ndarray], list[str]]: Immagini e timestamp ordinati.
    """
    combined = list(zip(timestamps, images)) #lista di tuple con l'immagine associata al suo timestamp
    combined.sort(key=lambda x: x[0]) #key fornisce il criterio di ordinamento cronologico rispetto alla prima coppia immagazzinata
    sorted_timestamps, sorted_images = zip(*combined) #spacchetto le coppie di tuple in due liste separate ma ora ordinate cronologicamente
    return list(sorted_images), list(sorted_timestamps)

# carica corrente, tempo, range di misura dal keithley

def load_keithley_data(file_path):
    """Carica dati tabulati del Keithley da file di testo.

    Ogni riga valida e attesa nel formato:
    ``current<TAB>timestamp<TAB>range``.

    Args:
        file_path (str): Percorso del file dati.

    Returns:
        tuple[list[str], list[float], list[float], list[float]]: correnti, timestamp
            normalizzati e range di misura.
    """
    timestamps = []
    currents = []
    ranges = []
    with open(file_path, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                ts_common = float(parts[1])#keithley_timestamp_to_common(parts[1])
                timestamps.append(ts_common)
                currents.append(float(parts[0]))
                range_val = parts[2].strip()
                if range_val.lower() == "auto":
                    ranges.append(float(-1))
                else:
                    ranges.append(float(range_val))
    return currents, timestamps, ranges

def calculate_resistance(currents_arr, voltage=1.0):
    return voltage / currents_arr

def separa_terzine_keithley(timestamps, currents, ranges):
    """
    Legge i dati a blocchi di 3 e li smista in base al range.
    Assicura di separare sia le correnti che i rispettivi timestamp.
    """
    # Inizializziamo un dizionario con liste vuote per ogni categoria
    separati = {
        'auto': {'timestamps': [], 'currents': []},
        'upper': {'timestamps': [], 'currents': []},
        'lower': {'timestamps': [], 'currents': []}
    }
    
    # Iteriamo saltando di 3 in 3
    for i in range(0, len(ranges), 3):
        # Estraiamo la "terzina" (chunk) corrente
        t_chunk = timestamps[i:i+3]
        c_chunk = currents[i:i+3]
        r_chunk = ranges[i:i+3]
        
        # Controllo di sicurezza: se l'ultimo blocco non ha 3 elementi, lo saltiamo
        if len(r_chunk) < 3:
            print(f"Attenzione: trovati {len(r_chunk)} dati residui alla fine del file. Ignorati.")
            break
            
        # 1. Troviamo l'indice del range Auto (-1)
        try:
            idx_auto = r_chunk.index(-1)
        except ValueError:
            # Se per qualche motivo manca il -1, saltiamo la terzina o gestiamo l'errore
            print(f"Range 'Auto' (-1) non trovato alla terzina {i}. Dati della terzina ignorati.")
            continue 
            
        # 2. Identifichiamo gli altri due indici
        indici_rimanenti = [0, 1, 2]
        indici_rimanenti.remove(idx_auto)
        idx_A, idx_B = indici_rimanenti
        
        # 3. Confrontiamo i valori dei range rimanenti per capire chi è upper e chi lower
        if r_chunk[idx_A] > r_chunk[idx_B]:
            idx_upper = idx_A
            idx_lower = idx_B
        else:
            idx_upper = idx_B
            idx_lower = idx_A
            
        # 4. Smistiamo i dati nei rispettivi contenitori
        separati['auto']['timestamps'].append(t_chunk[idx_auto])
        separati['auto']['currents'].append(c_chunk[idx_auto])
        
        separati['upper']['timestamps'].append(t_chunk[idx_upper])
        separati['upper']['currents'].append(c_chunk[idx_upper])
        
        separati['lower']['timestamps'].append(t_chunk[idx_lower])
        separati['lower']['currents'].append(c_chunk[idx_lower])

    # Convertiamo tutte le liste in array NumPy per comodità di analisi
    for categoria in separati:
        separati[categoria]['timestamps'] = np.array(separati[categoria]['timestamps'])
        separati[categoria]['currents'] = np.array(separati[categoria]['currents'])
        
    return separati

# carica timestamp, rate, thickness dalla bilancia

def load_bilancia_data(file_path):
    """Carica dati tabulati della microbilancia da file di testo.

    Ogni riga valida e attesa nel formato:
    ``timestamp<TAB>rate<TAB>thickness``.

    Args:
        file_path (str): Percorso del file dati.

    Returns:
        tuple[list[str], list[float], list[float]]: Timestamp normalizzati,
            rate e spessori.
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
                ts_common = (float(parts[0]))#bilancia_timestamp_to_common(parts[0])
                timestamps.append(ts_common)
                rates.append(float(parts[1]))
                thicknesses.append(float(parts[2]))
    return timestamps, rates, thicknesses # i dati nel file sono salvati in ordine: tempo, spessore e rate 
# rate e spessore sono salvati nell'array opposto (i.e. i dati di spessore (parts[1]) sono salvati in rates e viceversa )

def extract_common_timestamp_points(image_timestamps, bilancia_timestamps, max_diff_seconds=1.0):
    """Trova coppie immagine-bilancia compatibili temporalmente.

    Per ogni timestamp immagine cerca il primo timestamp bilancia entro una
    finestra temporale ``max_diff_seconds``.

    Args:
        image_timestamps (list[str]): Timestamp immagini nel formato comune.
        bilancia_timestamps (list[str]): Timestamp bilancia nel formato comune.
        max_diff_seconds (float): Scarto massimo accettato in secondi.

    Returns:
        tuple[list[int], list[int]]: Indici corrispondenti in
            ``image_timestamps`` e ``bilancia_timestamps``.
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
    """Interpola valori bilancia sui timestamp delle immagini.

    Args:
        image_timestamps (list[str]): Timestamp immagini nel formato comune.
        bilancia_timestamps (list[str]): Timestamp bilancia nel formato comune.
        bilancia_values (list[float] | np.ndarray): Valori associati ai
            timestamp bilancia (es. rate o spessore).

    Returns:
        np.ndarray: Valori interpolati sui timestamp immagini.
    """
    image_seconds = [time.mktime(time.strptime(ts, FORMATO_COMUNE)) for ts in image_timestamps]
    bilancia_seconds = [time.mktime(time.strptime(ts, FORMATO_COMUNE)) for ts in bilancia_timestamps]
    
    interpolated_values = np.interp(image_seconds, bilancia_seconds, bilancia_values)
    return interpolated_values

def moving_average_images(images, window_size):
    """Applica media mobile uniforme a una sequenza di immagini.

    Args:
        images (list[np.ndarray]): Sequenza immagini in ingresso.
        window_size (int): Ampiezza della finestra mobile.

    Returns:
        list[np.ndarray]: Sequenza filtrata.
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
    """Applica media mobile pesata con kernel gaussiano.

    Args:
        images (list[np.ndarray]): Sequenza immagini in ingresso.
        window_size (int): Ampiezza della finestra mobile.
        sigma (float): Deviazione standard del kernel gaussiano.

    Returns:
        list[np.ndarray]: Sequenza filtrata con pesi gaussiani.
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
    """Estrae una ROI circolare da ciascuna immagine.

    Args:
        images (list[np.ndarray]): Sequenza immagini in ingresso.
        roi_center (tuple[int, int]): Centro ROI in coordinate pixel ``(x, y)``.
        roi_radius (int): Raggio ROI in pixel.

    Returns:
        list[np.ndarray]: Immagini mascherate con sola ROI.
    """
    roi_images = []

    for img in images:
        mask = np.zeros_like(img) #crea un foglio nero (matrice di 0 delle dimensioni dell'immagine)
        h, w = img.shape[:2]
        Y, X = np.ogrid[:h, :w] #Y è una colonna che contiene tutti gli indici di riga, X è una riga che contiene tutti gli indici di colonna
        dist_from_center = np.sqrt((X - roi_center[0])**2 + (Y - roi_center[1])**2) # non è un numero, ma una matrice della stessa dimensione della reference_image pari a h x w
        roi_mask = dist_from_center <= roi_radius
        #cv2.circle(mask, roi_center, roi_radius, 255, -1) #crea un cerchio bianco sull'immagine nera
        #roi_img = cv2.bitwise_and(img, img, mask=mask)
        #L'operatore AND bit a bit confronta l'immagine originale con la maschera:
        # dove la maschera è bianca: l'immagine originale "passa" e rimane identica.
        # dove la maschera è nera: l'immagine originale viene cancellata e diventa nera
        roi_images.append(img * roi_mask)

    return roi_images

def compute_difference_from_reference(images, reference_image):
    """Calcola differenza assoluta rispetto a una immagine di riferimento.

    Args:
        images (list[np.ndarray]): Sequenza immagini da confrontare.
        reference_image (np.ndarray): Immagine di riferimento.

    Returns:
        list[np.ndarray]: Immagini differenza assoluta.
    """
    difference_images = []

    for img in images:
        diff_img = reference_image - img  #cv2.absdiff(img, reference_image)
        difference_images.append(diff_img)

    return difference_images

def compute_average_intensity(images):
    """Calcola l'intensita media per ogni immagine.

    Args:
        images (list[np.ndarray]): Sequenza immagini.

    Returns:
        list[float]: Intensita medie per frame.
    """
    avg_intensities = []

    for img in images:
        avg_intensity = np.mean(img)
        avg_intensities.append(avg_intensity)

    return avg_intensities

def extract_line_profile_np(image, x0, y0, x1, y1, num_samples=None):
    """Estrae un profilo di intensita lungo un segmento con interpolazione.

    Usa interpolazione bilineare su campionamento uniforme tra i due estremi.

    Args:
        image (np.ndarray): Immagine sorgente.
        x0 (float): Coordinata x del punto iniziale.
        y0 (float): Coordinata y del punto iniziale.
        x1 (float): Coordinata x del punto finale.
        y1 (float): Coordinata y del punto finale.
        num_samples (int | None): Numero di campioni lungo il segmento. Se
            ``None`` viene usata la lunghezza geometrica del segmento + 1.

    Returns:
        np.ndarray: Profilo 1D di intensita.
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
    """Estrae lo stesso profilo lineare da una sequenza di immagini.

    Args:
        images (list[np.ndarray]): Sequenza immagini.
        x0 (float): Coordinata x del punto iniziale.
        y0 (float): Coordinata y del punto iniziale.
        x1 (float): Coordinata x del punto finale.
        y1 (float): Coordinata y del punto finale.
        num_samples (int | None): Numero di campioni per profilo.

    Returns:
        list[np.ndarray]: Lista di profili, uno per immagine.
    """
    return [extract_line_profile_np(img, x0, y0, x1, y1, num_samples) for img in images]

def extract_line_profiles_circle_np(images, center, radius, num_profiles=10, num_samples=None):
    """Estrae profili lungo diametri distribuiti su una circonferenza.

    Args:
        images (list[np.ndarray]): Sequenza immagini.
        center (tuple[float, float]): Centro della circonferenza ``(x, y)``.
        radius (float): Raggio della circonferenza.
        num_profiles (int): Numero di diametri/profili per immagine.
        num_samples (int | None): Numero campioni per singolo profilo.

    Returns:
        np.ndarray: Array con shape ``(n_immagini, num_profiles, n_samples)``.
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
    """Calcola il profilo medio su diametri di una circonferenza.

    Args:
        images (list[np.ndarray]): Sequenza immagini.
        center (tuple[float, float]): Centro della circonferenza ``(x, y)``.
        radius (float): Raggio della circonferenza.
        num_profiles (int): Numero di diametri/profili per immagine.

    Returns:
        np.ndarray | None: Profilo medio per diametro, o ``None`` quando non
            sono disponibili profili.
    """

    line_profiles = extract_line_profiles_circle_np(images, center, radius, num_profiles)
    avg_line_profiles = np.mean(line_profiles, axis=0) if line_profiles else None
    return avg_line_profiles

def extract_line_profiles_circle(images, center, radius, num_profiles=10):
    """Estrae profili discreti su diametri senza interpolazione.

    Args:
        images (list[np.ndarray]): Sequenza immagini.
        center (tuple[int, int]): Centro della circonferenza ``(x, y)``.
        radius (int): Raggio della circonferenza.
        num_profiles (int): Numero di diametri/profili per immagine.

    Returns:
        list[list[np.ndarray]]: Profili raggruppati per immagine.
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
    """Widget interattivo per selezionare una ROI circolare su un'immagine."""

    def __init__(self, image):
        """Inizializza il widget e registra callback mouse.

        Args:
            image (np.ndarray): Immagine su cui selezionare la ROI.
        """
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
        """Gestisce click mouse per spostare/ridimensionare la ROI.

        Args:
            event (matplotlib.backend_bases.MouseEvent): Evento mouse.
        """
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
        """Aggiorna geometria della ROI disegnata sul canvas."""
        self.circle.center = self.roi_center
        self.circle.radius = self.roi_radius
        self.fig.canvas.draw()
    
    def draw(self):
        """Mostra la figura associata al widget."""
        self.fig.show()
    
    @property
    def roi(self):
        """Restituisce stato corrente della ROI.

        Returns:
            tuple[tuple[int, int], int]: Centro ``(x, y)`` e raggio in pixel.
        """
        return self.roi_center, self.roi_radius

def lin_fit_with_error(x, y):
    """
    Esegue una regressione lineare sui dati (x, y) e restituisce i parametri della retta (slope, intercept) e l'errore standard.
    """
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * np.array(x) + intercept
    residuals = np.array(y) - predicted
    error = np.sqrt(np.sum(residuals**2) / (len(x) - 2))
    return slope, intercept, error