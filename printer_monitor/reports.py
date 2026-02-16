from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from datetime import datetime

def get_header_style():
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.gray
    )
    return header_style

def get_centered_style():
    styles = getSampleStyleSheet()
    centered_style = ParagraphStyle(
        'Centered',
        parent=styles['Normal'],
        alignment=TA_CENTER
    )
    return centered_style

def generate_individual_report(data, month, year, output_filename):
    """
    Genera un reporte PDF individual para una impresora.
    """
    doc = SimpleDocTemplate(output_filename, pagesize=A4,
                            rightMargin=40, leftMargin=40,
                            topMargin=40, bottomMargin=40)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # --- Título ---
    title = Paragraph(f"Reporte Individual de Impresora", styles['Title'])
    subtitle = Paragraph(f"Periodo: {month}/{year}", styles['Heading2'])
    elements.append(title)
    elements.append(subtitle)
    elements.append(Spacer(1, 1 * cm))
    
    # --- Datos de Identificación ---
    # Usamos una tabla para alinear bonito los datos clave
    id_data = [
        [Paragraph("<b>Nombre del Dispositivo:</b>", styles['Normal']), data['name']],
        [Paragraph("<b>Ubicación:</b>", styles['Normal']), data['location']],
        [Paragraph("<b>Modelo:</b>", styles['Normal']), data.get('model', 'N/A')],
        [Paragraph("<b>Fabricante:</b>", styles['Normal']), data.get('manufacturer', 'N/A')],
        [Paragraph("<b>Versión de Firmware:</b>", styles['Normal']), data.get('firmware', 'N/A')],
        [Paragraph("<b>Número de Serie:</b>", styles['Normal']), data['serial']],
        [Paragraph("<b>Dirección IP:</b>", styles['Normal']), data['ip']],
        [Paragraph("<b>Dirección MAC:</b>", styles['Normal']), data['mac']]
    ]
    
    id_table = Table(id_data, colWidths=[6*cm, 10*cm])
    id_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(id_table)
    elements.append(Spacer(1, 1 * cm))
    
    # --- Métricas ---
    elements.append(Paragraph("Métricas de Rendimiento", styles['Heading2']))
    
    # Preparamos datos numéricos
    c_print = f"{data['current_print']:,}"
    c_copy = f"{data['current_copy']:,}"
    d_print = f"{data['delta_print']:,}"
    d_copy = f"{data['delta_copy']:,}"
    
    metrics_data = [
        ["Concepto", "Lectura Actual", "Consumo del Mes"],
        ["Impresiones", c_print, d_print],
        ["Copias", c_copy, d_copy],
        ["Total", f"{(data['current_print'] + data['current_copy']):,}", f"{(data['delta_print'] + data['delta_copy']):,}"]
    ]
    
    metrics_table = Table(metrics_data, colWidths=[6*cm, 5*cm, 5*cm])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey), # Fila de total
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(metrics_table)
    
    # --- Footer ---
    elements.append(Spacer(1, 2 * cm))
    date_str = datetime.now().strftime('%d-%m-%Y %H:%M')
    footer = Paragraph(f"Generado automáticamente el {date_str}", get_header_style())
    elements.append(footer)
    
    doc.build(elements)

def generate_global_report(data_rows, month, year, output_filename):
    """
    Genera un PDF global con tabla resumen.
    """
    doc = SimpleDocTemplate(output_filename, pagesize=landscape(A4),
                            rightMargin=20, leftMargin=20,
                            topMargin=30, bottomMargin=30)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # --- Título ---
    title = Paragraph(f"Reporte Global de Flota - {month}/{year}", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 0.5 * cm))
    
    # --- Tabla ---
    # Headers solicitados: Nombre, Serial, IP, MAC, Tot Print, Tot Copy, Delta Print, Delta Copy
    headers = [
        "Impresora", "Serial", "IP", "MAC",
        "Total\nPrint", "Total\nCopy",
        "Consumo (mes)\nPrint", "Consumo (mes)\nCopy"
    ]
    
    table_data = [headers]
    
    # Totales
    total_c_print = 0
    total_c_copy = 0
    total_d_print = 0
    total_d_copy = 0
    
    for row in data_rows:
        # Acumular totales acumulativos y consumo del mes
        total_c_print += row['current_print']
        total_c_copy += row['current_copy']
        total_d_print += row['delta_print']
        total_d_copy += row['delta_copy']
        
        # Formatear
        row_cells = [
            Paragraph(f"<b>{row['name']}</b>", styles['Normal']),
            row['serial'],
            row['ip'],
            row['mac'],
            f"{row['current_print']:,}",
            f"{row['current_copy']:,}",
            f"{row['delta_print']:,}",
            f"{row['delta_copy']:,}"
        ]
        table_data.append(row_cells)
        
    # Fila final de totales
    centered = get_centered_style()
    table_data.append([
        Paragraph(f"<b>TOTALES GLOBALES</b>", centered), 
        Paragraph(f"<b>FLOTA</b>", centered), 
        "", 
        "",
        Paragraph(f"<b>{total_c_print:,}</b>", centered),
        Paragraph(f"<b>{total_c_copy:,}</b>", centered),
        Paragraph(f"<b>{total_d_print:,}</b>", centered),
        Paragraph(f"<b>{total_d_copy:,}</b>", centered)
    ])
    
    # Ajustar anchos de columna para que quepa en landscape
    # A4 Landscape width ~29.7cm. Margins 2cm each side -> ~25cm available
    col_widths = [
        4.5*cm, # Nombre
        3.0*cm, # Serial
        3.0*cm, # IP
        3.5*cm, # MAC
        2.5*cm, # Tot Print
        2.5*cm, # Tot Copy
        2.5*cm, # Delta Print
        2.5*cm  # Delta Copy
    ]
    
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,-1), (-1,-1), colors.lightgrey),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,-1), (-1,-1), 'CENTER'),  # Centrar contenido de fila de totales
        ('VALIGN', (0,-1), (-1,-1), 'MIDDLE'),  # Alinear verticalmente fila de totales
        ('FONTSIZE', (0,-1), (-1,-1), 10),  # Tamaño de fuente un poco más grande
    ]))
    
    elements.append(t)
    
    # --- Footer ---
    elements.append(Spacer(1, 1 * cm))
    footer = Paragraph(f"Generado el: {datetime.now().strftime('%d-%m-%Y %H:%M')}", get_header_style())
    elements.append(footer)
    
    doc.build(elements)
