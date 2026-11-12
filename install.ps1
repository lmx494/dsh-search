# 把本仓库装成 DSH 技能（默认 ~/.dsh/skills/locator）。
# 用法：pwsh -File install.ps1 [-SkillsDir "D:\某个\skills"]
param([string]$SkillsDir = "$env:USERPROFILE\.dsh\skills")

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $SkillsDir "locator"

New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $here "SKILL.md") $dst -Force
Copy-Item (Join-Path $here "tools") $dst -Recurse -Force

Write-Host "locator 已安装到 $dst"
Write-Host "试一下："
Write-Host "  `$P = `"python`""
Write-Host "  & `$P `"$dst\tools\build_index.py`" add `<你的文件或目录>`"
Write-Host "  & `$P `"$dst\tools\locate.py`" `"<要搜的字符串>`" --section"
