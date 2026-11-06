# FYAgent 环境搭建脚本（全部落在 D 盘，不写 C 盘）
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# 做的事：
#   1. 在 <仓库根>\.venv 建虚拟环境（Python 3.10+，优先用 PATH 上的 python）
#   2. 把 pip 缓存指到 <仓库根>\.cache\pip，避免占用 C 盘
#   3. 安装 FYAgent 全部依赖（openai / textual / mcp / trafilatura / pytest）
#   4. 跑一遍 FYAgent 测试套件确认装对了
#   5. 若缺少 Agent\FYAgent\config.ini，从 config.example.ini 复制一份（记得改密钥）

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $RepoRoot ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$Agent = Join-Path $RepoRoot "Agent\FYAgent"

Write-Host "== FYAgent setup ==" -ForegroundColor Cyan
Write-Host "repo   : $RepoRoot"
Write-Host "venv   : $Venv"

# --- 1. 虚拟环境 ---------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $python) {
        throw "找不到 python。请安装 Python 3.10+ 后重试（建议安装到 D 盘并勾选 Add to PATH）。"
    }
    Write-Host "creating venv with $($python.Source)"
    & $python.Source -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv 失败（exit $LASTEXITCODE）" }
} else {
    Write-Host "venv already exists, reuse"
}

# --- 2/3. 依赖 -----------------------------------------------------------
$env:PIP_CACHE_DIR = Join-Path $RepoRoot ".cache\pip"
Write-Host "installing requirements (cache: $env:PIP_CACHE_DIR)"
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r (Join-Path $Agent "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install 失败（exit $LASTEXITCODE）" }

# --- 4. 测试 -------------------------------------------------------------
Write-Host "running FYAgent tests"
Push-Location $Agent
try {
    & $VenvPy -X utf8 -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "测试未通过（exit $LASTEXITCODE）" }
} finally {
    Pop-Location
}

# --- 5. 配置 -------------------------------------------------------------
$config = Join-Path $Agent "config.ini"
$example = Join-Path $Agent "config.example.ini"
if (-not (Test-Path $config)) {
    Copy-Item $example $config
    Write-Host "已生成 $config（示例值）——请把 [llm] 三项改成自己的接口 / 密钥 / 模型" -ForegroundColor Yellow
} else {
    Write-Host "config.ini 已存在，未改动"
}

Write-Host ""
Write-Host "== done ==" -ForegroundColor Green
Write-Host "启动：双击 Agent\FYAgent\启动.bat"
Write-Host "  或： & $VenvPy -X utf8 $Agent\main.py"
