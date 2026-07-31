<#
.SYNOPSIS
NDL OCR passthrough, step 1: pull NDL's own OCR for a Next-Gen DL volume and
normalize it into a per-frame transcription plus translation-ready chunks.

.DESCRIPTION
NDL has already run production OCR over the Next-Gen Digital Library; this
script does no reading of its own. It fetches the fulltext (with per-line
coordinates) and the book record (TOC anchors), then normalizes:

  - one text block per frame (koma), line breaks rebuilt from coordinates,
    each block carrying its viewer URL as provenance;
  - frame <-> printed-page numbering estimated from the TOC anchors and
    stamped on every block (marked as estimated - verify against the scan);
  - fixed-size chunk files ready to hand to a translator (human or model).

Politeness matches ingestion/iiif_client.py: identifying UA, cached responses,
one request per endpoint per volume, ever.

Output quality is bounded by NDL's uncorrected OCR. Treat it like any Layer 4
output: a machine proposal, never authoritative.

.EXAMPLE
.\ndl_fulltext_pull.ps1 -NdlPid 1446616
.EXAMPLE
.\ndl_fulltext_pull.ps1 -NdlPid 1446616 -OutDir D:\work\hohei-soten -ChunkSize 20
#>
param(
    [Parameter(Mandatory = $true)][string]$NdlPid,
    [string]$OutDir,
    [int]$ChunkSize = 15
)
$ErrorActionPreference = 'Stop'

if (-not $OutDir) {
    $home_ = if ($env:JP_OCR_DATA) { $env:JP_OCR_DATA } else { "$env:USERPROFILE\jp-ocr-data" }
    $OutDir = Join-Path $home_ "manuals\ndl-$NdlPid"
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$utf8bom = New-Object System.Text.UTF8Encoding $true
$ua = @{ 'User-Agent' = 'jp-vertical-ocr-optimization (research ingestion; polite, cached)' }

# --- fetch (cached: one request per endpoint per volume, ever) ---------------
$fulltextPath = Join-Path $OutDir 'ndl_fulltext_raw.json'
$bookPath     = Join-Path $OutDir 'ndl_book_raw.json'
if (-not (Test-Path $fulltextPath)) {
    Invoke-WebRequest -Uri "https://lab.ndl.go.jp/dl/api/book/fulltext-json/$NdlPid" -Headers $ua -OutFile $fulltextPath -UseBasicParsing
}
if (-not (Test-Path $bookPath)) {
    Invoke-WebRequest -Uri "https://lab.ndl.go.jp/dl/api/book/$NdlPid" -Headers $ua -OutFile $bookPath -UseBasicParsing
}
$fulltext = ([System.IO.File]::ReadAllText($fulltextPath, [System.Text.Encoding]::UTF8)) | ConvertFrom-Json
$book     = ([System.IO.File]::ReadAllText($bookPath, [System.Text.Encoding]::UTF8)) | ConvertFrom-Json

# --- TOC anchors: "<section>/<printed page>  (NNNN.jp2)" ---------------------
$toc = @()
foreach ($entry in $book.index) {
    if ($entry -match '^(.*?)(?:/(\d+))?\s*\((\d+)\.jp2\)\s*$') {
        $toc += [PSCustomObject]@{
            section = $Matches[1].Trim()
            printedPage = if ($Matches[2]) { [int]$Matches[2] } else { $null }
            frame = [int]$Matches[3]
        }
    }
}

# --- frame -> printed-page mapping, estimated from anchors -------------------
# Model: page(f) = slope*f + offset, slope 2 for two-page spreads, 1 for
# single-page scans. Fit slope from consecutive anchors, offset by median.
$anchors = @($toc | Where-Object { $null -ne $_.printedPage } | Sort-Object frame)
$slope = $null; $offset = $null; $maxDev = $null
if ($anchors.Count -ge 2) {
    $rates = for ($i = 1; $i -lt $anchors.Count; $i++) {
        $df = $anchors[$i].frame - $anchors[$i-1].frame
        if ($df -gt 0) { ($anchors[$i].printedPage - $anchors[$i-1].printedPage) / $df }
    }
    $medianRate = ($rates | Sort-Object)[[int](($rates.Count - 1) / 2)]
    $slope = if ([Math]::Abs($medianRate - 2) -le [Math]::Abs($medianRate - 1)) { 2 } else { 1 }
    $offsets = $anchors | ForEach-Object { $_.printedPage - $slope * $_.frame }
    $offset = ($offsets | Sort-Object)[[int](($offsets.Count - 1) / 2)]
    $maxDev = ($anchors | ForEach-Object { [Math]::Abs($_.printedPage - ($slope * $_.frame + $offset)) } | Measure-Object -Maximum).Maximum
}
function Get-PageLabel([int]$frame) {
    if ($null -eq $script:slope) { return 'printed page unknown (no TOC anchors)' }
    $p = $script:slope * $frame + $script:offset
    if ($p -lt 1) { return 'front matter (before printed page 1)' }
    if ($script:slope -eq 2) { return "printed pages ~$($p - 1)-$p (estimated)" }
    return "printed page ~$p (estimated)"
}

# --- transcription: one block per frame, lines from coordinates --------------
$sb = New-Object System.Text.StringBuilder
$title = if ($book.title) { $book.title } else { "NDL pid $NdlPid" }
[void]$sb.AppendLine(('=' * 78))
[void]$sb.AppendLine("$title - transcription from NDL's own OCR (uncorrected machine output)")
[void]$sb.AppendLine("Source      : NDL Digital Collections pid $NdlPid - https://dl.ndl.go.jp/pid/$NdlPid")
[void]$sb.AppendLine("Published   : $($book.published) - publisher $($book.publisher)")
[void]$sb.AppendLine("Text source : https://lab.ndl.go.jp/dl/api/book/fulltext-json/$NdlPid")
[void]$sb.AppendLine("Attribution : National Diet Library. Unreadable glyphs appear as the geta mark.")
if ($null -ne $slope) {
    [void]$sb.AppendLine("Page mapping: page = $slope*frame + $offset, fit from $($anchors.Count) TOC anchors (max deviation $maxDev). ESTIMATED - verify against the scan.")
}
[void]$sb.AppendLine("Retrieved   : $(Get-Date -Format yyyy-MM-dd)")
[void]$sb.AppendLine(('=' * 78))
[void]$sb.AppendLine('')

$frameBlocks = @()
foreach ($e in ($fulltext.list | Sort-Object page)) {
    $fb = New-Object System.Text.StringBuilder
    [void]$fb.AppendLine("=== Frame $($e.page) ===")
    [void]$fb.AppendLine("URL: https://dl.ndl.go.jp/pid/$NdlPid/1/$($e.page)")
    [void]$fb.AppendLine("PRINTED: $(Get-PageLabel $e.page)")
    foreach ($t in ($toc | Where-Object { $_.frame -eq $e.page })) {
        $pageNote = if ($null -ne $t.printedPage) { " - printed page $($t.printedPage)" } else { '' }
        [void]$fb.AppendLine("[TOC: $($t.section)$pageNote]")
    }
    if ([string]::IsNullOrWhiteSpace($e.coordjson) -or $e.coordjson -eq 'null') {
        if (-not [string]::IsNullOrWhiteSpace($e.contents)) { [void]$fb.AppendLine($e.contents) }
        else { [void]$fb.AppendLine('(no OCR text on this frame)') }
    } else {
        foreach ($ln in ($e.coordjson | ConvertFrom-Json)) { [void]$fb.AppendLine($ln.contenttext) }
    }
    [void]$fb.AppendLine('')
    $frameBlocks += $fb.ToString()
}
$transcriptionPath = Join-Path $OutDir "${NdlPid}_transcription_ja.txt"
[System.IO.File]::WriteAllText($transcriptionPath, $sb.ToString() + ($frameBlocks -join ''), $utf8bom)

# --- chunks for translation --------------------------------------------------
$chunkDir = Join-Path $OutDir 'chunks'
New-Item -ItemType Directory -Force $chunkDir | Out-Null
$n = 0
for ($i = 0; $i -lt $frameBlocks.Count; $i += $ChunkSize) {
    $n++
    $end = [Math]::Min($i + $ChunkSize - 1, $frameBlocks.Count - 1)
    [System.IO.File]::WriteAllText((Join-Path $chunkDir ("chunk_{0:D2}.txt" -f $n)), ($frameBlocks[$i..$end] -join ''), $utf8bom)
}

"volume      : $title ($($book.published))"
"frames      : $($frameBlocks.Count)"
"toc anchors : $($anchors.Count)"
"transcription: $transcriptionPath"
"chunks      : $n files in $chunkDir"
'next: translate each chunk (keep the Frame/PRINTED headers), then run translation_docx.ps1 on the merged markdown.'
