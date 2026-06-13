# Wondershot installer/updater for Windows (Rust/Tauri app).
#
#   irm https://raw.githubusercontent.com/jackmusick/wondershot/main/Install-Wondershot.ps1 | iex
#
# Downloads the newest Tauri Windows installer from GitHub Releases and
# runs it silently. Re-running updates in place. The installer is not
# code-signed yet; this script downloads over HTTPS straight from this
# repo's Releases.

$ErrorActionPreference = "Stop"
$repo = "jackmusick/wondershot"

function Say($msg) { Write-Host "[wondershot] $msg" }
function Fail($msg) { Write-Error "[wondershot] $msg" }

Say "looking up the latest release..."
try {
    $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
} catch {
    Fail ("No published release found for $repo yet. " +
          "Check https://github.com/$repo/releases")
    return
}

$assets = @($release.assets | Where-Object {
    $_.name -match '^(Wondershot|wondershot).*\.(msi|exe)$' -and
    $_.name -notlike "WondershotSetup-*.exe" # legacy Python/Inno installer
})

$asset = $assets |
    Sort-Object @{ Expression = {
        if ($_.name -match '\.msi$') { 0 }
        elseif ($_.name -match '-setup\.exe$') { 1 }
        else { 2 }
    }}, name |
    Select-Object -First 1

if (-not $asset) {
    Fail ("Release $($release.tag_name) has no Rust/Tauri Windows installer " +
          "asset (.msi or *-setup.exe). Refusing to install the legacy " +
          "WondershotSetup Python build.")
    return
}

$tmp = Join-Path $env:TEMP $asset.name
Say "downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
Invoke-WebRequest $asset.browser_download_url -OutFile $tmp

Say "installing (silent, per-user)..."
if ($asset.name -match '\.msi$') {
    $args = @("/i", "`"$tmp`"", "/qn", "/norestart")
    $p = Start-Process "msiexec.exe" -ArgumentList $args -Wait -PassThru
} else {
    # Tauri's NSIS installer uses /S for silent mode.
    $p = Start-Process $tmp -ArgumentList "/S" -Wait -PassThru
}
if ($p.ExitCode -ne 0) {
    Fail "installer exited with code $($p.ExitCode)"
    return
}
Remove-Item $tmp -ErrorAction SilentlyContinue

Say "done — Wondershot $($release.tag_name) is in your Start menu."
Say "update later by re-running this same command."
