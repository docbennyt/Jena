$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "source\app.py"
$Dist = Join-Path $Root "dist"
$env:PYTHONPATH = Join-Path $Root "source"

python -m pip install -r (Join-Path $Root "requirements.txt")

foreach ($StalePath in @(
    (Join-Path $Dist "Jena"),
    (Join-Path $Dist "Jena-Portable.zip")
)) {
    if (Test-Path $StalePath) {
        $DistPrefix = [System.IO.Path]::GetFullPath($Dist).TrimEnd('\') + '\'
        $ResolvedTarget = [System.IO.Path]::GetFullPath($StalePath)
        if (-not $ResolvedTarget.StartsWith($DistPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove build artifact outside dist: $ResolvedTarget"
        }
        Remove-Item -Recurse -Force $StalePath
    }
}

python -m PyInstaller --noconfirm --windowed --name Jena --distpath $Dist --workpath (Join-Path $Root "build") $Source

$Portable = Join-Path $Dist "Jena"
Copy-Item -Force (Join-Path $Root "portable.flag") (Join-Path $Portable "portable.flag")
Copy-Item -Force (Join-Path $Root "README.md") (Join-Path $Portable "README.txt")
Copy-Item -Force (Join-Path $Root "LICENSES.md") (Join-Path $Portable "LICENSES.txt")

$VendorEngine = Join-Path $Root "vendor\7zip"
$PackagedEngine = Join-Path $Portable "tools\7zip"
foreach ($RequiredFile in @("7z.exe", "7z.dll", "License.txt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $VendorEngine $RequiredFile))) {
        throw "Missing vendored 7-Zip runtime file: $RequiredFile"
    }
}
New-Item -ItemType Directory -Force -Path $PackagedEngine | Out-Null
Copy-Item -Force (Join-Path $VendorEngine "7z.exe") (Join-Path $PackagedEngine "7z.exe")
Copy-Item -Force (Join-Path $VendorEngine "7z.dll") (Join-Path $PackagedEngine "7z.dll")
Copy-Item -Force (Join-Path $VendorEngine "License.txt") (Join-Path $PackagedEngine "License.txt")

$Zip = Join-Path $Dist "Jena-Portable.zip"
if (Test-Path $Zip) {
    Remove-Item $Zip -Force
}
Compress-Archive -Path (Join-Path $Portable "*") -DestinationPath $Zip
Write-Host "Portable build: $Portable"
Write-Host "Portable ZIP: $Zip"
