#!/usr/bin/env pwsh
# Windows 完整打包入口: 依赖同步、接口生成、前端构建、服务与桌面壳打包.
# 输出目录与工作目录沿用 build_windows_app.ps1 的环境变量.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

if ($env:OS -ne 'Windows_NT') {
    throw 'Windows 打包必须在 Windows 上运行.'
}

foreach ($command in @('uv', 'dotnet')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "缺少构建工具: $command. 请安装并加入 PATH 后重新运行."
    }
}

$hasPnpm = $null -ne (Get-Command pnpm -ErrorAction SilentlyContinue)
$hasJust = $null -ne (Get-Command just -ErrorAction SilentlyContinue)
if (-not $hasPnpm -and -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw '缺少 pnpm 与 npm. 请安装 Node.js 并加入 PATH 后重新运行.'
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectRoot
try {
    if (-not $hasPnpm) {
        # npm exec 提供的 PATH 由 just 及其子进程继承.
        $buildCommand = if ($hasJust) { 'just windows-app' } else { 'uv tool run --from rust-just just windows-app' }
        & npm exec --yes --package pnpm@10 -c $buildCommand
    }
    elseif (-not $hasJust) {
        & uv tool run --from rust-just just windows-app
    }
    else {
        & just windows-app
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Windows 打包失败, 退出码: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
