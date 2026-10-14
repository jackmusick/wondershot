param(
    [string]$Source,
    [string]$Version = "8.1.1"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$binaries = Join-Path $repoRoot "src-tauri\binaries"
$targets = @(
    (Join-Path $binaries "ffmpeg-x86_64-pc-windows-gnu.exe"),
    (Join-Path $binaries "ffmpeg-x86_64-pc-windows-msvc.exe")
)

New-Item -ItemType Directory -Force -Path $binaries | Out-Null

if ($Source) {
    $ffmpeg = Resolve-Path $Source
    foreach ($target in $targets) {
        Copy-Item -LiteralPath $ffmpeg -Destination $target -Force
        Write-Host "staged $target"
    }
    return
}

$cache = Join-Path $repoRoot ".tauri-sidecars"
$zip = Join-Path $cache "ffmpeg-windows-$Version.zip"
$extract = Join-Path $cache "ffmpeg-$Version"
New-Item -ItemType Directory -Force -Path $cache | Out-Null

if (-not (Test-Path $zip)) {
    if ($Version -notmatch '^(\d+\.\d+)') {
        throw "FFmpeg version must begin with a major.minor pair (received '$Version')"
    }

    $releaseSeries = $Matches[1]
    $urls = @(
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n$releaseSeries-latest-win64-gpl-$releaseSeries.zip"
    )
    $partial = "$zip.partial"
    $downloaded = $false

    foreach ($url in $urls) {
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Write-Host "downloading $url (attempt $attempt of 3)"
                Invoke-WebRequest -Uri $url -OutFile $partial -TimeoutSec 180
                Move-Item -LiteralPath $partial -Destination $zip -Force
                $downloaded = $true
                break
            }
            catch {
                Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
                Write-Warning "download failed: $($_.Exception.Message)"
                if ($attempt -lt 3) {
                    Start-Sleep -Seconds (5 * $attempt)
                }
            }
        }

        if ($downloaded) {
            break
        }
    }

    if (-not $downloaded) {
        throw "Unable to download FFmpeg $Version from any configured source"
    }
}

if (-not (Test-Path $extract)) {
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
}

$ffmpeg = Get-ChildItem -Path $extract -Recurse -Filter ffmpeg.exe |
    Sort-Object FullName |
    Select-Object -First 1

if (-not $ffmpeg) {
    throw "ffmpeg.exe not found in $extract"
}

foreach ($target in $targets) {
    Copy-Item -LiteralPath $ffmpeg.FullName -Destination $target -Force
    Write-Host "staged $target"
}
