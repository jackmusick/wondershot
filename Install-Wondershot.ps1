# Wondershot installer/updater for Windows.
#
#   irm https://raw.githubusercontent.com/jackmusick/wondershot/main/Install-Wondershot.ps1 | iex
#
# Downloads the newest WondershotSetup from GitHub Releases and runs it
# silently (per-user, no admin). Re-running updates in place (same Inno
# AppId). The installer is not code-signed yet; this script downloads
# over HTTPS straight from this repo's Releases.

$ErrorActionPreference = "Stop"
$repo = "jackmusick/wondershot"

function Say($msg) { Write-Host "[wondershot] $msg" }

Say "looking up the latest release..."
try {
    $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
} catch {
    Write-Error ("No published release found for $repo yet. " +
        "Check https://github.com/$repo/releases")
    return
}

$asset = $release.assets | Where-Object { $_.name -like "WondershotSetup-*.exe" } | Select-Object -First 1
if (-not $asset) {
    Write-Error "Release $($release.tag_name) has no WondershotSetup asset."
    return
}

$tmp = Join-Path $env:TEMP $asset.name
Say "downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
Invoke-WebRequest $asset.browser_download_url -OutFile $tmp

Say "installing (silent, per-user)..."
$p = Start-Process $tmp -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait -PassThru
if ($p.ExitCode -ne 0) {
    Write-Error "installer exited with code $($p.ExitCode)"
    return
}
Remove-Item $tmp -ErrorAction SilentlyContinue

Say "done — Wondershot $($release.tag_name) is in your Start menu."
Say "update later by re-running this same command."
