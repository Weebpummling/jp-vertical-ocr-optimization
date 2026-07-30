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

docker exec jpocr-db pg_dump -U jpocr -d jpocr --no-owner | Out-File -FilePath $file -Encoding utf8
if ((Get-Item $file).Length -lt 1024) { throw "Backup suspiciously small: $file" }
$tail = Get-Content $file -Tail 5 | Out-String
if ($tail -notmatch "PostgreSQL database dump complete") { throw "Backup incomplete: $file" }

Get-ChildItem $dest -Filter "jpocr-*.sql" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 | Remove-Item -Force -Confirm:$false
Write-Output "OK $file ($([int]((Get-Item $file).Length/1kb)) KB)"
