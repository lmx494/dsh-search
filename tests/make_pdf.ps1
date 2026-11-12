# 用 Word COM 把 docx 导出为 PDF（仅测试用）
param([string]$In, [string]$Out)
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$doc = $word.Documents.Open($In, $false, $true, $false)
try { $doc.ExportAsFixedFormat($Out, 17) } finally { $doc.Close(0); $word.Quit(0) }
Write-Output ("PDF: " + (Test-Path -LiteralPath $Out) + " " + $Out)
