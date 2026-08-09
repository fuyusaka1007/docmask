<#
.SYNOPSIS
DocMask v0.1.0-beta.4 Windows 打包脚本
在 Windows 上运行此脚本，生成与 macOS 版本一致的发行包。

用法:
  powershell -ExecutionPolicy Bypass -File build_windows.ps1

前提:
  - Python 3.10+
  - pip install -r requirements.txt
  - pip install pyinstaller
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

# 清理旧构建
Remove-Item -Recurse -Force build, dist, *.egg-info -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path dist | Out-Null

# 计算 assets 绝对路径（PyInstaller --add-data 需要相对 workpath 的正确路径）
$assetsSrc = Join-Path $projectRoot "docmask\ui\assets"

Write-Host "=== Building docmask-cli (Windows) ===" -ForegroundColor Cyan
python -m PyInstaller --onefile --name docmask-cli --noconfirm `
    --hidden-import lxml --hidden-import chardet `
    --distpath dist --workpath build/cli --specpath build/cli `
    docmask_cli.py

if ($LASTEXITCODE -ne 0) { Write-Error "CLI build failed"; exit 1 }

Write-Host "=== Building docmask-ui (Windows) ===" -ForegroundColor Cyan
python -m PyInstaller --onefile --windowed --name docmask-ui --noconfirm `
    --hidden-import customtkinter --hidden-import darkdetect `
    --hidden-import lxml --hidden-import chardet --hidden-import PIL `
    --add-data "$assetsSrc;docmask\ui\assets" `
    --distpath dist --workpath build/ui --specpath build/ui `
    docmask_ui.py

if ($LASTEXITCODE -ne 0) { Write-Error "UI build failed"; exit 1 }

Write-Host "=== Building sdist ===" -ForegroundColor Cyan
python setup.py sdist --dist-dir dist

Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Output:"
Get-ChildItem dist | Format-Table Name, Length -AutoSize
