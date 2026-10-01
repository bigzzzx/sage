# Start the optional local Laya inference service. All caches stay under this repository on D:.
$sageRoot = Split-Path -Parent $PSScriptRoot
$cacheRoot = Join-Path $sageRoot '.cache'
$env:HF_HOME = Join-Path $cacheRoot 'huggingface'
$env:TORCH_HOME = Join-Path $cacheRoot 'torch'
$env:XDG_CACHE_HOME = Join-Path $cacheRoot 'xdg'
$env:UV_CACHE_DIR = Join-Path $cacheRoot 'uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $cacheRoot 'python'
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null

$env:LAYA_HOST = '127.0.0.1'
$env:LAYA_PORT = '8011'
$env:LAYA_DEVICE = 'cuda'
$env:LAYA_MODELS = 'multilingual'
$env:LAYA_PRELOAD = '1'

$server = Join-Path $cacheRoot 'laya-venv\Scripts\laya-serve.exe'
if (-not (Test-Path -LiteralPath $server)) {
    throw "Laya service executable not installed: $server"
}
& $server
