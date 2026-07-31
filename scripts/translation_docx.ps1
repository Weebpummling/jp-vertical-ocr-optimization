<#
.SYNOPSIS
NDL OCR passthrough, step 2: render a frame-referenced translation markdown
file to .docx via Word COM.

.DESCRIPTION
For machines without pandoc/node/python: converts simple markdown (headings,
tables, lists, hr, bold/italic/code) to HTML, opens it in Word via COM, and
saves as .docx. Word ignores CSS font rules on HTML import and stamps its own
run-level fonts (PMingLiU on CJK runs), so the script normalizes fonts twice -
on the styles and across the whole content range.

Frame headings (##) become Heading 2, so Word's navigation pane doubles as a
clickable frame index. A centered page number is added to the footer.

Requires desktop Word. The document author will be the local Word identity;
clear it via File > Info before sharing if that matters.

.EXAMPLE
.\translation_docx.ps1 -MarkdownPath D:\work\1446616_translation_en.md
.EXAMPLE
.\translation_docx.ps1 -MarkdownPath t.md -DocxPath out.docx -LatinFont Cambria -CjkFont "Yu Gothic"
#>
param(
    [Parameter(Mandatory = $true)][string]$MarkdownPath,
    [string]$DocxPath,
    [string]$LatinFont = 'Georgia',
    [string]$CjkFont = 'Yu Mincho'
)
$ErrorActionPreference = 'Stop'

$MarkdownPath = (Resolve-Path $MarkdownPath).Path
if (-not $DocxPath) { $DocxPath = [System.IO.Path]::ChangeExtension($MarkdownPath, '.docx') }
$md = [System.IO.File]::ReadAllText($MarkdownPath, [System.Text.Encoding]::UTF8)

function Convert-Inline([string]$s) {
    $s = $s -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;'
    $s = [regex]::Replace($s, '\*\*(.+?)\*\*', '<strong>$1</strong>')
    $s = [regex]::Replace($s, '`(.+?)`', '<code>$1</code>')
    $s = [regex]::Replace($s, '(?<![\w*])\*([^*\r\n]+?)\*(?![\w*])', '<em>$1</em>')
    return $s
}

$html = New-Object System.Text.StringBuilder
[void]$html.AppendLine('<html><head><meta charset="utf-8"><style>')
[void]$html.AppendLine('body { font-size: 11pt; } h1 { text-align: center; font-size: 20pt; } h2 { font-size: 13pt; border-bottom: 1px solid #999; margin-top: 18pt; } table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 3pt 6pt; vertical-align: top; }')
[void]$html.AppendLine('</style></head><body>')

$inTable = $false; $inList = $false
$para = New-Object System.Collections.Generic.List[string]
function Flush-Para {
    if ($script:para.Count -gt 0) {
        [void]$script:html.AppendLine("<p>$(Convert-Inline ($script:para -join ' '))</p>")
        $script:para.Clear()
    }
}
function Close-List  { if ($script:inList)  { [void]$script:html.AppendLine('</ul>');    $script:inList  = $false } }
function Close-Table { if ($script:inTable) { [void]$script:html.AppendLine('</table>'); $script:inTable = $false } }

foreach ($line in ($md -split "`r?`n")) {
    $t = $line.TrimEnd()
    if ($t -match '^\|') {
        Flush-Para; Close-List
        if ($t -match '^\|[\s:|-]+\|$') { continue }  # separator row
        if (-not $inTable) { [void]$html.AppendLine('<table>'); $inTable = $true }
        $row = (($t.Trim('|') -split '\|') | ForEach-Object { "<td>$(Convert-Inline $_.Trim())</td>" }) -join ''
        [void]$html.AppendLine("<tr>$row</tr>")
        continue
    }
    Close-Table
    if ($t -match '^###\s+(.*)') { Flush-Para; Close-List; [void]$html.AppendLine("<h3>$(Convert-Inline $Matches[1])</h3>"); continue }
    if ($t -match '^##\s+(.*)')  { Flush-Para; Close-List; [void]$html.AppendLine("<h2>$(Convert-Inline $Matches[1])</h2>"); continue }
    if ($t -match '^#\s+(.*)')   { Flush-Para; Close-List; [void]$html.AppendLine("<h1>$(Convert-Inline $Matches[1])</h1>"); continue }
    if ($t -match '^(---+|\*\*\*+)\s*$') { Flush-Para; Close-List; [void]$html.AppendLine('<hr>'); continue }
    if ($t -match '^\s*[-*]\s+(.*)') {
        Flush-Para
        if (-not $inList) { [void]$html.AppendLine('<ul>'); $inList = $true }
        [void]$html.AppendLine("<li>$(Convert-Inline $Matches[1])</li>")
        continue
    }
    if ($t -match '^\s*$') { Flush-Para; Close-List; continue }
    $para.Add($t.Trim())
}
Flush-Para; Close-List; Close-Table
[void]$html.AppendLine('</body></html>')

$htmlPath = [System.IO.Path]::ChangeExtension($DocxPath, '.tmp.html')
[System.IO.File]::WriteAllText($htmlPath, $html.ToString(), (New-Object System.Text.UTF8Encoding $true))

$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
    $doc = $word.Documents.Open($htmlPath, $false, $true)

    foreach ($sn in @('Normal', 'Heading 1', 'Heading 2', 'Heading 3')) {
        $st = $doc.Styles.Item($sn)
        $st.Font.NameAscii = $LatinFont
        $st.Font.NameOther = $LatinFont
        $st.Font.NameFarEast = $CjkFont
    }
    $doc.Styles.Item('Normal').ParagraphFormat.SpaceAfter = 6
    $doc.Styles.Item('Heading 2').ParagraphFormat.KeepWithNext = $true

    # HTML import stamps run-level fonts over the styles - clear them wholesale
    $f = $doc.Content.Font
    $f.NameAscii = $LatinFont
    $f.NameOther = $LatinFont
    $f.NameFarEast = $CjkFont

    [void]$doc.Sections.Item(1).Footers.Item(1).PageNumbers.Add(1, $true)  # centered

    $doc.SaveAs2($DocxPath, 12)  # wdFormatXMLDocument
    "pages : $($doc.ComputeStatistics(2))"
    $doc.Close($false)
    "saved : $DocxPath"
} finally {
    $word.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    Remove-Item $htmlPath -Force -ErrorAction SilentlyContinue
}
