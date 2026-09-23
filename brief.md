# Brief de implementación: extracción de contadores Kyocera

## Objetivo

Automatizar con Playwright (Python) la extracción mensual de los contadores de
trabajos por usuario desde el portal web de una impresora Kyocera, guardar un
histórico y calcular el consumo del período para un reporte.

Frecuencia: **mensual**. No se requiere un servicio permanente; basta un script
invocable a mano o desde una tarea programada.

## Contexto: flujo manual actual

Este es el recorrido que hace hoy una persona. Los textos entre comillas son los
literales que aparecen en pantalla (portal en español).

1. Abrir `http://<IP_IMPRESORA>` (HTTP, sin TLS).
2. Clic en "Inicio de sesión de administrador".
3. Diligenciar usuario y contraseña, clic en "Inicio de sesión".
4. Se habilitan secciones nuevas; entrar a "Configuración de administración".
5. En el submenú, entrar a "Contabilidad de trabajos".
6. Se muestra la lista paginada de personas con acceso a la impresora.
7. Frente a cada persona hay un botón "Contador"; al darle clic se abre el
   detalle de conteo de esa persona.
8. Se imprime ese detalle a PDF (Ctrl + P) y se vuelve atrás.

**Limitación conocida:** el botón de volver atrás siempre regresa a la página 1
de la lista. Si se estaba en la página 2 o posterior, hay que re-navegar la
paginación antes de continuar con la siguiente persona.

## Fase 0 — Reconocimiento (hacer ANTES de escribir el script)

No escribas la implementación hasta reportar los hallazgos de esta fase. Usa
`playwright codegen http://<IP>` o una sesión `--headed` con pausas, e
investiga:

1. **Estructura del DOM**: ¿el portal usa framesets/iframes? El firmware
   antiguo de Command Center RX sí; eso obliga a usar `frame_locator` en vez de
   selectores sobre la página principal.
2. **URL del detalle de contador**: al hacer clic en "Contador", ¿cambia la URL
   y contiene un identificador de cuenta/usuario? Si es así, se puede navegar
   directo a cada detalle y **el problema de la paginación desaparece**. Si el
   botón dispara un POST o JavaScript sin URL estable, hay que replicar la
   navegación con manejo de paginación.
3. **Exportación nativa**: revisar si en "Contabilidad de trabajos" existe algún
   botón de exportar o descargar la lista. Si existe y trae los contadores, úsalo:
   es más estable que raspar y reduce el alcance del scraping drásticamente.
4. **Estructura del detalle**: qué métricas trae el detalle por persona
   (impresión, copia, escaneo, fax; B/N vs color; total de páginas). Documentar
   los nombres de campo exactos.
5. **Sesión**: cuánto dura antes de expirar y si hay que cerrar sesión
   explícitamente al final para no dejar la sesión de administrador colgada.
6. **Selectores estables**: preferir `name`, `id` o texto visible sobre rutas
   XPath posicionales, que se rompen con cualquier cambio de firmware.

Entrega de esta fase: un resumen de hallazgos y la ruta de navegación
confirmada, más una recomendación de si conviene URL directa o paginación.

## Fase 1 — Script de extracción

Requisitos:

- Python + Playwright (sync API). Chromium.
- Configuración por variables de entorno o archivo `.env`: IP, usuario,
  contraseña, carpeta de salida. **Nunca hardcodear credenciales** ni
  commitearlas; incluir `.env` en `.gitignore` y dejar un `.env.example`.
- Flags de CLI: `--headed` (depuración), `--dry-run` (recorre sin escribir
  archivos), `--outdir`.
- Recolectar **primero** la lista completa de personas recorriendo todas las
  páginas, y solo después iterar sobre el detalle de cada una. Esto evita ir y
  volver de la lista al detalle, que es donde se pierde la paginación.
- Si la ruta directa por URL no es viable, implementar una función auxiliar
  `ir_a_pagina(n)` que se invoque tras cada regreso a la lista.
- Salida principal: **CSV normalizado** con una fila por persona y una columna
  por métrica, más columnas de fecha de captura e IP del equipo. Este es el
  dato que alimenta el reporte.
- Salida secundaria opcional (flag `--pdf`): el detalle de cada persona en PDF
  usando `page.pdf()`. Ctrl+P no es replicable desde Playwright, y `page.pdf()`
  solo funciona en Chromium headless.
- Manejo de errores: reintentos con espera en fallos de red, timeouts
  explícitos, y ante un fallo de selector guardar un screenshot de la página y
  el HTML para diagnóstico. Si una persona falla, registrar el error y
  continuar con las demás en vez de abortar toda la corrida.
- Logging a consola y a archivo, indicando progreso (persona N de M).

**Restricción crítica de seguridad:** el script opera con sesión de
administrador sobre un equipo en producción. Es de **solo lectura**. No debe
hacer clic en ningún botón de guardar, aplicar, restablecer, reiniciar ni
modificar configuración, ni en ningún control que resetee contadores. Ante un
selector ambiguo que pudiera activar una acción destructiva, abortar y reportar
en vez de adivinar.

## Fase 2 — Histórico y cálculo del período

Los contadores de la impresora son **acumulados desde el último reset**, no
mensuales. Por lo tanto:

- Guardar cada corrida como un snapshot inmutable: `snapshots/YYYY-MM.csv`.
  Nunca sobrescribir un snapshot existente sin confirmación explícita.
- Un módulo aparte calcula el consumo del período restando el snapshot anterior
  del actual, emparejando por identificador de usuario.
- Casos borde a manejar explícitamente: usuarios nuevos que no estaban en el
  snapshot anterior, usuarios que desaparecieron, y **deltas negativos**, que
  indican un reset de contadores en la impresora y deben marcarse en la salida
  en vez de reportarse como número negativo.
- Primera corrida: sin snapshot previo no hay delta; el script debe decirlo
  claramente y guardar solo la línea base.

## Fase 3 — Reporte

Independiente de Playwright. A partir del CSV de consumo del período, generar
la salida para entregar. El formato exacto está por definir; dejar esta capa
desacoplada para poder cambiarla sin tocar la extracción.

## Criterios de aceptación

- Una corrida completa produce el snapshot del mes con todas las personas de
  todas las páginas, sin faltantes por el problema de la paginación.
- El script corre sin intervención manual una vez configurado el `.env`.
- Un cambio de credenciales o de IP no requiere tocar código.
- Un fallo en una persona no pierde los datos de las demás.
- Existe un README corto con cómo instalar, configurar y ejecutar.

## Qué no hacer

- No inventar selectores basándose en cómo suele ser el Command Center RX:
  confirmarlos contra el portal real en la fase 0.
- No reemplazar el CSV estructurado por PDFs como salida principal.
- No implementar las fases 2 y 3 hasta que la fase 1 extraiga datos correctos y
  verificados contra una consulta manual de al menos dos personas.