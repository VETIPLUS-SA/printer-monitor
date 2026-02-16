# Monitor de Impresoras SNMP

Este proyecto es un sistema modular para monitorear contadores de impresoras mediante SNMP (v2c y v3) y generar reportes mensuales en PDF.

## Características

*   **Soporte SNMP Flexible:** Compatible con SNMP v2c y v3 (Auth/Priv).
*   **Base de Datos SQLite:** Almacenamiento eficiente de históricos.
*   **Reportes PDF:** Generación automática de reportes con cálculo de consumo mensual.
*   **Tolerancia a Fallos:** El fallo de una impresora no detiene el monitoreo del resto.
*   **Arquitectura Modular:** Fácil de mantener y extender.

## Estructura del Proyecto

```text
printer-monitor/
├── config/             # Archivos de configuración
│   └── config.json     # Configuración de impresoras y OIDs
├── data/               # Almacenamiento de datos
│   └── database.db     # Base de datos SQLite (generada automáticamente)
├── docs/               # Documentación
├── logs/               # Registros de ejecución
├── printer_monitor/    # Código fuente principal (paquete Python)
│   ├── database.py     # Gestión de base de datos
│   ├── monitor.py      # Lógica de negocio
│   ├── reports.py      # Generador de PDF
│   └── snmp.py         # Cliente SNMP
├── scripts/            # Scripts de utilidad
│   └── seed_data.py    # Generador de datos de prueba
├── main.py             # Punto de entrada de la aplicación
└── requirements.txt    # Dependencias del proyecto
```

## Requisitos

*   Python 3.9+
*   Dependencias listadas en `requirements.txt`

## Instalación

1.  Clonar el repositorio o descargar el código.
2.  Crear un entorno virtual (recomendado):
    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/Mac
    venv\Scripts\activate     # Windows
    ```
3.  Instalar dependencias:
    ```bash
    pip install -r requirements.txt
    ```

## Configuración

Editar el archivo `config/config.json` para agregar las impresoras y definir los perfiles SNMP.

Ejemplo de `config/config.json`:
```json
{
  "printers": [
    {
      "ip": "192.168.1.100",
      "name": "Impresora_RRHH",
      "location": "Piso 2",
      "profile": "kyocera_generic",
      "version": 3,
      "auth": {
        "username": "admin",
        "auth_key": "authpass",
        "priv_key": "privpass",
        "auth_proto": "SHA",
        "priv_proto": "AES"
      }
    }
  ],
  "profiles": {
    "kyocera_generic": {
      "oids": { ... }
    }
  }
}
```

## Uso

El script `main.py` es el punto de entrada principal.

### Ejecutar Escaneo (Recolección de datos)
Ejecutar periódicamente (ej. cronjob diario/semanal):
```bash
python main.py --scan
```

### Generar Reporte Mensual
Genera un PDF con el consumo del mes actual:
```bash
python main.py --report
```

### Ambos (Escaneo + Reporte)
```bash
python main.py
```

## Desarrollo

### Datos de Prueba
Para verificar el funcionamiento sin esperar a recolectar datos reales, puedes poblar la base de datos con datos ficticios:
```bash
python scripts/seed_data.py
```
Esto creará una impresora de prueba e insertará registros para el mes actual y el anterior.
