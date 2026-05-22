param(
    [int]$Port = 8000,
    [string]$HostName = "0.0.0.0",
    [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not (Test-Path $VenvDir)) {
    Write-Host "[run_server] Создаю venv в $VenvDir..."
    py -m venv $VenvDir
    & "$VenvDir\Scripts\python.exe" -m pip install --upgrade pip
}

Write-Host "[run_server] Проверяю зависимости..."
& "$VenvDir\Scripts\pip.exe" install -r requirements.txt

Write-Host "[run_server] Запуск uvicorn на $HostName`:$Port"
& "$VenvDir\Scripts\uvicorn.exe" main:app --host $HostName --port $Port --workers 1
