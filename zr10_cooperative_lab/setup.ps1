param([ValidateSet('sim','hardware','dev')][string]$Profile = 'sim')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$extra = switch ($Profile) { 'hardware' {'.[vision,analysis,learning]'} 'dev' {'.[dev,analysis]'} default {'.[analysis,learning]'} }
& $taskPython -m pip install -e $extra
if ($LASTEXITCODE -ne 0) { throw '安装项目依赖失败' }
if ($Profile -eq 'hardware' -or $Profile -eq 'dev') {
    if (-not (Test-Path -LiteralPath 'vendor/sdk/siyi_sdk/pyproject.toml')) {
        Expand-Archive -LiteralPath 'vendor/siyi_sdk_v2_snapshot.zip' -DestinationPath 'vendor/sdk'
    }
    & $taskPython -m pip install './vendor/sdk/siyi_sdk'
    if ($LASTEXITCODE -ne 0) { throw '安装固定 SDK 失败' }
}
& $taskPython -m zr10lab validate
if ($LASTEXITCODE -ne 0) { throw '配置检查失败' }
Write-Host '安装完成。可运行 .venv/Scripts/python.exe -m zr10lab run'
