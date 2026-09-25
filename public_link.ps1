# Public link for the demo, from this laptop, with no account.
#
# Runs a production copy of the app (debug off, its own state file) and a
# Cloudflare quick tunnel to it, both detached from the window that started
# them, so closing the window does not kill the link. Prints the address.
#
#   powershell -ExecutionPolicy Bypass -File public_link.ps1          start (or restart) both
#   powershell -ExecutionPolicy Bypass -File public_link.ps1 -App     restart only the app copy (after a code change; the link stays)
#   powershell -ExecutionPolicy Bypass -File public_link.ps1 -Stop    stop both
#
# The tunnel binary is downloaded next to this script the first time. The
# address changes whenever the tunnel is restarted; a restart of the app
# copy alone keeps it. The app copy keeps its state in public_state.db here;
# delete that file (or use Reset demo) for a clean case book.
param([switch]$App, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$cf = Join-Path $root 'cloudflared.exe'
$log = Join-Path $root 'public_tunnel.log'
$appLog = Join-Path $root 'public_app.log'
$port = 8020

function Stop-App { Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*waitress*--listen=127.0.0.1:$port*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false } }
function Stop-Tunnel { Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false }

if ($Stop) { Stop-App; Stop-Tunnel; 'stopped'; exit 0 }

if (-not (Test-Path $py)) { throw "No .venv: run  py -3.13 -m venv .venv  and  .venv\Scripts\python.exe -m pip install -r requirements.txt  first." }
& $py -c "import waitress" 2>$null; if ($LASTEXITCODE -ne 0) { & $py -m pip install -q --disable-pip-version-check 'waitress>=3.0' }

# The app copy: production server, debug off, a random secret, its own state.
Stop-App
$env:DEBUG = '0'; $env:DEMO_MODE = '1'; $env:PYTHONUTF8 = '1'
$env:SECRET_KEY = -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
$env:FCC_STATE_DB = Join-Path $root 'public_state.db'
Start-Process -FilePath $py -ArgumentList "-m waitress --listen=127.0.0.1:$port --threads=8 app:app" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $appLog -RedirectStandardError (Join-Path $root 'public_app.err.log')
$up = $false
foreach ($i in 1..60) { try { if ((Invoke-WebRequest -Uri "http://127.0.0.1:$port/login" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $up = $true; break } } catch { Start-Sleep -Milliseconds 500 } }
if (-not $up) { throw "The app copy did not come up on port $port; see $appLog" }
"app copy: up on 127.0.0.1:$port"

if ($App) { $url = if (Test-Path $log) { [regex]::Match((Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com').Value } else { '' }; "link unchanged: $url"; exit 0 }

# The tunnel.
Stop-Tunnel
if (-not (Test-Path $cf)) { Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cf -UseBasicParsing }
if (Test-Path $log) { Remove-Item $log -Force }
Start-Process -FilePath $cf -ArgumentList "tunnel --url http://127.0.0.1:$port --no-autoupdate --protocol http2" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardError $log -RedirectStandardOutput (Join-Path $root 'public_tunnel.out.log')
$url = ''
foreach ($i in 1..60) { if (Test-Path $log) { $url = [regex]::Match((Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com').Value; if ($url) { break } }; Start-Sleep -Seconds 1 }
if (-not $url) { throw "No tunnel address after 60 s; see $log" }
foreach ($i in 1..30) { try { if ((Invoke-WebRequest -Uri "$url/login" -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200) { break } } catch { Start-Sleep -Seconds 2 } }
"public link: $url"
