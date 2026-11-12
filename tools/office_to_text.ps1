<#
  office_to_text.ps1 — 用本机 Microsoft Office COM 把 Office/PDF 转成 UTF-8 文本。
  用法:
    pwsh -NoProfile -File office_to_text.ps1 -Path <输入文件> -Out <输出.txt>
  退出码: 0 成功 / 2 不支持的扩展名 / 3 文件不存在 / 4 转换失败
  说明: Word 负责 doc/docx/rtf/odt/pdf；Excel 负责 xls；PowerPoint 负责 ppt。
        转换全程不弹窗（Word/PowerPoint 用 WithWindow=$false），产出为 UTF-8 无 BOM。
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = 'Stop'

function Fail([string]$code, [string]$msg) {
  [Console]::Error.WriteLine("$code`: $msg")
  exit 4
}
function Release($o) {
  if ($null -ne $o) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($o) } catch { } }
}
function Write-Utf8([string]$p, [string]$text) {
  [System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))
}

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { [Console]::Error.WriteLine("NOT_FOUND: $Path"); exit 3 }
$src = (Resolve-Path -LiteralPath $Path).Path
$outFull = [System.IO.Path]::GetFullPath($Out)
$null = New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($outFull))
$ext = [System.IO.Path]::GetExtension($src).ToLowerInvariant()

# ---------------- Word: doc / docx / docm / rtf / odt / pdf ----------------
if ($ext -match '^\.(doc|docx|docm|rtf|odt|pdf)$') {
  $word = $null; $doc = $null
  try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try { $word.Options.ConfirmConversions = $false } catch { }
    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, ...)
    $doc = $word.Documents.Open($src, $false, $true, $false)
    # wdFormatUnicodeText = 7
    try { $doc.SaveAs2($outFull, 7) } catch { $doc.SaveAs($outFull, 7) }
    $doc.Close(0)
    $doc = $null
  }
  catch { Fail 'WORD_FAIL' $_.Exception.Message }
  finally { Release $doc; if ($word) { try { $word.Quit(0) } catch { } }; Release $word; [GC]::Collect() }
  if (-not (Test-Path -LiteralPath $outFull)) { Fail 'WORD_NO_OUTPUT' 'Word 未产出文件' }
  exit 0
}

# ---------------- Excel: xls（xlsx 由 openpyxl 处理） ----------------
if ($ext -eq '.xls') {
  $xl = $null; $wb = $null
  try {
    $xl = New-Object -ComObject Excel.Application
    $xl.Visible = $false
    $xl.DisplayAlerts = $false
    $wb = $xl.Workbooks.Open($src, 0, $true)
    $sb = New-Object System.Text.StringBuilder
    foreach ($ws in $wb.Worksheets) {
      [void]$sb.AppendLine("[工作表] " + $ws.Name)
      $ur = $ws.UsedRange
      $rows = [int]$ur.Rows.Count; $cols = [int]$ur.Columns.Count
      if ($rows -lt 1 -or $cols -lt 1) { continue }
      $vals = $ur.Value2
      for ($r = 1; $r -le $rows; $r++) {
        $parts = New-Object System.Collections.Generic.List[string]
        for ($c = 1; $c -le $cols; $c++) {
          $v = if ($rows -eq 1 -and $cols -eq 1) { $vals } else { $vals[$r, $c] }
          if ($null -eq $v) { $parts.Add('') } else { $parts.Add(("{0}" -f $v)) }
        }
        [void]$sb.AppendLine(("行{0}`t{1}" -f $r, ($parts -join ' | ').TrimEnd(' ', '|')))
      }
    }
    Write-Utf8 $outFull $sb.ToString()
    $wb.Close($false); $wb = $null
  }
  catch { Fail 'EXCEL_FAIL' $_.Exception.Message }
  finally { Release $wb; if ($xl) { try { $xl.Quit() } catch { } }; Release $xl; [GC]::Collect() }
  exit 0
}

# ---------------- PowerPoint: ppt（pptx 由 python-pptx 处理） ----------------
if ($ext -eq '.ppt') {
  $ppt = $null; $pres = $null
  try {
    $ppt = New-Object -ComObject PowerPoint.Application
    # Open(FileName, ReadOnly, Untitled, WithWindow) —— WithWindow=$false 才能不弹窗
    $pres = $ppt.Presentations.Open($src, $true, $false, $false)
    $sb = New-Object System.Text.StringBuilder
    $n = 0
    foreach ($slide in $pres.Slides) {
      $n++
      [void]$sb.AppendLine("[幻灯片 $n]")
      foreach ($shape in $slide.Shapes) {
        try {
          if ($shape.HasTextFrame -and $shape.TextFrame.HasText) {
            $t = $shape.TextFrame.TextRange.Text -replace "`r", "`n"
            foreach ($ln in ($t -split "`n")) { if ($ln.Trim()) { [void]$sb.AppendLine($ln.TrimEnd()) } }
          }
          if ($shape.HasTable) {
            $tb = $shape.Table
            for ($r = 1; $r -le $tb.Rows.Count; $r++) {
              $cells = New-Object System.Collections.Generic.List[string]
              for ($c = 1; $c -le $tb.Columns.Count; $c++) { $cells.Add($tb.Cell($r, $c).Shape.TextFrame.TextRange.Text) }
              [void]$sb.AppendLine(("表格行{0}`t{1}" -f $r, ($cells -join ' | ')))
            }
          }
        }
        catch { }
      }
    }
    Write-Utf8 $outFull $sb.ToString()
    $pres.Close(); $pres = $null
  }
  catch { Fail 'PPT_FAIL' $_.Exception.Message }
  finally { Release $pres; if ($ppt) { try { $ppt.Quit() } catch { } }; Release $ppt; [GC]::Collect() }
  exit 0
}

[Console]::Error.WriteLine("UNSUPPORTED_EXT: $ext")
exit 2
