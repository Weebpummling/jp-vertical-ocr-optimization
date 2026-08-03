<#
.SYNOPSIS
JACAR handwritten-document workflow, step 1: pull the source PDF for a JACAR
reference code and render its pages to PNG for the reading engines.

.DESCRIPTION
Implements docs/jacar-handwritten-workflow.md sections 1-2 for machines without
python/pypdfium2. The modern JACAR viewer (/das/image/{REF}) is PDF.js over one
raw PDF per reference code; the PDF URL is parsed out of the viewer page HTML
(the parent bundle id in the path is not constructible from the ref code).

Page rendering uses the Windows built-in PDF engine (Windows.Data.Pdf, WinRT) -
it decodes JACAR's JBIG2 bilevel scans with no installs. On machines with
NDLOCR-Lite, prefer feeding --sourcepdf directly for Engine A; the PNGs here
are for the vision engine (Engine B) and human review.

JACAR has no fulltext API and no OCR text layer: everything read from these
pages is a machine proposal, never authoritative.

.EXAMPLE
.\jacar_pull.ps1 -RefCode C14030374300
.EXAMPLE
.\jacar_pull.ps1 -RefCode C14030562600 -RenderWidth 1600
#>
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Z]\d+$')][string]$RefCode,
    [string]$OutDir,
    [int]$RenderWidth = 2200,
    [switch]$SkipRender
)
$ErrorActionPreference = 'Stop'

if (-not $OutDir) {
    $home_ = if ($env:JP_OCR_DATA) { $env:JP_OCR_DATA } else { "$env:USERPROFILE\jp-ocr-data" }
    $OutDir = Join-Path $home_ "jacar\$RefCode"
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$ua = @{ 'User-Agent' = 'jp-vertical-ocr-optimization (research ingestion; polite, cached)' }

# --- 1. resolve + download the source PDF (cached) ---------------------------
$pdfPath = Join-Path $OutDir "${RefCode}_source.pdf"
if (-not (Test-Path $pdfPath)) {
    $viewer = Invoke-WebRequest -Uri "https://www.jacar.archives.go.jp/das/image/$RefCode" -Headers $ua -UseBasicParsing
    $m = [regex]::Match($viewer.Content, 'content/item[^"'']*\.pdf')
    if (-not $m.Success) { throw "no PDF path found in viewer page for $RefCode - viewer layout may have changed" }
    $pdfUrl = "https://www.jacar.archives.go.jp/$($m.Value)"
    "resolved: $pdfUrl"
    Invoke-WebRequest -Uri $pdfUrl -Headers $ua -OutFile $pdfPath -UseBasicParsing
}
"pdf: $pdfPath ($([Math]::Round((Get-Item $pdfPath).Length / 1MB, 1)) MB)"

if ($SkipRender) { return }

# --- 2. render pages via the Windows built-in PDF engine ---------------------
$pagesDir = Join-Path $OutDir 'pages'
New-Item -ItemType Directory -Force $pagesDir | Out-Null

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
})[0]
function Await-Op($op, $type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
function Await-Action($action) {
    $task = $asTaskAction.Invoke($null, @($action))
    $task.Wait(-1) | Out-Null
}

$file = Await-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Get-Item $pdfPath).FullName)) ([Windows.Storage.StorageFile])
$doc = Await-Op ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
"pages in pdf: $($doc.PageCount)"
for ($i = 0; $i -lt $doc.PageCount; $i++) {
    $dest = Join-Path $pagesDir ("page_{0:D2}.png" -f ($i + 1))
    if (Test-Path $dest) { continue }
    $page = $doc.GetPage($i)
    $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $opts.DestinationWidth = $RenderWidth
    $ms = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    Await-Action ($page.RenderToStreamAsync($ms, $opts))
    $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($ms.GetInputStreamAt(0))
    $fs = [System.IO.File]::Create($dest)
    $net.CopyTo($fs)
    $fs.Close(); $net.Close(); $ms.Dispose(); $page.Dispose()
}
$stats = Get-ChildItem $pagesDir -Filter *.png | Measure-Object -Property Length -Sum
"rendered: $($stats.Count) pages, $([Math]::Round($stats.Sum / 1MB, 1)) MB in $pagesDir"
'next: engines A/B per docs/jacar-handwritten-workflow.md sections 3-5, then translation_docx.ps1.'
