import sys
import argparse
from printer_monitor import monitor

def main():
    parser = argparse.ArgumentParser(
        description='Monitor de Impresoras SNMP - Sistema de Gestión y Reportes',
        epilog='''Ejemplos de uso:
  python main.py --scan               # Escanear impresoras y guardar datos
  python main.py --report             # Generar reportes PDF del mes
  python main.py --list               # Ver inventario de impresoras
  python main.py --delete 5           # Borrar la impresora con ID 5
  python main.py --scan --report      # Escanear y generar reporte en una sola ejecución
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--scan', action='store_true', help='Ejecutar escaneo SNMP para actualizar contadores')
    parser.add_argument('--report', action='store_true', help='Generar reportes PDF (Individuales y Global) del mes actual')
    parser.add_argument('--list', action='store_true', help='Listar todas las impresoras registradas en la base de datos')
    parser.add_argument('--delete', type=int, metavar='ID', help='Eliminar una impresora y su historial usando su ID')
    
    # Si no hay argumentos, mostrar ayuda en lugar de ejecutar todo por defecto
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    else:
        args = parser.parse_args()
        
    if args.list:
        monitor.list_printers()
        return

    if args.delete:
        monitor.delete_printer(args.delete)
        return
        
    if args.scan:
        monitor.run_scan()
        
    if args.report:
        monitor.run_report()

if __name__ == "__main__":
    main()
