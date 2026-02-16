#!/usr/bin/env python3
"""
Script para insertar registros iniciales de impresoras del 31 de enero de 2026
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Configuración de base de datos
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "database.db"

# Cargar configuración de impresoras
with open(BASE_DIR / "config" / "config.json", "r") as f:
    config = json.load(f)

def insert_initial_records():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Datos de las impresoras basados en la configuración
    printers_data = [
        {
            "name": "Impresora Cartera Tercer Piso",
            "ip": "192.168.1.104",
            "location": "Piso 3",
            "total_copy": 212510,
            "total_print": 20698
        },
        {
            "name": "Impresora Pedidos y Facturación Segundo Piso",
            "ip": "192.168.1.59",
            "location": "Piso 2",
            "total_copy": 195910,
            "total_print": 8710
        },
        {
            "name": "Impresora Archivo Segundo Piso",
            "ip": "192.168.1.163",
            "location": "Piso 2",
            "total_copy": 857208,
            "total_print": 151269
        }
    ]
    
    # Fecha inicial: 31 de enero de 2026
    initial_date = "2026-01-31 00:00:00"
    
    for printer in printers_data:
        # Obtener o crear la impresora en la tabla monitored_printers
        cursor.execute(
            'SELECT id FROM monitored_printers WHERE ip_address = ?',
            (printer["ip"],)
        )
        result = cursor.fetchone()
        
        if result:
            printer_id = result[0]
            print(f"✓ Impresora '{printer['name']}' ya existe (ID: {printer_id})")
        else:
            cursor.execute(
                '''INSERT INTO monitored_printers 
                   (ip_address, friendly_name, location) 
                   VALUES (?, ?, ?)''',
                (printer["ip"], printer["name"], printer["location"])
            )
            printer_id = cursor.lastrowid
            print(f"✓ Impresora '{printer['name']}' registrada (ID: {printer_id})")
        
        # Insertar el registro inicial en printer_logs
        cursor.execute(
            '''INSERT INTO printer_logs 
               (printer_id, timestamp, total_copy, total_print) 
               VALUES (?, ?, ?, ?)''',
            (printer_id, initial_date, printer["total_copy"], printer["total_print"])
        )
        print(f"  └─ Registro inicial: {printer['total_copy']} copias, {printer['total_print']} impresiones")
    
    conn.commit()
    conn.close()
    print("\n✓ Registros insertados correctamente")

if __name__ == "__main__":
    insert_initial_records()
