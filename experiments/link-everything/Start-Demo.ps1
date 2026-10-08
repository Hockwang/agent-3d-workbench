param(
    [switch]$CheckOnly,
    [string]$BackendPython,
    [string]$WorkbenchPython,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8766,
    [ValidateRange(1024, 65535)][int]$WorkbenchPort = 8767
)

$ErrorActionPreference = 'Stop'
$demoRoot = $PSScriptRoot
$demoOutputs = Join-Path $demoRoot 'outputs'
$backendDefault = Join-Path $demoRoot '.venv\Scripts\python.exe'
$repositoryRoot = Split-Path (Split-Path $demoRoot -Parent) -Parent
$workbenchDefault = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
if ($BackendPort -eq $WorkbenchPort) { throw 'BackendPort and WorkbenchPort must differ.' }
if (-not $BackendPython) { $BackendPython = $env:CONNECTION_DEMO_BACKEND_PYTHON }
if (-not $WorkbenchPython) { $WorkbenchPython = $env:CONNECTION_DEMO_WORKBENCH_PYTHON }
if (-not $BackendPython) { $BackendPython = $backendDefault }
if (-not $WorkbenchPython) { $WorkbenchPython = $workbenchDefault }

function Assert-Python {
    param([string]$Executable, [string]$Label)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "$Label Python 不存在：$Executable。请按 README 用 uv 建立两个独立 Python 3.12 环境；也可用 -BackendPython / -WorkbenchPython 或同名 CONNECTION_DEMO_*_PYTHON 环境变量指定解释器。"
    }
    $version = & $Executable -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    if ($LASTEXITCODE -ne 0 -or $version -ne '3.12') {
        throw "$Label 需要 Python 3.12：$Executable（检测到 $version）"
    }
}

function Test-DemoService {
    param([int]$Port, [string]$Kind)
    try {
        if ($Kind -eq 'backend') {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if (-not $health.ok -or $health.service -ne 'connection-design') { return $false }
            $project = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/project" -TimeoutSec 3
            $manual = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/manual/project" -TimeoutSec 3
            $assembly = @($project.artifacts | Where-Object { $_.id -eq 'assembly.glb' })
            if ($project.id -ne 'camera-connection-demo' -or $assembly.Count -ne 1 -or $manual.schema -ne 'manual-connectors.project/v1') { return $false }
            $expected = [IO.Path]::GetFullPath((Join-Path $demoOutputs 'revisions')) + [IO.Path]::DirectorySeparatorChar
            return ([IO.Path]::GetFullPath([string]$assembly[0].absolute_path)).StartsWith($expected, [StringComparison]::OrdinalIgnoreCase)
        }
        # Session token is kept in memory and never written to logs or the console.
        $session = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/session" -TimeoutSec 3
        $expectedJob = [IO.Path]::GetFullPath((Join-Path $demoOutputs 'workbench_project'))
        if (-not $session.ok -or ([IO.Path]::GetFullPath([string]$session.job)) -ne $expectedJob) { return $false }
        $headers = @{ 'X-Studio-Token' = [string]$session.token }
        $state = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/assembly/project" -Headers $headers -TimeoutSec 3
        $manualState = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/assembly/project?source=manual" -Headers $headers -TimeoutSec 3
        $expected = [IO.Path]::GetFullPath((Join-Path $demoOutputs 'revisions')) + [IO.Path]::DirectorySeparatorChar
        $manualExpected = [IO.Path]::GetFullPath((Join-Path $demoOutputs 'manual')) + [IO.Path]::DirectorySeparatorChar
        return ($state.units -eq 'm' -and ([IO.Path]::GetFullPath([string]$state.import_file)).StartsWith($expected, [StringComparison]::OrdinalIgnoreCase) -and
            $manualState.units -eq 'm' -and ([IO.Path]::GetFullPath([string]$manualState.import_file)).StartsWith($manualExpected, [StringComparison]::OrdinalIgnoreCase))
    }
    catch { return $false }
}

$services = @(
    @{ Name = '连接设计后端'; Kind = 'backend'; Port = $BackendPort; Script = 'backend\server.py'; Extra = @('--port', [string]$BackendPort); Python = $BackendPython },
    @{ Name = '3D 工作台与装配模块'; Kind = 'workbench'; Port = $WorkbenchPort; Script = 'integration\serve_workbench.py'; Extra = @('--port', [string]$WorkbenchPort); Python = $WorkbenchPython }
)

# Inspect both ports before starting either service. Never terminate a port owner.
foreach ($service in $services) {
    $service.Healthy = Test-DemoService -Port $service.Port -Kind $service.Kind
    if (-not $service.Healthy) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $service.Port -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) {
            throw "端口 $($service.Port) 已被其他或未通过身份检查的服务占用；未终止任何进程。请检查该端口后重试。"
        }
        if ($CheckOnly) { throw "$($service.Name) 尚未运行（端口 $($service.Port)）。检查模式没有启动服务。" }
    }
}

foreach ($service in $services) {
    if ($service.Healthy) {
        Write-Host "$($service.Name)：已运行且身份检查通过，保留当前进程。"
        continue
    }
    Assert-Python -Executable $service.Python -Label $service.Name
    New-Item -ItemType Directory -Force -Path $demoOutputs | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $scriptPath = Join-Path $demoRoot $service.Script
    $arguments = @('-X', 'utf8', '-u', ('"' + $scriptPath + '"')) + $service.Extra
    $stdout = Join-Path $demoOutputs "$($service.Kind)-$stamp.stdout.log"
    $stderr = Join-Path $demoOutputs "$($service.Kind)-$stamp.stderr.log"
    $started = Start-Process -FilePath $service.Python -ArgumentList $arguments -WorkingDirectory $demoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $healthy = Test-DemoService -Port $service.Port -Kind $service.Kind
        if ($healthy) { break }
        $started.Refresh()
        if ($started.HasExited) { throw "$($service.Name) 启动后退出。请查看 $stderr" }
    } while ((Get-Date) -lt $deadline)
    if (-not $healthy) { throw "$($service.Name) 未在 20 秒内通过检查。请查看 $stderr；未自动终止任何进程。" }
    Write-Host "$($service.Name)：已在隐藏窗口启动。日志：$stdout"
}

Write-Host "工作台：http://127.0.0.1:$WorkbenchPort/?mode=assembly&assemblyBackendPort=$BackendPort"
Write-Host "手动分件与连接：http://127.0.0.1:$BackendPort/manual.html"
Write-Host "预设与流程：http://127.0.0.1:$BackendPort/presets.html"
Write-Host "独立模块：http://127.0.0.1:$BackendPort/"
