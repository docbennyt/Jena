$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "source"
$Dist = Join-Path $Root "dist"
$Portable = Join-Path $Dist "Jena"
$Zip = Join-Path $Dist "Jena-Portable.zip"

$env:PYTHONPATH = $Source

Write-Host "Installing dependencies..."
python -m pip install -r (Join-Path $Root "requirements.txt")

Write-Host "Running tests..."
python -m pytest (Join-Path $Root "tests") -q

Write-Host "Running compile validation..."
python -m compileall -q $Source

Write-Host "Building portable app..."
& (Join-Path $PSScriptRoot "build.ps1")

Write-Host "Launching packaged smoke test..."
$Exe = Join-Path $Portable "Jena.exe"
$Process = Start-Process -FilePath $Exe -WorkingDirectory $Portable -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 4
if ($Process.HasExited) {
    throw "Packaged Jena.exe exited during smoke test."
}
Stop-Process -Id $Process.Id -Force

$Hash = Get-FileHash $Zip -Algorithm SHA256
Write-Host "Release folder: $Portable"
Write-Host "Portable ZIP: $Zip"
Write-Host "SHA-256: $($Hash.Hash)"
