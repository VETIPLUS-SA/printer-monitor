import json
import logging
import os
import sys
from datetime import datetime
from . import snmp
from . import database
from . import reports

# Determine base directory (one level up from this file's directory, then one more up to root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "logs", "monitor.log")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "config.json")

# Ensure logs directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Configuración de Logging Global
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

logger = logging.getLogger("monitor")

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando config.json desde {CONFIG_FILE}: {e}")
        sys.exit(1)

def process_printers(config):
    logger.info("Iniciando ciclo de monitoreo...")
    
    profiles = config.get('profiles', {})
    printers = config.get('printers', [])
    
    for printer_conf in printers:
        ip = printer_conf.get('ip')
        name = printer_conf.get('name')
        profile_name = printer_conf.get('profile')
        location = printer_conf.get('location', 'Unknown')
        
        logger.info(f"Procesando impresora: {name} ({ip})")
        
        # 1. Obtener OIDs del perfil
        profile = profiles.get(profile_name)
        if not profile:
            logger.error(f"Perfil '{profile_name}' no encontrado para {name}")
            continue
            
        oids_map = profile.get('oids')

        # 2. Obtener datos SNMP PRIMERO (para tener el serial)
        snmp_data = snmp.get_snmp_data(ip, printer_conf, oids_map)
        
        # Validar si obtuvimos datos críticos (ej: serial)
        if snmp_data and snmp_data.get('serial_number'):
            serial = snmp_data.get('serial_number')
            model = snmp_data.get('model')
            manufacturer = snmp_data.get('manufacturer')
            logger.info(f"Datos obtenidos exitosamente para {name} (Serial: {serial}, Modelo: {model})")
            
            # 3. Asegurar impresora en BD usando SERIAL + metadatos
            printer_id = database.get_or_create_printer(
                ip, name, location, serial=serial, model=model, manufacturer=manufacturer
            )
            # 4. Guardar en BD
            database.insert_log(printer_id, snmp_data)
        else:
            logger.warning(f"No se pudieron obtener datos completos para {name} (No se pudo obtener Serial)")

def list_printers():
    database.init_db()
    printers = database.list_printers()
    print(f"\n{'ID':<5} {'IP':<15} {'Nombre':<20} {'Ubicación':<15} {'Serial':<15}")
    print("-" * 75)
    for p in printers:
        # p es una tupla: (id, ip, name, location, serial)
        print(f"{p[0]:<5} {p[1]:<15} {p[2]:<20} {p[3]:<15} {str(p[4]):<15}")
    print("\n")

def delete_printer(printer_id):
    database.init_db()
    success = database.delete_printer(printer_id)
    if success:
        print(f"Impresora ID {printer_id} eliminada correctamente.")
    else:
        print(f"No se encontró impresora con ID {printer_id}.")

def run_scan():
    config = load_config()
    database.init_db()
    process_printers(config)

def run_report():
    database.init_db()
    generate_report_logic()


def generate_report_logic():
    """
    Compone los datos necesarios desde la base y genera los PDF individuales y el global.
    """
    now = datetime.now()
    month = now.month
    year = now.year

    # Asegurar carpeta de reportes
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(BASE_DIR, 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    data_rows = []

    printers = database.get_all_active_printers()
    for p in printers:
        printer_id = p['id']
        name = p['friendly_name'] or p['ip_address']
        ip = p['ip_address']
        serial = p['serial_number'] or ""
        location = p['location'] or ""
        model = p['model'] or ""
        manufacturer = p['manufacturer'] or ""

        first_log, last_log = database.get_monthly_data(printer_id, month, year)
        prev_last = database.get_previous_month_last_log(printer_id, month, year)

        # Determinar lecturas actuales
        if last_log:
            current_print = last_log['total_print'] or 0
            current_copy = last_log['total_copy'] or 0
            mac = last_log['mac_address'] or ""
            firmware = last_log['firmware'] or ""
        elif first_log:
            current_print = first_log['total_print'] or 0
            current_copy = first_log['total_copy'] or 0
            mac = first_log['mac_address'] or ""
            firmware = first_log['firmware'] or ""
        else:
            # Sin datos este mes
            continue

        # Base para cálculo de consumo
        if prev_last:
            base_print = prev_last['total_print'] or 0
            base_copy = prev_last['total_copy'] or 0
        else:
            # Si no hay mes anterior, usar primer registro del mes como base
            if first_log:
                base_print = first_log['total_print'] or 0
                base_copy = first_log['total_copy'] or 0
            else:
                base_print = 0
                base_copy = 0

        delta_print = max(0, current_print - base_print)
        delta_copy = max(0, current_copy - base_copy)

        row = {
            'id': printer_id,
            'name': name,
            'ip': ip,
            'serial': serial,
            'mac': mac,
            'location': location,
            'model': model,
            'manufacturer': manufacturer,
            'firmware': firmware,
            'current_print': int(current_print),
            'current_copy': int(current_copy),
            'delta_print': int(delta_print),
            'delta_copy': int(delta_copy)
        }

        data_rows.append(row)

        # Generar reporte individual
        safe_name = name.replace(' ', '_')
        individual_filename = os.path.join(reports_dir, f"report_{safe_name}_{year}_{month:02d}.pdf")
        try:
            reports.generate_individual_report(row, month, year, individual_filename)
            logger.info(f"Reporte individual generado: {individual_filename}")
        except Exception as e:
            logger.error(f"Error generando reporte individual para {name}: {e}")

    # Generar reporte global si hay datos
    if data_rows:
        global_filename = os.path.join(reports_dir, f"report_global_{year}_{month:02d}.pdf")
        try:
            reports.generate_global_report(data_rows, month, year, global_filename)
            logger.info(f"Reporte global generado: {global_filename}")
        except Exception as e:
            logger.error(f"Error generando reporte global: {e}")
