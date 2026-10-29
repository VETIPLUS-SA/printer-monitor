# Registra (o reemplaza) la tarea programada PrinterMonitorMonthCount: el día 1 de
# cada mes a la 1:00 ejecuta tools\tarea_mensual.ps1 (cierre del mes anterior).
#
# Por defecto la tarea corre con tu usuario y solo cuando tienes la sesión iniciada;
# no pide contraseña ni permisos de administrador. Con -SinSesion corre aunque no
# haya nadie conectado: pide tu contraseña y necesita PowerShell como administrador.

param(
    [switch]$SinSesion
)

$ErrorActionPreference = "Stop"

$nombre = "PrinterMonitorMonthCount"
$proyecto = Split-Path -Parent $PSScriptRoot
$script = Join-Path $proyecto "tools\tarea_mensual.ps1"
$usuario = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logonType = if ($SinSesion) { "Password" } else { "InteractiveToken" }

# StartWhenAvailable: si el equipo estaba apagado a la 1:00, corre apenas se pueda.
# WakeToRun: si estaba suspendido, lo despierta. RestartOnFailure cubre fallos al
# arrancar la tarea; los fallos de la corrida los reintenta tarea_mensual.ps1.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Cierre mensual de contadores Kyocera: main.py extract -p --pdf (mes anterior).</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-01T01:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth>
        <DaysOfMonth><Day>1</Day></DaysOfMonth>
        <Months>
          <January /><February /><March /><April /><May /><June />
          <July /><August /><September /><October /><November /><December />
        </Months>
      </ScheduleByMonth>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$usuario</UserId>
      <LogonType>$logonType</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT15M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$script"</Arguments>
      <WorkingDirectory>$proyecto</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

if ($SinSesion) {
    $credencial = Get-Credential -UserName $usuario -Message "Contraseña de $usuario para la tarea $nombre"
    Register-ScheduledTask -TaskName $nombre -Xml $xml -User $usuario `
        -Password $credencial.GetNetworkCredential().Password -Force | Out-Null
} else {
    Register-ScheduledTask -TaskName $nombre -Xml $xml -Force | Out-Null
}

Get-ScheduledTask -TaskName $nombre | Get-ScheduledTaskInfo |
    Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult
