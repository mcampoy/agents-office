<#
.SYNOPSIS
  Starts the office (if it is not running) and opens it in the browser.

.DESCRIPTION
  1. Reads the registered projects (<data>/projects.json) or, with -Profile, a standalone profile.
  2. If an office is already answering on the port, it only opens the browser.
  3. Otherwise, checks that the python.exe registered by the installer exists, starts the
     server in the background, without a window, waits until it answers and opens the browser.
  4. If the compiled web (web/dist) is missing, warns: the office shows the basic view.

  The server writes its output to <data>/server.log. To stop it: .\start-office.ps1 -Stop
  Messages are shown to the user, so they are Spanish.

.EXAMPLE
  .\start-office.ps1
  .\start-office.ps1 -Profile ..\my-profile -Port 8770 -NoBrowser
  .\start-office.ps1 -Stop
#>
param(
    [string]$Profile,
    [int]$Port,
    [switch]$NoBrowser,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot

# Python: the one the installer registered; without a registry, the py launcher
$py = 'py'
$pyArgs = @('-3')
$info = & $py @pyArgs -c @"
import json, sys
sys.path.insert(0, r'$repo')
from server.offices import read_projects
from server.profile import Profile, data_folder
data = data_folder()
projects = read_projects(data)
chosen = r'$Profile' or None
p = Profile(chosen if chosen or not projects else projects[0]['profile'])
config = {}
try:
    config = json.loads((data / 'config.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    pass
name = p['name'] if chosen or len(projects) < 2 else ', '.join(x['id'] for x in projects)
print(json.dumps({'port': p['port'], 'data': str(data), 'profile': str(p.folder), 'name': name,
                  'python': config.get('python')}))
"@
if ($LASTEXITCODE -ne 0) { throw "No se pudo leer el perfil. ¿Está instalado Python 3 (py -3)?" }
$info = $info | ConvertFrom-Json
if (-not $Port) { $Port = [int]$info.port }
$url = "http://127.0.0.1:$Port/"

if ($info.python) {
    if (-not (Test-Path -LiteralPath $info.python)) {
        throw "El python.exe que registró el instalador ya no existe: $($info.python). Volvé a correr: py -3 scripts\install.py"
    }
    $py = $info.python
    $pyArgs = @()
}

if ($Stop) {
    $processes = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='py.exe'" |
        Where-Object { $_.CommandLine -like '*-m server*' -and $_.CommandLine -like "*--port $Port*" }
    if (-not $processes) { Write-Host "No hay una oficina corriendo en el puerto $Port."; return }
    $processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Confirm:$false }
    Write-Host "Oficina detenida (puerto $Port)."
    return
}

function Test-Office {
    try {
        $r = Invoke-WebRequest -Uri "${url}api/profile" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (Test-Office) {
    Write-Host "La oficina ya está corriendo en $url"
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $repo 'web\dist\index.html'))) {
        Write-Warning "Falta la web compilada (web\dist): se verá la vista básica. Para compilarla: cd web\pixel-agents; npm install; npm run build"
    }
    New-Item -ItemType Directory -Force -Path $info.data | Out-Null
    $log = Join-Path $info.data 'server.log'
    $arguments = $pyArgs + @('-m', 'server', '--port', "$Port")
    if ($Profile) { $arguments += @('--profile', $Profile) }
    Start-Process -FilePath $py -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
        Start-Sleep -Milliseconds 250
        $ready = Test-Office
    }
    if (-not $ready) { throw "El servidor no respondió en $url. Revisá $log.err" }
    Write-Host "Oficina ($($info.name)) en $url"
}

if (-not $NoBrowser) { Start-Process $url }
