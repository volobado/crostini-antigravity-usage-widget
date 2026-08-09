<#
.SYNOPSIS
    Set up Lagrange: desktop shortcut, and optionally wire it into your
    Antigravity launchers so switching accounts restarts agy in place.

.DESCRIPTION
    Nothing is installed system-wide and nothing is overwritten without a
    backup: every launcher this script edits is copied to <name>.bak first.

.PARAMETER Launchers
    Batch files that start Antigravity. Each is rewritten to open the widget
    and run agy through `lagrange run`, which is what lets an account switch
    take effect in the same console.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 `
        -Launchers "C:\tools\agy_standard.bat","C:\tools\agy_nonstop.bat"
#>
[CmdletBinding()]
param(
    [string[]] $Launchers = @(),
    [switch]   $NoShortcut,
    [string]   $ShortcutName = "Lagrange"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Write-Step($text) { Write-Host "  $text" }
function Write-Ok($text)   { Write-Host "  [ok] $text"   -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [!!] $text"   -ForegroundColor Yellow }
function Write-Bad($text)  { Write-Host "  [xx] $text"   -ForegroundColor Red }

Write-Host ""
Write-Host "Lagrange installer" -ForegroundColor Cyan
Write-Host ("=" * 52)

# ── Python ──────────────────────────────────────────────────────────────────
$python = $null
foreach ($candidate in @("py -3", "python")) {
    $exe, $args = $candidate.Split(" ", 2)
    if (Get-Command $exe -ErrorAction SilentlyContinue) { $python = $candidate; break }
}
if (-not $python) {
    Write-Bad "Python 3.10+ not found. Install it from https://python.org and re-run."
    exit 1
}

$version = & ([scriptblock]::Create("$python -c ""import sys;print('%d.%d'%sys.version_info[:2])"""))
Write-Ok "Python $version ($python)"

$tk = & ([scriptblock]::Create("$python -c ""import tkinter;print('yes')"" 2>&1"))
if ($tk -notmatch "yes") {
    Write-Bad "tkinter is missing. Reinstall Python with the tcl/tk option enabled."
    exit 1
}
Write-Ok "tkinter available"

# pythonw sits next to python and is what keeps the widget console-free.
$pythonwPath = & ([scriptblock]::Create(
    "$python -c ""import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"""))
if (-not (Test-Path $pythonwPath)) {
    Write-Warn "pythonw.exe not found; the widget will open with a console window"
    $pythonwPath = $null
} else {
    Write-Ok "pythonw: $pythonwPath"
}

# ── does Antigravity exist ──────────────────────────────────────────────────
$env:PYTHONPATH = "$repo;$env:PYTHONPATH"
$agyProbe = & ([scriptblock]::Create(
    "$python -c ""from lagrange import discovery;print(discovery.find_agy() or '')"" 2>&1"))
if ([string]::IsNullOrWhiteSpace($agyProbe)) {
    Write-Warn "agy.exe not found. Install Antigravity CLI, or set agy_path in ~/.lagrange/config.json"
} else {
    Write-Ok "Antigravity: $agyProbe"
}

# ── desktop shortcut ────────────────────────────────────────────────────────
if (-not $NoShortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $linkPath = Join-Path $desktop "$ShortcutName.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    if ($pythonwPath) {
        $link.TargetPath = $pythonwPath
        $link.Arguments = "-m lagrange widget"
    } else {
        $link.TargetPath = Join-Path $repo "bin\lagrange-widget.cmd"
    }
    $link.WorkingDirectory = $repo
    $link.Description = "Antigravity quota and account switcher"
    $icon = Join-Path $repo "docs\lagrange.ico"
    if (Test-Path $icon) { $link.IconLocation = "$icon,0" }
    $link.Save()

    # The shortcut runs pythonw directly, so it needs PYTHONPATH set for the
    # user rather than only inside the .cmd shims.
    $userPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "User")
    if ($userPath -notlike "*$repo*") {
        $merged = if ([string]::IsNullOrWhiteSpace($userPath)) { $repo } else { "$repo;$userPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $merged, "User")
        Write-Ok "PYTHONPATH now includes the repo (new consoles only)"
    }
    Write-Ok "Shortcut: $linkPath"
}

# ── Antigravity launchers ───────────────────────────────────────────────────
$configured = @()
foreach ($launcher in $Launchers) {
    if (-not (Test-Path $launcher)) { Write-Warn "skipped, not found: $launcher"; continue }

    $backup = "$launcher.bak"
    if (-not (Test-Path $backup)) { Copy-Item $launcher $backup }

    $original = Get-Content $launcher -Raw
    if ($original -match "lagrange") {
        Write-Step "already wired: $launcher"
        $configured += @{ label = [IO.Path]::GetFileNameWithoutExtension($launcher); path = $launcher }
        continue
    }

    # Keep the caller's own agy flags; only the way agy is started changes.
    $agyArgs = ""
    if ($original -match '(?m)^\s*"?[^"\r\n]*agy\.exe"?\s*(.*)$') {
        $agyArgs = $Matches[1].Trim()
        $agyArgs = ($agyArgs -replace '--log-file\s+"[^"]*"', '').Trim()
        $agyArgs = ($agyArgs -replace '%\*', '').Trim()
    }

    @"
@echo off
:: Rewritten by the Lagrange installer. Previous version: $([IO.Path]::GetFileName($backup))
:: Opens the quota widget, then runs Antigravity through `lagrange run` so that
:: switching accounts restarts agy in THIS console instead of a new one.
call "$repo\bin\lagrange-widget.cmd"
call "$repo\bin\lagrange.cmd" run $agyArgs %*
"@ | Set-Content -Path $launcher -Encoding ASCII

    Write-Ok "wired: $launcher  (backup: $([IO.Path]::GetFileName($backup)))"
    $configured += @{ label = [IO.Path]::GetFileNameWithoutExtension($launcher); path = $launcher }
}

# Remember the launchers so the widget can offer them when no wrapper is live.
# Handed over as a file: JSON through a command line loses its quoting to
# whichever shell is in the middle.
if ($configured.Count -gt 0) {
    # Tab-separated rather than JSON: Windows PowerShell 5.1 collapses a
    # one-element array into an object, and paths full of backslashes invite
    # quoting mistakes. Python assembles the JSON instead.
    $payload = Join-Path $env:TEMP "lagrange-launchers.tsv"
    ($configured | ForEach-Object { "$($_.label)`t$($_.path)" }) |
        Set-Content -Path $payload -Encoding UTF8
    $writer = Join-Path $env:TEMP "lagrange-write-config.py"
    @'
import sys
from lagrange import config
launchers = []
with open(sys.argv[1], encoding="utf-8-sig") as fh:
    for line in fh:
        label, _, path = line.rstrip("\n").partition("\t")
        if path:
            launchers.append({"label": label, "path": path})
config.set_values(launchers=launchers)
print(config.CONFIG_FILE)
'@ | Set-Content -Path $writer -Encoding UTF8
    $written = & ([scriptblock]::Create("$python ""$writer"" ""$payload"""))
    Remove-Item $payload, $writer -ErrorAction SilentlyContinue
    Write-Ok "Launchers remembered in $written"
}

Write-Host ("=" * 52)
Write-Host "Done." -ForegroundColor Green
Write-Host ""
Write-Host "  Next:  bin\lagrange.cmd doctor     check everything"
Write-Host "         bin\lagrange.cmd run        start Antigravity with in-place switching"
Write-Host ""
