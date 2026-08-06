<#
.SYNOPSIS
Build a worklist candidate set for a title, from BOTH NDL catalogues at once.

.DESCRIPTION
Spike B's standing lesson: catalogue records vary, and a title-only search on one
API silently misses editions (it missed the 1925-1932 active rosters). This script
queries both and reports the union, marking which API found each record, so a gap
in the result is a real gap rather than a search artefact.

  - ndlsearch SRU   : authoritative bibliographic catalogue, exact-title match
  - lab.ndl.go.jp/dl: Next-Gen Digital Library index (public items only - absence
                      here is NOT evidence of absence; see -CheckAccess)

The two behave differently on purpose: SRU matches the title field, the lab index
matches more broadly, so lab-only rows include unrelated catalogues that merely
mention the term. Read the `sources` column - `sru+labdl` rows are corroborated by
both, `labdl`-only rows need an eye before they enter a worklist.

With -CheckAccess it also fetches each PID's IIIF manifest, which is the practical
test of "can we actually retrieve this": OK means internet-public and ingestible,
404 usually means library-transmission only.

Politeness: serial requests, identifying UA, small delays. Read-only.

.EXAMPLE
.\ndl_worklist_sweep.ps1 -Title 陸軍予備役将校同相当官服役停年名簿 -CheckAccess
.EXAMPLE
.\ndl_worklist_sweep.ps1 -Title 服役停年名簿 -Csv worklist-candidates.csv
#>
param(
    [Parameter(Mandatory = $true)][string]$Title,
    [string]$Csv,
    [switch]$CheckAccess
)
$ErrorActionPreference = 'Stop'
$ua = @{ 'User-Agent' = 'jp-vertical-ocr-optimization (research ingestion; polite, cached)' }
$found = @{}   # pid -> record

function Add-Hit($pid_, $title_, $vol, $year, $src) {
    if (-not $pid_) { return }
    if ($found.ContainsKey($pid_)) {
        if ($found[$pid_].sources -notmatch $src) { $found[$pid_].sources += "+$src" }
        return
    }
    $found[$pid_] = [PSCustomObject]@{
        pid = $pid_; title = $title_; volume = $vol; year = $year
        sources = $src; access = ''
    }
}

# --- 1. ndlsearch SRU -------------------------------------------------------
$q = [uri]::EscapeDataString("title=`"$Title`"")
$r = Invoke-WebRequest -Uri "https://ndlsearch.ndl.go.jp/api/sru?operation=searchRetrieve&query=$q&maximumRecords=100&recordSchema=dcndl" -Headers $ua -UseBasicParsing
$t = [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
foreach ($rec in [regex]::Matches($t, '<recordData>.*?</recordData>', 'Singleline')) {
    # recordData bodies are HTML-escaped - unescape before matching tags
    $v = $rec.Value -replace '&lt;', '<' -replace '&gt;', '>' -replace '&quot;', '"' -replace '&amp;', '&'
    $ti = [regex]::Match($v, '<dc:title>\s*<rdf:Description>\s*<rdf:value>([^<]+)', 'Singleline').Groups[1].Value
    if (-not $ti) { $ti = [regex]::Match($v, '<dcterms:title>([^<]+)').Groups[1].Value }
    $vol = [regex]::Match($v, '<dcndl:volume>\s*<rdf:Description>\s*<rdf:value>([^<]+)', 'Singleline').Groups[1].Value
    $yr = [regex]::Match($v, '<dcterms:issued[^>]*>(\d{4})').Groups[1].Value
    $id = [regex]::Match($v, 'dl\.ndl\.go\.jp/(?:info:ndljp/pid/|pid/)(\d+)').Groups[1].Value
    Add-Hit $id $ti.Trim() $vol.Trim() $yr 'sru'
}

# --- 2. Next-Gen DL index (paged) -------------------------------------------
$kw = [uri]::EscapeDataString($Title)
$from = 0
while ($true) {
    $r2 = Invoke-WebRequest -Uri "https://lab.ndl.go.jp/dl/api/book/search?keyword=$kw&from=$from&size=100" -Headers $ua -UseBasicParsing -TimeoutSec 60
    $j = ([System.Text.Encoding]::UTF8.GetString($r2.RawContentStream.ToArray())) | ConvertFrom-Json
    if (-not $j.list -or $j.list.Count -eq 0) { break }
    foreach ($b in $j.list) { Add-Hit $b.id $b.title $b.volume $b.publishyear 'labdl' }
    $from += $j.list.Count
    if ($j.list.Count -lt 100) { break }
    Start-Sleep -Milliseconds 600
}

# --- 3. optional retrievability check ---------------------------------------
$out = $found.Values | Sort-Object year, pid
if ($CheckAccess) {
    foreach ($rec in $out) {
        try {
            $m = Invoke-WebRequest -Uri "https://dl.ndl.go.jp/api/iiif/$($rec.pid)/manifest.json" -Headers $ua -UseBasicParsing -TimeoutSec 30
            $rec.access = "internet_public ($((($m.Content | ConvertFrom-Json).sequences[0].canvases).Count) canvases)"
        } catch {
            $rec.access = "not_public (HTTP $($_.Exception.Response.StatusCode.value__))"
        }
        Start-Sleep -Milliseconds 400
    }
}

$out | Format-Table -AutoSize pid, year, volume, sources, access, title
"records: $($out.Count)  (sru-only: $(($out | Where-Object sources -eq 'sru').Count), labdl-only: $(($out | Where-Object sources -eq 'labdl').Count), both: $(($out | Where-Object sources -match '\+').Count))"
if ($Csv) {
    $out | Export-Csv -Path $Csv -NoTypeInformation -Encoding UTF8
    "csv: $Csv"
}
