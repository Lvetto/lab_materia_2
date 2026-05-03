> **Regola d'oro:** 
> - `self.axes` = La griglia/cornice (statica)
> - `self.artists` = Il contenuto/dati (dinamico)

### si fa in modo che self.axes sia sempre una matrice accessibile tramite self.axes[i,j]:

```python
if ncols == 1 and nrows == 1:
    self.axes = np.array([[self.axes]]) #questa è una lista dentro una lista: np.array([self.axes]) crea un vettore, np.array([[self.axes]]) crea una matrice di un solo elemento
elif ncols == 1:
    self.axes = self.axes[:, np.newaxis] #creo 1 colonna, modifico il vettore di N righe in una matrice Nx1 
elif nrows == 1:
    self.axes = self.axes[np.newaxis, :] #creo 1 riga, modifico il vettore di N colonne in una matrice 1xN


#creo una matrice vuota della stessa dimensione della griglia di grafici
self.artists = np.empty((nrows, ncols), dtype=object) 

# inizializzo tele vuote in self.artist[i,j] 
if plot_type == 'image':
    self.artists[i, j] = self.axes[i, j].imshow(np.zeros((10, 10)), cmap='gray')
```

> - le funzioni add_callback(), start(), stop() fanno parte della libreria timer

> - la funzione on_click si aspetta come argomento il nome di una funzione da chiamare quando avviene il clic. Tuttavia, c'è una regola: questa funzione deve essere in grado di accettare un argomento (che rappresenta l'oggetto pulsante stesso che è stato cliccato).

```python
lambda _: self.on_start_btn() #crea una funzione anonima "usa e getta" che:
```
1) Riceve un argomento (rappresentato dal trattino basso _). Il trattino basso è una convenzione in Python per dire: "So che mi arrivano dei dati, ma non mi interessano e non li userò".

2) Esegue la funzione self.on_start_btn().

Scrivere on_click(self.on_start_btn()) è sbagliato perché eseguo la funzione mentre creo il collegamento al pulsante: il pulsante non funzionerà al clic, perché la funzione è già stata eseguita.

> - L'argomento event è un oggetto che viene generato e "spedito" automaticamente dal Backend di Matplotlib, è una cartella piena di dettagli sul clic appena avvenuto 

```python
self.fig.canvas.mpl_connect('button_press_event', self.on_roi_click) # "ogni volta che l'utente preme un tasto del mouse sulla figura, chiama la funzione on_roi_click"
```
1) Il sistema operativo comunica a Matplotlib le coordinate del cursore sullo schermo.

2) Matplotlib "impacchetta" queste informazioni grezze in un oggetto chiamato MouseEvent.

3) Matplotlib esegue la funzione on_roi_click e le passa questo pacchetto come argomento


