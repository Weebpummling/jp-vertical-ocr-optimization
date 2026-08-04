# Column-count scale check of a roster volume against an external total.
# One officer entry = one vertical text column; clustering NDL-OCR line boxes
# by x-center estimates total entries. First use: pid 1908490 (reserve
# directory, 大正15) vs MA/Tokyo Report 2727's First Reserve total 22,745 -
# see benchmarks/reserve-1926-crosscheck.md.
param([string]$NdlPid = '1908490')
$ErrorActionPreference = 'Stop'
$cache = "$env:USERPROFILE\jp-ocr-data\cache\$NdlPid"
$raw = [System.IO.File]::ReadAllText("$cache\fulltext.json", [System.Text.Encoding]::UTF8)
$j = $raw | ConvertFrom-Json

$all = New-Object System.Text.StringBuilder
foreach ($e in $j.list) { [void]$all.Append($e.contents); [void]$all.Append("`n") }
$txt = $all.ToString()
"total chars   : $($txt.Length)"

$kanjiNum = '[一二三四五六七八九十百〇]'
$districtPat = '第' + $kanjiNum + '{0,4}[(（]'
"yobieki-dai   : $([regex]::Matches($txt, '豫備役第').Count)"
"district pat  : $([regex]::Matches($txt, $districtPat).Count)"
"hohei         : $([regex]::Matches($txt, '[步歩]兵').Count)"
"kihei         : $([regex]::Matches($txt, '騎兵').Count)"
"hohei-sho     : $([regex]::Matches($txt, '砲兵').Count)"
"kohei         : $([regex]::Matches($txt, '工兵').Count)"
"shicho        : $([regex]::Matches($txt, '輜重兵').Count)"
"taisho-era    : $([regex]::Matches($txt, '大正').Count)"

# column-count estimate from coordjson: cluster line boxes by x-center per frame
$totalCols = 0
$frameCols = @{}
foreach ($e in $j.list) {
    if ([string]::IsNullOrWhiteSpace($e.coordjson) -or $e.coordjson -eq 'null') { continue }
    $lines = $e.coordjson | ConvertFrom-Json
    if ($lines.Count -lt 5) { continue }
    $centers = $lines | ForEach-Object { ($_.xmin + $_.xmax) / 2 } | Sort-Object
    # cluster: new column when the gap between successive x-centers exceeds 60px
    $cols = 1
    for ($i = 1; $i -lt $centers.Count; $i++) {
        if (($centers[$i] - $centers[$i - 1]) -gt 60) { $cols++ }
    }
    $totalCols += $cols
    $frameCols[$e.page] = $cols
}
"frames used   : $($frameCols.Count)"
"total columns : $totalCols"
"mean cols/frame: $([Math]::Round($totalCols / [double]$frameCols.Count, 1))"
