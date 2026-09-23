# Fase 0 — Hallazgos de reconocimiento (Kyocera Command Center RX)

Fecha: 2026-09-23 · Equipo: `192.168.1.59` (ECOSYS M3655idn, monocromática, MFP)
Herramienta: `tools/recon_kyocera.py` (solo lectura: bloquea todo POST salvo login/logout).

## Alcance de red

| IP | Modelo (según BD antigua) | Accesible desde 192.168.1.85 |
|----|---------------------------|------------------------------|
| 192.168.1.59  | ECOSYS M3655idn | Sí |
| 192.168.1.104 | ECOSYS M3655idn | No (timeout) |
| 192.168.1.163 | ECOSYS M3560idn | No (timeout) |

## 1. Estructura del DOM

- `http://` redirige (307) a `https://` con certificado autofirmado → `ignore_https_errors=True`.
- Frameset HTML 4.01. Todo vive en frames con nombre fijo:
  `wlmframe` (menú + login), `device`, `panelusage`, `paper`, `toner`, `staple`, `postlstinfo`.
- Las páginas son Knockout.js; los datos llegan en un "model" JS
  (`/js/jssrc/model/<ruta>.model.htm?<args>`) que expone `XxxModel.get('<campo>')`.

## 2. Login / sesión

- Enlace `#aadminloginid` → campos `#arg01_UserName`, `#arg02_Password`, botón `input[name=Login]`.
- POST a `/startwlm/login.cgi` con `func=authLogin`. Cookies de sesión: `ID1`, `level`, `cert_id`, …
- Logout: botón `#Logout` (texto "Desconexión") en `wlmframe`. Funciona y devuelve al inicio.
- El servidor embebido es frágil: peticiones en ráfaga provocaron `socket hang up`.
  → Espaciar peticiones y reintentar con backoff.
- Duración de la sesión: no medida (no fue necesaria; una corrida completa tarda < 1 min).

## 3. Lista de cuentas ("Contabilidad de trabajos")

- URL: `/mngset/jobset/MngSet_JobAcc_JobAccLst.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7=<PÁGINA>&arg8=0&arg9=`
- 10 cuentas por página; total en `MngSet_JobAcc_JobAccLstModel.get('searchResult')` (hoy 20 → 2 páginas).
- Por fila, en el model: `sDeptPrivateID` (ID interno), `sDeptPublicID` (ID de cuenta visible, p. ej. `0882`), `sDeptName`.
- **No hay exportación nativa** en esta pantalla.
- ⚠ La misma pantalla tiene checkboxes + formulario de **borrado** de cuentas (`okhtmfile=MngSet_Acc_DeleteRslt.htm`). Nunca interactuar con ellos.
- Filas especiales al pie: "Otra cuenta" (ID interno `101`) y "Contabilidad total tbjos." (totales del equipo).

## 4. Detalle por cuenta — URL directa (sin paginación)

`callTotalJob(privateID)` solo carga URLs GET en frames:

| Frame | URL (`<Q>` = `arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7=1&arg8=0&arg9=&arg10=`) |
|-------|------------------------------------------------------------------------------|
| device | `/mngset/jobset/MngSet_JobAcc_EchJobPrnCnt.htm?arg1=0&<Q>&arg11=<privateID>` (por función) |
| device | idem con `arg1=2` (por diseño: dúplex / combinar) |
| panelusage | `/mngset/jobset/MngSet_JobAcc_EchJobScnCnt.htm?arg1=1&<Q>&arg11=<privateID>` |
| paper | `/mngset/jobset/MngSet_JobAcc_EchJobFaxCnt.htm?arg1=1&<Q>&arg11=<privateID>` |
| toner | `/mngset/jobset/MngSet_JobAcc_ResetCnt.htm?...` ⚠ **pantalla de reinicio de contador — no cargar ni tocar** |

Totales del equipo: `MngSet_JobAcc_TotPrnCnt.htm` / `TotScnCnt.htm` / `TotFaxCnt.htm` (sin `arg11`).

**Requisito clave:** el servidor responde **404** a estas URLs si la petición no lleva
`Referer: https://<IP>/startwlm/login.cgi`. Con ese Referer funcionan directamente,
incluso sin haber pasado por la lista.

## 5. Métricas del detalle (etiquetas exactas, equipo monocromático)

- Impresas por función: `Copiadora Total`, `Impresora Total`
- Impresas por diseño: `Dúplex (1 cara)`, `Dúplex (2 caras)`, `Total`, `Combinar (Ninguno)`, `Combinar (2 en 1)`, `Combinar (4 en 1)`, `Total`
- Escaneadas: `Copia`, `FAX`, `Escaneo (Otras)`, `Total de escaneado`
- FAX: `Páginas transmisión FAX`, `Hora transmisión FAX` (hh:mm:ss)
- Cada fila trae además `Uso/MÁX.` (límite; hoy `----------` = sin límite).

El model de `EchJobPrnCnt` trae los mismos valores en arrays sin etiqueta
(`copyCounter`, `printerCounter`, `duplexCounter`, `combineCounter`, `FAXCounter`, …) más `accountId`, `accountName`, `lastUpdate`.

## Recomendación

**URL directa, no paginación por clics.**

1. Login por UI (única acción con POST permitida).
2. Recorrer la lista por URL (`arg7=1..N`) y leer `sDeptPrivateID/PublicID/Name` del model de cada página → lista completa antes de tocar detalles.
3. Por cada cuenta, navegar el frame a las URLs de detalle con el Referer requerido y leer la tabla renderizada **por etiqueta** (texto visible), no por posición.
4. Nunca cargar `ResetCnt`, nunca tocar checkboxes/borrado; mantener el guard que aborta cualquier POST no permitido.
5. Logout siempre en `finally`.
6. Clave del usuario en el CSV: `account_id` (ID público); guardar también el ID interno y el nombre.
