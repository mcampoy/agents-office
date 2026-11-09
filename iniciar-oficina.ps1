<#
.SYNOPSIS
  Levanta la oficina (si no está corriendo) y la abre en el navegador.

.DESCRIPTION
  1. Lee los proyectos registrados (<datos>/proyectos.json) o, con -Perfil, un perfil suelto.
  2. Si ya hay una oficina respondiendo en el puerto, solo abre el navegador.
  3. Si no, verifica que exista el python.exe que registró el instalador (decisión 1), levanta el
     servidor en segundo plano, sin ventana, espera a que responda y abre el navegador.
  4. Si falta la web compilada (web/dist), avisa: la oficina muestra la vista básica.

  El servidor deja su salida en <datos>/servidor.log. Para detenerlo: .\iniciar-oficina.ps1 -Detener

.EXAMPLE
  .\iniciar-oficina.ps1
  .\iniciar-oficina.ps1 -Perfil ..\mi-perfil -Puerto 8770 -SinNavegador
  .\iniciar-oficina.ps1 -Detener
#>
param(
    [string]$Perfil,
    [int]$Puerto,
    [switch]$SinNavegador,
    [switch]$Detener
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot

# Python: el que registró el instalador; si no hay registro, el lanzador py
$py = 'py'
$pyArgs = @('-3')
$info = & $py @pyArgs -c @"
import json, sys
sys.path.insert(0, r'$repo')
from servidor.oficinas import carpeta_comun, leer_proyectos
from servidor.perfil import Perfil
datos = carpeta_comun()
proyectos = leer_proyectos(datos)
perfil = r'$Perfil' or None
p = Perfil(perfil if perfil or not proyectos else proyectos[0]['perfil'])
config = {}
try:
    config = json.loads((datos / 'config.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    pass
nombre = p['nombre'] if perfil or len(proyectos) < 2 else ', '.join(x['id'] for x in proyectos)
print(json.dumps({'puerto': p['puerto'], 'datos': str(datos), 'perfil': str(p.carpeta), 'nombre': nombre,
                  'python': config.get('python')}))
"@
if ($LASTEXITCODE -ne 0) { throw "No se pudo leer el perfil. ¿Está instalado Python 3 (py -3)?" }
$info = $info | ConvertFrom-Json
if (-not $Puerto) { $Puerto = [int]$info.puerto }
$url = "http://127.0.0.1:$Puerto/"

if ($info.python) {
    if (-not (Test-Path -LiteralPath $info.python)) {
        throw "El python.exe que registró el instalador ya no existe: $($info.python). Volvé a correr: py -3 scripts\instalar.py"
    }
    $py = $info.python
    $pyArgs = @()
}

if ($Detener) {
    $procesos = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='py.exe'" |
        Where-Object { $_.CommandLine -like '*-m servidor*' -and $_.CommandLine -like "*--puerto $Puerto*" }
    if (-not $procesos) { Write-Host "No hay una oficina corriendo en el puerto $Puerto."; return }
    $procesos | ForEach-Object { Stop-Process -Id $_.ProcessId -Confirm:$false }
    Write-Host "Oficina detenida (puerto $Puerto)."
    return
}

function Responde {
    try {
        $r = Invoke-WebRequest -Uri "${url}api/perfil" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (Responde) {
    Write-Host "La oficina ya está corriendo en $url"
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $repo 'web\dist\index.html'))) {
        Write-Warning "Falta la web compilada (web\dist): se verá la vista básica. Para compilarla: cd web\pixel-agents; npm install; npm run build"
    }
    New-Item -ItemType Directory -Force -Path $info.datos | Out-Null
    $log = Join-Path $info.datos 'servidor.log'
    $argumentos = $pyArgs + @('-m', 'servidor', '--puerto', "$Puerto")
    if ($Perfil) { $argumentos += @('--perfil', $Perfil) }
    Start-Process -FilePath $py -ArgumentList $argumentos -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" | Out-Null
    $listo = $false
    for ($i = 0; $i -lt 40 -and -not $listo; $i++) {
        Start-Sleep -Milliseconds 250
        $listo = Responde
    }
    if (-not $listo) { throw "El servidor no respondió en $url. Revisá $log.err" }
    Write-Host "Oficina ($($info.nombre)) en $url"
}

if (-not $SinNavegador) { Start-Process $url }
