$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
foreach ($Path in @((Join-Path $Root "build"), (Join-Path $Root "dist"))) {
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
}
