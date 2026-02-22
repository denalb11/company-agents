# create_deploy_zip.ps1
# Creates deploy.zip for Azure App Service zip-deploy.
# Run from the project root:  .\create_deploy_zip.ps1

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$destination = Join-Path $projectRoot "deploy.zip"

# Directories whose entire subtree is excluded (matched against every path segment)
$excludedDirs = @("venv", "__pycache__", "uploads", "teams_app", ".git")

# Exact filenames that are excluded regardless of location
$excludedFiles = @(".env")

# File extensions that are excluded
$excludedExtensions = @(".pyc")

# Remove previous zip
if (Test-Path $destination) {
    Remove-Item $destination -Force
    Write-Host "Removed existing deploy.zip"
}

# Stage files into a temp directory so Compress-Archive preserves the tree
$tempDir = Join-Path $env:TEMP "deploy_staging_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir | Out-Null
Write-Host "Staging to: $tempDir"

try {
    $included = 0
    $skipped  = 0

    Get-ChildItem -Path $projectRoot -Recurse -File | ForEach-Object {
        $file = $_

        # Relative path from project root (e.g. "src\interfaces\teams_bot.py")
        $rel = $file.FullName.Substring($projectRoot.Length).TrimStart('\', '/')

        # Split into path segments for directory checks
        $segments = $rel -split '[/\\]'

        $skip = $false

        # 1. Exclude if any ancestor directory matches the exclusion list
        # (segments[0..n-2] are directories; segments[-1] is the filename)
        $dirSegments = $segments[0..($segments.Count - 2)]
        foreach ($seg in $dirSegments) {
            if ($excludedDirs -contains $seg) {
                $skip = $true
                break
            }
        }

        # 2. Exclude exact filenames (.env but NOT .env.example)
        if (-not $skip -and ($excludedFiles -contains $segments[-1])) {
            $skip = $true
        }

        # 3. Exclude by extension (*.pyc)
        if (-not $skip -and ($excludedExtensions -contains $file.Extension)) {
            $skip = $true
        }

        if ($skip) {
            $skipped++
            return
        }

        # Copy to temp dir, recreating the relative folder structure
        $destFile   = Join-Path $tempDir $rel
        $destFolder = Split-Path -Parent $destFile
        if (-not (Test-Path $destFolder)) {
            New-Item -ItemType Directory -Path $destFolder -Force | Out-Null
        }
        Copy-Item -Path $file.FullName -Destination $destFile
        $included++
    }

    Write-Host "Files included : $included"
    Write-Host "Files skipped  : $skipped"

    # Zip the staged tree — "tempDir\*" puts files at the zip root (no extra nesting)
    Compress-Archive -Path "$tempDir\*" -DestinationPath $destination

    $sizeMB = [math]::Round((Get-Item $destination).Length / 1MB, 2)
    Write-Host ""
    Write-Host "Created : $destination"
    Write-Host "Size    : $sizeMB MB"
    Write-Host ""
    Write-Host "Deploy with:"
    Write-Host "  az webapp deploy --resource-group <rg> --name <app> --src-path deploy.zip --type zip"

} finally {
    # Always clean up the temp directory
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force
    }
}
