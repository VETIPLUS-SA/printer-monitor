import asyncio
from pysnmp.hlapi.v3arch.asyncio import *
import logging
import re

# Configurar logging específico para SNMP
logger = logging.getLogger("snmp_client")

def extract_device_info(device_string):
    """
    Extrae componentes del string device_info de Kyocera.
    Formato: "ID:ECOSYS M3655idn;MFG:Kyocera;CMD:...;MDL:ECOSYS M3655idn;...;SER:R4P9X43764;"
    Retorna dict con: model, manufacturer, serial, description
    """
    info = {}
    try:
        # Extraer componentes del string
        parts = device_string.split(';')
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                if key == 'MDL':
                    info['model'] = value.strip()
                elif key == 'MFG':
                    info['manufacturer'] = value.strip()
                elif key == 'SER':
                    info['serial'] = value.strip()
                elif key == 'DES':
                    info['description'] = value.strip()
                elif key == 'ID':
                    info['id'] = value.strip()
        
        logger.info(f"Device info extraído: {info}")
        return info
    except Exception as e:
        logger.error(f"Error extracting device info: {e}")
        return {}

def format_mac_address(mac_bytes):
    """
    Convierte bytes o OctetString a formato AA:BB:CC:DD:EE:FF
    Maneja múltiples formatos:
    - Hex string con prefijo 0x: "0x0017c890e412"
    - Hex string sin separadores: "0017C890E412"
    - Hex string con espacios: "00 17 C8 90 E4 12"
    - Bytes de pysnmp
    """
    if not mac_bytes:
        return "00:00:00:00:00:00"
    
    try:
        mac_str = str(mac_bytes)
        logger.debug(f"format_mac_address input: {repr(mac_str)}, length: {len(mac_str)}")
        
        # Remover prefijo "0x" si existe
        if mac_str.lower().startswith('0x'):
            mac_str = mac_str[2:]
            logger.debug(f"After removing 0x prefix: {repr(mac_str)}")
        
        # Si contiene espacios (formato "00 17 C8 90 E4 12"), convertir a AA:BB:CC:DD:EE:FF
        if ' ' in mac_str:
            parts = mac_str.split()
            if all(len(p) == 2 for p in parts):
                result = ":".join(parts).upper()
                logger.debug(f"format_mac_address (space format) -> {result}")
                return result
        
        # Si es string hexadecimal sin separadores (ej: "0017C890E412"), agregar dos puntos cada 2 caracteres
        if len(mac_str) == 12 and all(c in '0123456789ABCDEFabcdef' for c in mac_str):
            result = ":".join(mac_str[i:i+2] for i in range(0, 12, 2)).upper()
            logger.debug(f"format_mac_address (hex format) -> {result}")
            return result
        
        # Si es un objeto de pysnmp, intentar obtener su valor crudo
        if hasattr(mac_bytes, 'asOctets'):
            mac_bytes = mac_bytes.asOctets()
            if isinstance(mac_bytes, bytes):
                result = ":".join("{:02X}".format(b) for b in mac_bytes)
                logger.debug(f"format_mac_address (pysnmp bytes) -> {result}")
                return result
        
        # Si ya es bytes
        if isinstance(mac_bytes, bytes):
            result = ":".join("{:02X}".format(b) for b in mac_bytes)
            logger.debug(f"format_mac_address (bytes) -> {result}")
            return result
        
        # Fallback: limpiar string
        cleaned = mac_str.replace(" ", ":").replace("0x", "").upper()
        logger.debug(f"format_mac_address (fallback) -> {cleaned}")
        return cleaned
        
    except Exception as e:
        logger.error(f"Error formatting MAC: {e}")
        return "Unknown"

async def get_snmp_data_async(ip, config, oids_map):
    """
    Versión asíncrona de la consulta SNMP
    """
    # 1. Configurar Auth Data
    if config.get('version') == 3:
        auth = config.get('auth', {})
        # Mapeo de protocolos
        auth_proto_map = {
            'MD5': usmHMACMD5AuthProtocol,
            'SHA': usmHMACSHAAuthProtocol,
            'SHA224': usmHMAC128SHA224AuthProtocol,
            'SHA256': usmHMAC192SHA256AuthProtocol,
            'SHA384': usmHMAC256SHA384AuthProtocol,
            'SHA512': usmHMAC384SHA512AuthProtocol,
            'NONE': usmNoAuthProtocol
        }
        priv_proto_map = {
            'DES': usmDESPrivProtocol,
            'AES': usmAesCfb128Protocol,
            'AES128': usmAesCfb128Protocol,
            'AES192': usmAesCfb192Protocol,
            'AES256': usmAesCfb256Protocol,
            'NONE': usmNoPrivProtocol
        }

        user_data = UsmUserData(
            auth.get('username'),
            auth.get('auth_key'),
            auth.get('priv_key'),
            authProtocol=auth_proto_map.get(auth.get('auth_proto', 'NONE'), usmNoAuthProtocol),
            privProtocol=priv_proto_map.get(auth.get('priv_proto', 'NONE'), usmNoPrivProtocol)
        )
    else:
        # Default to v2c
        community = config.get('community', 'public')
        user_data = CommunityData(community, mpModel=1) # mpModel=1 es v2c

    target = await UdpTransportTarget.create((ip, 161))
    target.timeout = 2
    target.retries = 1
    engine = SnmpEngine()
    results = {}

    for name, oid_str in oids_map.items():
        try:
            # get_cmd es awaitable en asyncio
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                engine,
                user_data,
                target,
                ContextData(),
                ObjectType(ObjectIdentity(oid_str))
            )

            if errorIndication:
                logger.error(f"Error SNMP en {ip} para {name}: {errorIndication}")
                results[name] = None
            elif errorStatus:
                logger.error(f"Error estado SNMP en {ip}: {errorStatus.prettyPrint()}")
                results[name] = None
            else:
                for varBind in varBinds:
                    val = varBind[1]
                    val_str = str(val.prettyPrint())
                    
                    # Procesar device_info (string con datos estructurados)
                    if name == 'device_info':
                        results[name] = val_str
                    # Procesar MAC en formato Hex-STRING
                    elif name == 'mac_address':
                        results[name] = format_mac_address(val_str)
                    elif name == 'uptime':
                        results[name] = val_str
                    elif name in ['firmware', 'model', 'manufacturer', 'description', 'id']:
                        results[name] = val_str
                    else:
                        # Intentar como número, sino guardar como string
                        try:
                            results[name] = int(val)
                        except (ValueError, TypeError):
                            results[name] = val_str
                             
        except Exception as e:
            logger.error(f"Excepción consultando {name} en {ip}: {str(e)}")
            results[name] = None
    
    # PASO CRÍTICO: Extraer serial del device_info si existe
    if results.get('device_info'):
        device_info = extract_device_info(results['device_info'])
        
        # Agregar datos extraídos al resultado
        if device_info.get('serial'):
            results['serial_number'] = device_info['serial']
        if device_info.get('model'):
            results['model'] = device_info['model']
        if device_info.get('manufacturer'):
            results['manufacturer'] = device_info['manufacturer']
        if device_info.get('description'):
            results['description'] = device_info['description']
            
    engine.closeDispatcher()
    return results

def get_snmp_data(ip, config, oids_map):
    """
    Wrapper síncrono para ser llamado desde main.py
    """
    return asyncio.run(get_snmp_data_async(ip, config, oids_map))
