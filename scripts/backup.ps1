# Nightly database backup (docs/PLAN.md, Phase 0).
# Dumps the dockerized Postgres to $env:JP_OCR_DATA\backups, keeps the last 14,
# and verifies the dump is restorable-looking (non-trivial size, valid gzip header
# is skipped since we use plain SQL - we check the closing line instead).
#
# Schedule (daily 02:00) once and forget:
#   schtasks /Create /TN "jpocr-backup" /SC DAILY /ST 02:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\scripts\backup.ps1"
#
# Off-machine copy: mirror the backups folder to the lead's personal cloud storage
# (destination configured privately on the lead's machine; see docs/data-home.md).

$ErrorActionPreference = "Stop"
$dataHome = $env:JP_OCR_DATA
if (-not $dataHome) { $dataHome = Join-Path $env:USERPROFILE "jp-ocr-data" }
$dest = Join-Path $dataHome "backups"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$file = Join-Path $dest "jpocr-$stamp.sql"

# Dump inside the container and copy the file out byte-for-byte. Piping pg_dump
# through PowerShell decodes the bytes as console text and re-encodes them; under
# the scheduler the console codepage is cp932, which silently destroys every
# Japanese character while the ASCII completion line survives -- a corrupt backup
# that passes its own checks. Verified failure mode; do not "simplify" this back
# to a pipeline.
# docker cp reports success on stderr; under the scheduler's redirected host,
# Windows PowerShell 5.1 turns native stderr into a terminating error when
# ErrorActionPreference is Stop. Gate on exit codes instead.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    docker exec jpocr-db pg_dump -U jpocr -d jpocr --no-owner -f /tmp/jpocr-dump.sql 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)" }
    docker cp jpocr-db:/tmp/jpocr-dump.sql $file 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed (exit $LASTEXITCODE)" }
    docker exec jpocr-db rm -f /tmp/jpocr-dump.sql 2>&1 | Out-Null
} finally {
    $ErrorActionPreference = $prevEAP
}

if ((Get-Item $file).Length -lt 1024) { throw "Backup suspiciously small: $file" }
$bytes = [IO.File]::ReadAllBytes($file)
$text = [Text.Encoding]::UTF8.GetString($bytes)
if ($text -notmatch "PostgreSQL database dump complete") { throw "Backup incomplete: $file" }
# The completion line is ASCII and survives encoding corruption; Japanese does
# not. U+6B69 U+5175 (hohei) comes from the loaded vocabulary, so any
# post-Phase-0 dump contains it. Built from code points because PowerShell 5.1
# reads BOM-less scripts as ANSI -- a literal here would itself be misread.
$hohei = [string][char]0x6B69 + [char]0x5175
if (-not $text.Contains($hohei)) { throw "Backup encoding is corrupt (no Japanese survived): $file" }

Get-ChildItem $dest -Filter "jpocr-*.sql" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 | Remove-Item -Force -Confirm:$false
Write-Output "OK $file ($([int]((Get-Item $file).Length/1kb)) KB)"
