import sqlite3
import os
from datetime import datetime

# Calculate path relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "data", "database.db")

def get_connection():
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla de inventario de impresoras
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS monitored_printers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT NOT NULL,
        serial_number TEXT UNIQUE,
        friendly_name TEXT,
        location TEXT,
        model TEXT,
        manufacturer TEXT,
        active BOOLEAN DEFAULT 1
    )
    ''')
    
    # Tabla de logs históricos (Sin Toner)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS printer_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        printer_id INTEGER,
        timestamp DATETIME,
        serial_number TEXT,
        mac_address TEXT,
        firmware TEXT,
        uptime TEXT,
        model TEXT,
        manufacturer TEXT,
        description TEXT,
        device_info TEXT,
        total_engine INTEGER,
        total_print INTEGER,
        total_copy INTEGER,
        simplex_count INTEGER,
        duplex_count INTEGER,
        FOREIGN KEY(printer_id) REFERENCES monitored_printers(id)
    )
    ''')
    
    conn.commit()
    
    # Ejecutar migraciones
    _run_migrations(conn)
    conn.close()

def _run_migrations(conn):
    """
    Ejecuta migraciones para actualizar el esquema de tablas existentes.
    Esto es útil cuando la BD ya existe pero le faltan columnas.
    """
    cursor = conn.cursor()
    
    # Verificar y agregar columnas faltantes a monitored_printers
    cursor.execute("PRAGMA table_info(monitored_printers)")
    columns = {row[1] for row in cursor.fetchall()}
    
    if 'model' not in columns:
        cursor.execute('ALTER TABLE monitored_printers ADD COLUMN model TEXT')
    if 'manufacturer' not in columns:
        cursor.execute('ALTER TABLE monitored_printers ADD COLUMN manufacturer TEXT')
    
    conn.commit()

def get_or_create_printer(ip, name, location="Unknown", serial=None, model=None, manufacturer=None):
    """
    Busca una impresora.
    Si se proporciona 'serial', se usa como identificador principal.
    Si no, se usa la IP (para compatibilidad o si falla SNMP).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    printer_id = None
    
    if serial:
        # 1. Buscar por Serial (Prioridad)
        cursor.execute('SELECT id, ip_address FROM monitored_printers WHERE serial_number = ?', (serial,))
        result = cursor.fetchone()
        
        if result:
            printer_id = result[0]
            current_ip = result[1]
            
            # Actualizar IP y metadatos si cambiaron
            if current_ip != ip:
                cursor.execute('''
                    UPDATE monitored_printers 
                    SET ip_address = ?, friendly_name = ?, location = ?, model = ?, manufacturer = ? 
                    WHERE id = ?
                ''', (ip, name, location, model, manufacturer, printer_id))
            else:
                 # Actualizar solo info meta
                 cursor.execute('''
                    UPDATE monitored_printers 
                    SET friendly_name = ?, location = ?, model = ?, manufacturer = ? 
                    WHERE id = ?
                ''', (name, location, model, manufacturer, printer_id))
        else:
            # Serial no encontrado, crear nueva (o ver si existe por IP y agregarle serial)
            # Primero chequear si la IP ya existe sin serial asignado
            cursor.execute('SELECT id FROM monitored_printers WHERE ip_address = ? AND serial_number IS NULL', (ip,))
            result_ip = cursor.fetchone()
            
            if result_ip:
                # Existe por IP pero no tenía serial, actualizamos
                printer_id = result_ip[0]
                cursor.execute('''
                    UPDATE monitored_printers 
                    SET serial_number = ?, friendly_name = ?, location = ?, model = ?, manufacturer = ? 
                    WHERE id = ?
                ''', (serial, name, location, model, manufacturer, printer_id))
            else:
                # Nuevo registro completo
                cursor.execute('''
                    INSERT INTO monitored_printers (ip_address, serial_number, friendly_name, location, model, manufacturer)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (ip, serial, name, location, model, manufacturer))
                printer_id = cursor.lastrowid

    else:
        # Fallback: Buscar solo por IP (si no pudimos obtener serial)
        cursor.execute('SELECT id FROM monitored_printers WHERE ip_address = ?', (ip,))
        result = cursor.fetchone()
        
        if result:
            printer_id = result[0]
            cursor.execute('''
                UPDATE monitored_printers 
                SET friendly_name = ?, location = ? 
                WHERE id = ?
            ''', (name, location, printer_id))
        else:
            cursor.execute('''
                INSERT INTO monitored_printers (ip_address, friendly_name, location)
                VALUES (?, ?, ?)
            ''', (ip, name, location))
            printer_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return printer_id

def list_printers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, ip_address, friendly_name, location, serial_number FROM monitored_printers WHERE active = 1')
    printers = cursor.fetchall()
    conn.close()
    return printers

def delete_printer(printer_id):
    conn = get_connection()
    cursor = conn.cursor()
    # Soft delete (desactivar) o Hard delete? El usuario pidió "borrar".
    # Hard delete es más limpio si queremos reiniciar, pero perdemos histórico.
    # Haré hard delete de logs y soft delete de la impresora para mantener integridad, 
    # o hard delete completo. El script clean_data hacía hard delete.
    # Vamos con Hard Delete completo como pidió el usuario para "limpiar".
    
    cursor.execute('DELETE FROM printer_logs WHERE printer_id = ?', (printer_id,))
    cursor.execute('DELETE FROM monitored_printers WHERE id = ?', (printer_id,))
    
    rows = cursor.rowcount
    conn.commit()
    conn.close()
    return rows > 0

def insert_log(printer_id, data):
    conn = get_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.now()
    
    cursor.execute('''
        INSERT INTO printer_logs (
            printer_id, timestamp, serial_number, mac_address, firmware, 
            uptime, model, manufacturer, description, device_info,
            total_engine, total_print, total_copy, 
            simplex_count, duplex_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        printer_id, timestamp, 
        data.get('serial_number'), 
        data.get('mac_address'), 
        data.get('firmware'), 
        data.get('uptime'),
        data.get('model'),
        data.get('manufacturer'),
        data.get('description'),
        data.get('device_info'),
        data.get('total_engine', 0), 
        data.get('total_print', 0), 
        data.get('total_copy', 0), 
        data.get('simplex_count', 0), 
        data.get('duplex_count', 0)
    ))
    
    conn.commit()
    conn.close()

def get_monthly_data(printer_id, month, year):
    """
    Obtiene el primer y último registro del mes para calcular el consumo.
    Retorna (first_log, last_log) donde cada log es un diccionario o tupla.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Formato de fecha para SQLite: YYYY-MM
    start_date = f"{year}-{month:02d}-01"
    # Lógica simple para fin de mes: buscamos hasta el inicio del siguiente mes
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    # Obtener el primer registro del mes
    cursor.execute('''
        SELECT * FROM printer_logs 
        WHERE printer_id = ? AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp ASC LIMIT 1
    ''', (printer_id, start_date, end_date))
    first_log = cursor.fetchone()
    
    # Obtener el último registro del mes
    cursor.execute('''
        SELECT * FROM printer_logs 
        WHERE printer_id = ? AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (printer_id, start_date, end_date))
    last_log = cursor.fetchone()
    
    conn.close()
    return first_log, last_log

def get_previous_month_last_log(printer_id, current_month, current_year):
    """
    Obtiene el último registro del mes ANTERIOR al solicitado.
    Esto es crucial porque el consumo del mes = (Ultimo registro mes actual) - (Ultimo registro mes anterior)
    Si no hay mes anterior, se usa el primero del mes actual como base (consumo parcial).
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if current_month == 1:
        prev_month = 12
        prev_year = current_year - 1
    else:
        prev_month = current_month - 1
        prev_year = current_year
        
    start_date = f"{prev_year}-{prev_month:02d}-01"
    if prev_month == 12:
        end_date = f"{prev_year+1}-01-01"
    else:
        end_date = f"{prev_year}-{prev_month+1:02d}-01"
        
    cursor.execute('''
        SELECT * FROM printer_logs 
        WHERE printer_id = ? AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (printer_id, start_date, end_date))
    
    result = cursor.fetchone()
    conn.close()
    return result

def get_all_active_printers():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM monitored_printers WHERE active = 1')
    printers = cursor.fetchall()
    conn.close()
    return printers
