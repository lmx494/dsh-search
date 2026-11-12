# 把本仓库装成 DSH 技能（默认 ~/.dsh/skills/locator）。
# 用法：pwsh -File install.ps1 [-SkillsDir "D:\某个\skills"]
param([string]$SkillsDir = "$env:USERPROFILE\.dsh\skills")

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $SkillsDir "locator"

New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $here "SKILL.md") $dst -Force
Copy-Item (Join-Path $here "tools") $dst -Recurse -Force

Write-Host "locator 已安装到 $dst"

# 把口令契约写进全局 AGENTS.md，装完就能用大白话触发；不想写就删掉这一段
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source (Join-Path $dst "tools\set_triggers.py") sync --scope global
    if ($LASTEXITCODE -eq 0) { Write-Host "口令契约已写入 $env:USERPROFILE\.dsh\AGENTS.md（改口令：tools\set_triggers.py add/search）" }
} else {
    Write-Host "没找到 python：跳过口令同步。手动跑：python `"$dst\tools\set_triggers.py`" sync --scope global"
}

Write-Host "试一下："
Write-Host "  `$P = `"python`""
Write-Host "  & `$P `"$dst\tools\build_index.py`" add `<你的文件或目录>`"
Write-Host "  & `$P `"$dst\tools\locate.py`" `"<要搜的字符串>`" --section"
