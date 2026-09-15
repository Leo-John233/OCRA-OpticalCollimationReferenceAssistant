[CmdletBinding()]
param(
    [string]$Name,
    [string]$EnvRoot,
    [switch]$List
)

$ErrorActionPreference = "Stop"

# 所有路径都从项目位置解析避免依赖当前工作目录
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StatePath = Join-Path $PSScriptRoot "python-env.local.json"
$StateTempPath = "$StatePath.tmp"
$PyrightPath = Join-Path $ProjectRoot "pyrightconfig.json"
$PyrightTempPath = "$PyrightPath.tmp"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"

# 命令参数和环境变量优先于本机持久选择
$SavedState = $null
if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    $SavedState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
}
if ([string]::IsNullOrWhiteSpace($Name) -and -not [string]::IsNullOrWhiteSpace($env:SERENA_PYTHON_ENV)) {
    $Name = $env:SERENA_PYTHON_ENV
}
if ([string]::IsNullOrWhiteSpace($Name) -and $null -ne $SavedState) {
    $Name = [string]$SavedState.name
}
if ([string]::IsNullOrWhiteSpace($EnvRoot) -and -not [string]::IsNullOrWhiteSpace($env:SERENA_ENV_ROOT)) {
    $EnvRoot = $env:SERENA_ENV_ROOT
}
if ([string]::IsNullOrWhiteSpace($EnvRoot) -and $null -ne $SavedState) {
    $EnvRoot = [string]$SavedState.envRoot
}
if ([string]::IsNullOrWhiteSpace($EnvRoot) -and (Test-Path -LiteralPath "D:\miniconda3\envs" -PathType Container)) {
    $EnvRoot = "D:\miniconda3\envs"
}
if ([string]::IsNullOrWhiteSpace($EnvRoot) -and -not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
    $EnvRoot = Split-Path -Parent $env:CONDA_PREFIX
}
if ([string]::IsNullOrWhiteSpace($EnvRoot)) {
    throw "请通过 -EnvRoot 或 SERENA_ENV_ROOT 指定环境根目录"
}

function Get-EnvironmentInfo {
    param(
        [string]$Root,
        [string]$EnvironmentName
    )

    if ([System.IO.Path]::GetFileName($EnvironmentName) -ne $EnvironmentName) {
        throw "环境名称不能包含路径分隔符"
    }

    $ResolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $EnvironmentPath = [System.IO.Path]::GetFullPath((Join-Path $ResolvedRoot $EnvironmentName))
    $ExpectedPrefix = "$ResolvedRoot$([System.IO.Path]::DirectorySeparatorChar)"
    if (-not $EnvironmentPath.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "环境路径必须位于 $ResolvedRoot"
    }

    $PythonPath = Join-Path $EnvironmentPath "python.exe"
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "未找到环境解释器 $PythonPath"
    }

    $PythonVersion = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($PythonVersion)) {
        throw "无法读取环境 Python 版本 $PythonPath"
    }

    [PSCustomObject]@{
        Name = $EnvironmentName
        Root = $ResolvedRoot
        Path = $EnvironmentPath
        Python = $PythonPath
        Version = $PythonVersion.Trim()
    }
}

if ($List) {
    if (-not (Test-Path -LiteralPath $EnvRoot -PathType Container)) {
        throw "未找到环境根目录 $EnvRoot"
    }
    Get-ChildItem -LiteralPath $EnvRoot -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "python.exe") -PathType Leaf } |
        ForEach-Object {
            $Version = & (Join-Path $_.FullName "python.exe") -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            [PSCustomObject]@{
                Name = $_.Name
                PythonVersion = $Version.Trim()
                Path = $_.FullName
            }
        } |
        Format-Table -AutoSize
    exit 0
}

# 未指定名称时使用项目默认分析环境
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = "Python3.13"
}

$Environment = Get-EnvironmentInfo -Root $EnvRoot -EnvironmentName $Name

# 提前验证项目依赖避免 Serena 启动后才出现成片缺失导入
& $Environment.Python -c "import PyQt6, cv2, numpy, PIL"
if ($LASTEXITCODE -ne 0) {
    throw "环境 $($Environment.Name) 缺少项目依赖 请运行 `"$($Environment.Python)`" -m pip install -r `"$RequirementsPath`""
}

$State = [ordered]@{
    envRoot = $Environment.Root
    name = $Environment.Name
}
$State | ConvertTo-Json | Set-Content -LiteralPath $StateTempPath -Encoding utf8
Move-Item -LiteralPath $StateTempPath -Destination $StatePath -Force

$PyrightConfig = [ordered]@{
    extends = "./pyrightconfig.base.json"
    venvPath = $Environment.Root.Replace('\', '/')
    venv = $Environment.Name
    pythonVersion = $Environment.Version
}
$PyrightConfig | ConvertTo-Json | Set-Content -LiteralPath $PyrightTempPath -Encoding utf8
Move-Item -LiteralPath $PyrightTempPath -Destination $PyrightPath -Force

Write-Host "Serena 分析环境已选择 $($Environment.Name)"
Write-Host "Python $($Environment.Version)  $($Environment.Python)"
