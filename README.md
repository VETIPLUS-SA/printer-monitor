# Extractor de contadores Kyocera

Automatiza con Playwright la extracción mensual de los contadores de trabajos
(impresión, copia, escaneo, fax) por cuenta de usuario desde el portal web
(Command Center RX) de una impresora Kyocera, y los guarda en un CSV.

Este proyecto reemplaza por completo la versión anterior basada en SNMP
(`printer_monitor/snmp.py`, `database.py`, `monitor.py`, `reports.py`): el
portal SNMP no exponía los contadores por usuario, solo totales del equipo.

**Estado actual: alcance completo por ahora.** Además de la extracción, el
script mantiene un histórico de consumo mensual por impresora
(`consumo_mensual.csv`), que reemplaza a las fases 2 y 3 descritas en
`brief.md`.

## Advertencia de seguridad

El script opera con una sesión de **administrador** sobre una impresora en
**producción**. Es de **solo lectura** por diseño:

- Un guard (`printer_monitor/safety.py`) intercepta **todas** las peticiones
  de red del navegador. Solo deja pasar las páginas de consulta necesarias
  (lista de cuentas, detalle de contadores, totales del equipo) y el POST de
  login/logout. Cualquier otra cosa —en particular la página de **reinicio de
  contadores** (`MngSet_JobAcc_ResetCnt`) y el formulario de **borrado de
  cuentas** (`MngSet_Acc_DeleteRslt`)— se bloquea y se aborta, sin excepción.
- Tras iniciar sesión, el script no hace clic en ningún otro control que no
  sea "Desconexión" (`#Logout`). Toda la navegación restante es a URLs
  construidas por el propio código, nunca a través de checkboxes, `select`,
  envío de formularios ni teclado.
- Si alguna petición llega a ser bloqueada por el guard durante una corrida,
  el proceso termina con código de salida `2` y se muestra una advertencia
  clara en consola y en el log. Eso nunca implica que se haya reseteado o
  borrado nada: significa que el guard interceptó el intento antes de que
  llegara al servidor.

Los tests de `tests/test_safety.py` verifican explícitamente que las páginas
de reinicio/borrado quedan bloqueadas y que todas las URLs que el propio
extractor construye quedan permitidas.

## Instalación

Requiere Python 3.10+ (probado con 3.14) y un entorno virtual.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
python -m playwright install chromium
```

Para desarrollo (incluye `pytest`):

```bash
pip install -r requirements-dev.txt
```

## Configuración

La configuración se hace por variables de entorno, o mediante un archivo
`.env` en la raíz del proyecto (nunca commitear este archivo; ya está en
`.gitignore`).

| Variable             | Obligatoria | Descripción                                                        | Valor por defecto |
|-----------------------|:-----------:|----------------------------------------------------------------------|--------------------|
| `KYOCERA_URL`          | Sí *        | URL base del portal, ej. `https://192.168.1.59/`                     | —                  |
| `KYOCERA_USER`         | Sí *        | Usuario administrador del portal                                     | —                  |
| `KYOCERA_PASSWORD`     | Sí *        | Contraseña del usuario administrador                                 | —                  |
| `KYOCERA_OUTDIR`       | No          | Carpeta de salida (CSV, PDFs, diagnósticos, logs)                    | `output`           |
| `KYOCERA_DELAY_MS`     | No          | Espera entre peticiones al portal, en milisegundos                    | `700`              |
| `KYOCERA_TIMEOUT_MS`   | No          | Timeout por navegación, en milisegundos                              | `20000`            |

\* Obligatorias solo en el modo de **una sola impresora** (ver abajo). En el
modo de **varias impresoras**, `KYOCERA_USER`/`KYOCERA_PASSWORD` pasan a ser
opcionales: sirven como credenciales compartidas de respaldo.

Ejemplo de archivo `.env` (una sola impresora):

```
KYOCERA_URL=https://192.168.1.59/
KYOCERA_USER=admin
KYOCERA_PASSWORD=cambia-esto
KYOCERA_OUTDIR=output
KYOCERA_DELAY_MS=700
```

El portal usa un certificado autofirmado (HTTPS); el script ignora ese error
de certificado de forma intencional (`ignore_https_errors`), igual que hace
cualquier navegador cuando el usuario acepta la excepción manualmente.

### Varias impresoras

El script puede manejar varias impresoras en una sola corrida, cada una con
sus propias credenciales (o compartiendo las credenciales por defecto).
Basta con agregar `KYOCERA_PRINTERS` al `.env`:

```
KYOCERA_PRINTERS=pedidos,cartera,bodega
KYOCERA_USER=Admin            # credenciales compartidas de respaldo
KYOCERA_PASSWORD=cambia-esto

KYOCERA_PEDIDOS_URL=https://192.168.1.59/
KYOCERA_PEDIDOS_USER=Admin
KYOCERA_PEDIDOS_PASSWORD=cambia-esto-pedidos

KYOCERA_CARTERA_URL=https://192.168.1.104/
KYOCERA_CARTERA_USER=otro_usuario
KYOCERA_CARTERA_PASSWORD=cambia-esto-cartera

KYOCERA_BODEGA_URL=https://192.168.1.162/   # sin USER/PASSWORD propios -> usa los compartidos
```

Reglas:

- `KYOCERA_PRINTERS` es una lista separada por comas de nombres cortos
  (solo letras, dígitos y guion bajo; mayúsculas/minúsculas no importan;
  entradas vacías se ignoran; nombres repetidos, aunque difieran en
  mayúsculas, son un error de configuración).
- Cada nombre define un prefijo `KYOCERA_<NOMBRE EN MAYÚSCULAS>_` para sus
  propias variables: `<PREFIJO>URL` (obligatoria), `<PREFIJO>USER` y
  `<PREFIJO>PASSWORD` (opcionales).
- Si una impresora no define su propio `USER`/`PASSWORD`, cada uno cae de
  forma **independiente** al compartido (`KYOCERA_USER`/`KYOCERA_PASSWORD`):
  una impresora puede heredar el usuario pero tener su propia contraseña, o
  viceversa.
- Si a una impresora le falta la URL, o le faltan usuario/contraseña sin
  tener un valor compartido de respaldo, la corrida **no arranca ninguna
  impresora**: se reporta el error de configuración (nombrando la variable
  exacta que falta) y el proceso termina con código de salida `1`, sin
  conectarse a ningún equipo.
- **Modo de una sola impresora**: si `KYOCERA_PRINTERS` no está definida (o
  está vacía), el comportamiento es exactamente el de antes: una sola
  impresora, llamada `default`, construida desde `KYOCERA_URL` /
  `KYOCERA_USER` / `KYOCERA_PASSWORD`. Los `.env` existentes siguen
  funcionando sin cambios.
- `KYOCERA_OUTDIR`, `KYOCERA_DELAY_MS` y `KYOCERA_TIMEOUT_MS` son
  compartidas por todas las impresoras.

Para correr solo algunas impresoras, usa `--printer NAME` (repetible,
insensible a mayúsculas):

```bash
python main.py extract --printer pedidos --printer bodega
python main.py extract --printer Pedidos   # equivalente, no distingue mayúsculas
```

Un nombre que no esté configurado hace terminar el proceso con código de
salida `1`, listando los nombres configurados. Sin `--printer`, se corren
**todas** las impresoras configuradas.

Las impresoras se procesan **una por una**, cada una con su propia sesión
de navegador. **Si una impresora falla (apagada, inalcanzable, error de
login, etc.), la corrida sigue con las demás**: el fallo se registra en el
log con el nombre de esa impresora y aparece en el resumen final, pero
nunca detiene a las otras. Por eso, antes de agregar una impresora nueva
(sobre todo si es un modelo distinto de Kyocera, cuyo portal podría diferir
de lo que este script espera) conviene probarla primero de forma aislada y
sin escribir nada:

```bash
python main.py extract --dry-run --printer nueva_impresora
```

Salidas por impresora, dentro de la misma carpeta de salida (ver también la
sección "Salidas" más abajo, que describe el detalle de cada archivo):

- `counters_<IP>_<fecha>.csv`: un CSV por impresora y corrida (el nombre de
  archivo ya no colisiona entre impresoras porque incluye la IP).
- `pdf/<IP>/<AAAA-MM>/`: los PDFs de cada impresora, igual que en el modo de
  una sola impresora.
- `consumo_mensual.csv`: una fila por (mes, impresora); además de
  `device_ip`, cada fila trae la columna `printer_name` con el nombre
  configurado (`pedidos`, `cartera`, etc., o `default` en modo de una sola
  impresora).

Al final de la corrida se imprime un resumen con una línea por impresora
(nombre, IP y estado: `ok`, `N account error(s)`, `failed: <motivo>` o
`skipped: ...` si el guard de seguridad bloqueó algo).

## Uso

```bash
python main.py extract                 # corrida normal: todas las impresoras configuradas
python main.py extract --dry-run       # recorre todo pero no escribe nada
python main.py extract --headed        # con ventana visible, para depurar
python main.py extract --pdf           # además del CSV, un PDF por cuenta
python main.py extract --outdir salida # carpeta de salida distinta
python main.py extract --month 2026-09 # fija el mes del reporte
python main.py extract --printer pedidos --printer bodega  # solo estas impresoras
```

- `--dry-run` recorre todas las cuentas y lee los contadores, pero **no
  escribe ningún archivo**: ni CSV, ni PDF, ni diagnósticos, ni log en disco
  (solo consola). Sirve para probar la configuración sin dejar rastro. Al
  ser `--dry-run`, tampoco se actualiza `consumo_mensual.csv`.
- `--pdf` solo funciona en modo headless (sin `--headed`); si se combinan
  ambas banderas, se omite la generación de PDFs y se avisa por log. Un
  fallo al generar un PDF nunca hace fallar la fila del CSV de esa cuenta.
- `--outdir` sobrescribe `KYOCERA_OUTDIR`.
- `--month AAAA-MM` fija el "mes del reporte": determina la carpeta mensual
  de los PDFs y la fila que se actualiza en `consumo_mensual.csv`. Por
  defecto es el mes de la fecha de captura (hora local). Útil, por ejemplo,
  al correr el script el día 1 del mes para registrar el cierre del mes
  anterior: `python main.py extract --month 2026-08`. Se aplica igual a
  todas las impresoras de la corrida.
- `--printer NAME` (repetible, insensible a mayúsculas): corre solo esas
  impresoras en vez de todas las configuradas. Ver "Varias impresoras" más
  arriba.

### Salidas

Con una corrida normal, dentro de la carpeta de salida (`output/` por
defecto):

```
output/
├── counters_<IP>_YYYYMMDD_HHMMSS.csv  # una fila por cuenta, una por impresora y corrida
├── consumo_mensual.csv             # histórico de consumo mensual (no en --dry-run)
├── pdf/                             # solo con --pdf
│   └── <IP de la impresora>/
│       └── <AAAA-MM>/
│           └── <NOMBRE>.pdf         # p. ej. pdf/192.168.1.59/2026-09/CAROLINA MEJIA.pdf
├── diagnostics/                    # solo si alguna cuenta falla
│   └── <timestamp>/<account_id>_*.png / *.html
└── logs/
    └── extract_YYYYMMDD_HHMMSS.log
```

Con varias impresoras, todo va a la misma carpeta de salida: el nombre del
CSV incluye la IP para no colisionar entre impresoras, y los PDFs ya se
organizaban por IP desde antes.

El CSV se guarda en UTF-8 con BOM para que Excel en Windows muestre bien los
acentos. Columnas principales: `captured_at`, `device_ip`, `printer_name`
(el nombre configurado de la impresora, o `default` en modo de una sola
impresora), `account_id`, `account_private_id`, `account_name`, los
contadores de impresión/copia (`copier_total`, `printer_total`, `duplex_*`,
`combine_*`), escaneo (`scan_*`), fax (`fax_tx_pages`, `fax_tx_time`) y
`status`/`error`. Además de las cuentas nombradas, siempre hay una fila
`OTHER` (cuenta "Otra cuenta", id interno `101`) y una fila `TOTAL`
(totales del equipo).

Si falla la lectura de una cuenta puntual, esa fila queda con `status=error`
y el mensaje en `error`, pero **la corrida sigue con las demás cuentas**: un
fallo nunca hace perder los datos de las otras. Lo mismo aplica entre
impresoras: si una impresora completa falla, las demás de la corrida siguen
normalmente (ver "Varias impresoras" más arriba).

Los nombres de archivo PDF van en mayúsculas y sin tildes, pero **conservan
la Ñ** (p. ej. "Eliana Sánchez Muñoz" → `ELIANA SANCHEZ MUÑOZ.pdf`). La
carpeta `<AAAA-MM>` es el "mes del reporte" (ver `--month`), no la fecha
exacta de la corrida. Si dos cuentas comparten el mismo nombre normalizado
dentro de esa carpeta, al segundo archivo se le agrega el id de cuenta entre
paréntesis (p. ej. `JUAN PEREZ (2222).pdf`) para no sobrescribir el primero.

### Consumo mensual (`consumo_mensual.csv`)

Cada corrida normal (no `--dry-run`) actualiza `consumo_mensual.csv` en la
carpeta de salida: un histórico con **una fila por (mes, impresora)**, en
UTF-8 con BOM. Columnas:

| Columna         | Significado                                                                 |
|------------------|------------------------------------------------------------------------------|
| `month`          | Mes del reporte, `AAAA-MM` (ver `--month`)                                  |
| `device_ip`      | IP/host de la impresora                                                     |
| `printer_name`   | Nombre configurado de la impresora (`pedidos`, `default`, etc.)             |
| `captured_at`    | Fecha/hora de la corrida que generó esta fila                               |
| `printer_total`, `copier_total`, `scan_total`, `fax_tx_pages` | Contadores **acumulados** del equipo (fila `TOTAL` de esa corrida) |
| `printer_pages`, `copier_pages`, `scanned_pages`, `fax_pages` | Consumo **de ese mes** (delta contra el mes anterior más reciente con datos) |
| `printed_pages`  | `printer_pages + copier_pages`: total de páginas impresas en el mes         |
| `note`           | Vacío en el caso normal; explica el caso especial (ver abajo)               |

- **Línea base**: el primer mes registrado para una impresora no tiene mes
  anterior con qué compararse, así que las columnas de consumo quedan vacías
  y `note` dice `baseline: no previous month to compare`.
- **Reinicio de contadores detectado**: si algún contador acumulado bajó
  respecto al mes anterior (la impresora reseteó sus contadores), esa
  columna de consumo queda **vacía** (nunca un número negativo) y `note`
  dice `counter reset detected: <columnas afectadas>`. `printed_pages`
  también queda vacío si `printer_pages` o `copier_pages` están vacíos.
- Si se vuelve a correr el script para el mismo mes y la misma impresora, la
  fila de ese mes se **reemplaza** (gana la corrida más reciente) y se
  recalculan los consumos de todos los meses de esa impresora en orden, para
  que una corrección también corrija el delta del mes siguiente.
- Si la fila `TOTAL` de la corrida falla (`status != ok`), el archivo **no
  se toca** y esa impresora se reporta como fallida (ver "Códigos de
  salida" más abajo).
- `printer_name` es una columna agregada de forma aditiva: un
  `consumo_mensual.csv` generado antes de esta funcionalidad, sin esa
  columna, se sigue leyendo sin problema (las filas viejas quedan con
  `printer_name` vacío hasta que se vuelvan a correr).

### Códigos de salida

El código de salida se calcula sobre **todas las impresoras** de la corrida
(o las seleccionadas con `--printer`):

| Código | Significado                                                                              |
|--------|--------------------------------------------------------------------------------------------|
| `0`    | Todas las impresoras corrieron sin ningún error de cuenta                                  |
| `1`    | Error de configuración, o al menos una impresora tuvo un error fatal del portal / falló / tuvo alguna cuenta con `status=error` |
| `2`    | El guard de seguridad bloqueó al menos una petición en al menos una impresora durante la corrida |

Al final de cada corrida se imprime un resumen de una línea por impresora
(nombre, IP, estado) en el log, independientemente del código de salida.

## La particularidad del Referer

El servidor del portal responde `404` a las URLs de detalle bajo `/mngset/`
si la petición no lleva la cabecera `Referer: <URL_BASE>/startwlm/login.cgi`,
incluso dentro de la misma sesión ya autenticada. Por eso toda navegación a
esas páginas se hace con `frame.goto(url, referer=...)` pasando ese Referer
explícitamente. Ver `docs/fase0-hallazgos.md` para el detalle completo de los
hallazgos de reconocimiento (estructura de frames, URLs confirmadas,
etiquetas exactas de cada contador) contra los que está construido este
script.

El servidor embebido del portal también es frágil ante ráfagas de peticiones
("socket hang up"); por eso hay una espera (`KYOCERA_DELAY_MS`) entre
navegaciones y reintentos con backoff (2s, 4s, 8s) ante errores de red,
timeouts o respuestas 5xx.

## Desarrollo y tests

Los tests son 100% offline (no requieren red ni Playwright en ejecución) y
usan datos sintéticos, nunca nombres reales de `recon/`:

```bash
python -m pytest -q
```

- `tests/test_safety.py`: el guard de solo lectura bloquea reinicio/borrado
  y permite toda URL que el extractor construye.
- `tests/test_parsing.py`: mapeo de filas de la tabla renderizada a columnas
  del CSV, incluyendo la etiqueta duplicada "Total" y espacios de no
  separación (`\xa0`).
- `tests/test_output.py`: orden de columnas del CSV (incluida
  `printer_name`), ceros a la izquierda en `account_id`, filas de error, y
  que el nombre de archivo incluye la IP para no colisionar entre
  impresoras.
- `tests/test_pdf_paths.py`: nombres de archivo PDF (tildes fuera, Ñ
  conservada, caracteres inválidos de Windows) y la carpeta mensual.
- `tests/test_consumption.py`: `consumo_mensual.csv` -- línea base, delta
  normal, `printed_pages`, reset de contadores, upsert del mismo mes con
  recálculo del mes siguiente, impresoras independientes, meses con huecos,
  fila `TOTAL` con error, y la columna `printer_name` (incluida su
  compatibilidad con archivos históricos que no la tienen).
- `tests/test_config.py`: modo de una sola impresora (legado), varias
  impresoras con credenciales propias, la caída independiente a las
  credenciales compartidas, errores de configuración (URL faltante,
  credenciales faltantes sin respaldo, nombre inválido, nombre duplicado),
  que el `repr` de `Settings` nunca expone la contraseña, y que los tests
  nunca leen el `.env` real (siempre pasan un `env` explícito).
- `tests/test_run.py`: agregación pura del resultado por impresora --
  código de salida y tabla de resumen -- con filas sintéticas, sin
  Playwright.

## Herramienta de reconocimiento (Fase 0)

`tools/recon_kyocera.py` fue el script usado para confirmar la estructura
real del portal antes de escribir el extractor (ver
`docs/fase0-hallazgos.md`). Se conserva en el repositorio como referencia y
para volver a usarlo si el firmware del portal cambia; también es de solo
lectura.

## Alcance del proyecto

El alcance está completo por ahora: extracción de contadores por cuenta
(Fase 1) más el histórico de consumo mensual por impresora
(`consumo_mensual.csv`, ver arriba), que reemplaza lo que `brief.md`
describía como fases 2 y 3.
