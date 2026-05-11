# -*- coding: utf-8 -*-
"""
Created on Thu May  8 16:21:03 2025

@author: casse
"""

# -*- coding: utf-8 -*-

import pyvisa
import numpy as np
import time
import keyboard
import serial


# ----- CONNESSIONE STRUMENTI -------
rm = pyvisa.ResourceManager()
inst = rm.list_resources()  #chiediamo quali porte sono aperte
print(inst)
multimeter = rm.open_resource('ASRL4::INSTR')


libra = serial.Serial('COM5', 9600,  timeout=2)
print(libra.name)

libra.reset_input_buffer()
libra.reset_output_buffer()

#----- IDENTIFICAZIONE STRUMENTI------
multimeter.write('*IDN?') #chiediamo allo strumento di identificarsi
print("Connection to ", multimeter.read()) #stampiamo la risposta del multimetro
multimeter.read()

identify_instruction = chr(255) + chr(254) + chr(1) + chr(1) + chr(0) + chr(254)
libra.write(identify_instruction.encode('latin-1'))
risposta = libra.read(60)  # Legge 255 byte dalla porta seriale
print(risposta)

time.sleep(2)# usiamo time.sleep al posto di *OPC per non dover scrivere ogni volta multimeter.read()

#-----RESET E INIZIALIZZAZIONE MULTIMETRO----
multimeter.write("*RST")
time.sleep(2)
multimeter.read()

# resistivity mesurement 
multimeter.write('OHMS')
#multimeter.write('OHMS2')
multimeter.read()


# multimeter scaling
multimeter.write('AUTO')
time.sleep(5)
multimeter.read()

# ----- PRESA DATI -------

istruzione = chr(255) + chr(254) + chr(1) + chr(5) + chr(2) + chr(248) + chr(1) + chr(255)
stop = chr(255)+chr(254)+chr(1)+chr(5)+chr(2)+chr(0)+chr(0)+chr(248)

multi_data =[]
libra_data =[]
startime=time.time()

libra.write(istruzione.encode('latin-1')) #indico alla bilancia di iniziare le misure
libra.read(8) #leggiamo corretta ricezione del messaggio di prendere le misure

print("Misure in corso, premere 'esc' per terminare le misure")

try:
    
    while True:
        duration_l = round( time.time() - startime, 5)
        libra.read(5) #leggo la testa della singola misura\
        rate_string= libra.read(5) #something like b'...'
        spessore_string= libra.read(6)
        libra.read(32)# leggo la coda della singola misura
        rate = rate_string.decode('latin-1')
        spessore = spessore_string.decode('latin-1')
        libra_data.append((duration_l, float(rate),float(spessore)))
    
    
        duration_m = round( time.time() - startime, 5)
        multimeter.write('VAL1?')
        misura = float(multimeter.read()) #.read() mi genera una string
        multi_data.append((duration_m, misura))
        multimeter.read()
    
        print(spessore, misura)
        
        if keyboard.is_pressed("esc"):
            print("Fine delle misure")
            np.savetxt(fname= "libra_data_6_06_1mm.txt", X= libra_data,fmt='%s', delimiter = '\t', header = "Tempo\t Rate\t Spessore")
            libra.reset_input_buffer()
            libra.write(stop.encode('latin-1'))

            
            np.savetxt(fname= "multimeter_data_6_06_1mm.txt", X= multi_data,fmt='%s', delimiter = '\t', header = "Tempo\t Resistenza")
            #multimeter.close()
            time.sleep(2)
            libra.reset_input_buffer()
            
            libra.reset_output_buffer()
            #libra.close() #chiudo porta seriale

            break
  
except:
    print("errore di misura")
    
finally:
    np.savetxt(fname= "libra_data_6_06_1mm.txt", X= libra_data,fmt='%s', delimiter = '\t', header = "Tempo\t Rate\t Spessore")
    libra.reset_input_buffer()
    libra.write(stop.encode('latin-1'))

    
    np.savetxt(fname= "multimeter_data_6_06_1mm.txt", X= multi_data,fmt='%s', delimiter = '\t', header = "Tempo\t Resistenza")
    multimeter.close()
    time.sleep(2)
    libra.reset_input_buffer()
    
    libra.reset_output_buffer()
    libra.close() #chiudo porta seriale

    