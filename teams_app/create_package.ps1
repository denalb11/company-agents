# create_package.ps1
# Packages the Teams app manifest and icons into teams_app.zip.
# Run from the teams_app/ directory:
#   cd teams_app
#   .\create_package.ps1

$ErrorActionPreference = "Stop"

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$destination = Join-Path $scriptDir "teams_app.zip"

$manifest   = Join-Path $scriptDir "manifest.json"
$colorPng   = Join-Path $scriptDir "color.png"
$outlinePng = Join-Path $scriptDir "outline.png"
$files = @($manifest, $colorPng, $outlinePng)

# Verify all source files exist
foreach ($f in $files) {
    if (-not (Test-Path $f)) {
        Write-Error "Required file not found: $f"
        exit 1
    }
}

# Remove existing zip if present
if (Test-Path $destination) {
    Remove-Item $destination -Force
    Write-Host "Removed existing $destination"
}

Compress-Archive -Path $files -DestinationPath $destination

Write-Host ""
Write-Host "Package created: $destination"
Write-Host ""
Write-Host "Included files:"
foreach ($f in $files) {
    Write-Host "  - $(Split-Path -Leaf $f)"
}
Write-Host ""
Write-Host "Upload teams_app.zip in the Teams Admin Center or via"
Write-Host "'Apps > Upload a custom app' in Microsoft Teams."
