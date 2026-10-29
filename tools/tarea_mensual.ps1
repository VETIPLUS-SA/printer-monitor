# Corrida mensual que lanza la tarea programada PrinterMonitorMonthCount.
# Ejecuta `main.py extract -p --pdf` (cierre del mes anterior) y reintenta si falla.
#
# Códigos de salida de main.py: 0 = todo bien, 1 = alguna impresora o cuenta falló,
# 2 = el guard de seguridad bloqueó una petición. Solo se reintenta el 1: un 2 nunca
# se repite a ciegas, hay que revisarlo a mano.

param(
    [int]$Intentos = 3,
    [int]$EsperaMinutos = 15
)

$ErrorActionPreference = "Stop"

$proyecto = Split-Path -Parent $PSScriptRoot
$python = Join-Path $proyecto ".venv\Scripts\python.exe"
$logs = Join-Path $proyecto "output\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$sello = Get-Date -Format "yyyyMMdd_HHmmss"
$logTarea = Join-Path $logs "tarea_mensual_$sello.log"

function Write-Log([string]$mensaje) {
    $linea = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $mensaje
    Add-Content -Path $logTarea -Value $linea -Encoding UTF8
}

$env:PYTHONIOENCODING = "utf-8"
$codigo = 1

for ($intento = 1; $intento -le $Intentos; $intento++) {
    Write-Log "Intento $intento de ${Intentos}: main.py extract -p --pdf"
    $salida = Join-Path $logs "tarea_mensual_${sello}_intento$intento.out.log"
    $errores = Join-Path $logs "tarea_mensual_${sello}_intento$intento.err.log"

    try {
        $proceso = Start-Process -FilePath $python `
            -ArgumentList @("main.py", "extract", "-p", "--pdf") `
            -WorkingDirectory $proyecto -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $salida -RedirectStandardError $errores
        $codigo = $proceso.ExitCode
    } catch {
        Write-Log "No se pudo lanzar Python: $($_.Exception.Message)"
        $codigo = 1
    }

    Write-Log "Intento $intento terminó con código $codigo"
    if ($codigo -ne 1) { break }
    if ($intento -lt $Intentos) {
        Write-Log "Reintentando en $EsperaMinutos minutos"
        Start-Sleep -Seconds ($EsperaMinutos * 60)
    }
}

if ($codigo -eq 2) {
    Write-Log "El guard de seguridad bloqueó una petición: no se reintenta, revisa el log de la corrida"
}
Write-Log "Fin con código $codigo"
exit $codigo
