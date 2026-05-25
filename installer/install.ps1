# LoopMap installer for Windows
# Downloads the latest loopmap.exe binary from GitHub Releases
# Run from the repo root: .\install.ps1

$ErrorActionPreference = "Stop"

$repo    = "bagusindrawanhardi/LoopMap"
$url     = "https://github.com/$repo/releases/latest/download/loopmap-windows.exe"
$outFile = Join-Path $PSScriptRoot "loopmap.exe"

Write-Host "Downloading loopmap.exe from GitHub Releases..."
try {
    Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing
    Write-Host "Done. loopmap.exe is ready in the repo root."
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\loopmap.exe --project usecases\<your-topic> --serve"
} catch {
    Write-Host "Download failed: $_"
    Write-Host "Visit https://github.com/$repo/releases to download manually."
    exit 1
}
