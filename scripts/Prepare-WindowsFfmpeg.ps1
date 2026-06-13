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
$zip = Join-Path $cache "ffmpeg-release-essentials.zip"
$extract = Join-Path $cache "ffmpeg"
New-Item -ItemType Directory -Force -Path $cache | Out-Null

if (-not (Test-Path $zip)) {
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Write-Host "downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip
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
