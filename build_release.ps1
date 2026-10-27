[CmdletBinding()]
param(
    # By default FFmpeg and FFprobe are copied from the build machine PATH.
    [switch]$SkipMediaTools,
    # Include local VLC runtime so embedded video playback does not depend on the target PC.
    [switch]$WithVlcRuntime,
    # Include local Hugging Face cache for offline model distribution (often very large).
    [switch]$WithModelCache,
    # Preserve the PyInstaller work directory for package diagnostics.
    [switch]$KeepBuildFiles,
    # Finish media/runtime copying for an already completed PyInstaller output.
    [switch]$UseExistingBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$spec = Join-Path $projectRoot 'WorkTool.spec'
$distRoot = Join-Path $projectRoot 'dist'
$workRoot = Join-Path $projectRoot 'build'
$releaseDir = $null

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment was not found: $python. Run install first."
}
if (-not (Test-Path -LiteralPath $spec)) {
    throw "Package specification was not found: $spec"
}

if (-not $UseExistingBuild) {
    Write-Host 'Building stable onedir release with the project virtual environment...' -ForegroundColor Cyan
    & $python -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code: $LASTEXITCODE"
    }
} else {
    Write-Host 'Using existing PyInstaller output; only completing runtime files...' -ForegroundColor Cyan
}
# Do not hard-code the Chinese output folder name here. Windows PowerShell 5
# can read an UTF-8 script without BOM using a legacy code page, which corrupts
# non-ASCII path literals after PyInstaller has already completed successfully.
$releaseCandidates = @()
foreach ($candidateDir in (Get-ChildItem -LiteralPath $distRoot -Directory -ErrorAction SilentlyContinue)) {
    $candidateExe = @(Get-ChildItem -LiteralPath $candidateDir.FullName -Filter '*.exe' -File -ErrorAction SilentlyContinue)
    if ($candidateExe.Count -gt 0) {
        $releaseCandidates += $candidateDir
    }
}
$releaseCandidates = @($releaseCandidates | Sort-Object LastWriteTime -Descending)
if ($releaseCandidates.Count -lt 1) {
    $available = ($releaseCandidates | ForEach-Object { $_.FullName }) -join '; '
    throw "Cannot identify the onedir build output under $distRoot. Candidates: $available"
}
# 允许 dist 保留历史发布包；PyInstaller 刚写出的目录时间最新，优先使用它。
# 旧逻辑要求候选目录只能有一个，会在第二次封包时无故失败。
$releaseDir = ''
foreach ($candidateDir in $releaseCandidates) {
    $releaseDir = [string]$candidateDir.FullName
    break
}
if ([string]::IsNullOrWhiteSpace($releaseDir)) {
    throw 'The newest release candidate has no usable path.'
}
if ($releaseCandidates.Count -gt 1) {
    Write-Host "Multiple release folders found; using newest: $releaseDir" -ForegroundColor DarkYellow
}

if (-not $SkipMediaTools) {
    $binDir = Join-Path $releaseDir 'bin'
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    foreach ($toolName in @('ffmpeg.exe', 'ffprobe.exe')) {
        $tool = Get-Command $toolName -ErrorAction SilentlyContinue
        if ($null -eq $tool -or -not (Test-Path -LiteralPath $tool.Source)) {
            Write-Warning "Media tool was not found on the build PATH: $toolName"
            continue
        }
        Copy-Item -LiteralPath $tool.Source -Destination (Join-Path $binDir $toolName) -Force
        Write-Host "Bundled media tool: $toolName" -ForegroundColor Green
    }
}

if ($WithVlcRuntime) {
    $programFiles = [Environment]::GetFolderPath('ProgramFiles')
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $vlcCandidates = @(
        (Join-Path $programFiles 'VideoLAN\VLC'),
        (Join-Path $programFilesX86 'VideoLAN\VLC')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'libvlc.dll')) }
    $vlcRoot = $vlcCandidates | Select-Object -First 1
    if ($vlcRoot) {
        Copy-Item -LiteralPath $vlcRoot -Destination (Join-Path $releaseDir 'VLC') -Recurse -Force
        Write-Host 'Bundled VLC runtime. Verify VideoLAN/VLC redistribution licensing before release.' -ForegroundColor Green
    } else {
        Write-Warning 'VLC runtime was not found. The release falls back to thumbnails unless VLC is installed on the target PC.'
    }
}

# faster-whisper 通过 CTranslate2 使用 CUDA。NVIDIA 显卡驱动只提供驱动本身，
# 通常不包含 cublas/cublasLt 运行库；开发机装过 CUDA Toolkit 时容易被掩盖，
# 导致封装包到 RTX 4060 等用户电脑上只能回退 CPU。
$cudaRuntimeStatus = 'not bundled (CUDA runtime not found on build machine)'
$ct2Dirs = @(Get-ChildItem -LiteralPath $releaseDir -Directory -Recurse -Filter 'ctranslate2' -ErrorAction SilentlyContinue)
if ($ct2Dirs.Count -gt 0) {
    $cudaBinCandidates = @()
    if ($env:CUDA_PATH) {
        $cudaBinCandidates += (Join-Path $env:CUDA_PATH 'bin')
    }
    $cudaToolkitRoot = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'NVIDIA GPU Computing Toolkit\CUDA'
    if (Test-Path -LiteralPath $cudaToolkitRoot) {
        $cudaBinCandidates += @(Get-ChildItem -LiteralPath $cudaToolkitRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'bin' })
    }
    $cudaBinCandidates = @($cudaBinCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique)
    $runtimeNames = @('cublas64_12.dll', 'cublasLt64_12.dll', 'cudart64_12.dll')
    $copiedRuntimeNames = @()
    foreach ($runtimeName in $runtimeNames) {
        $runtimeSource = $null
        $pathCommand = Get-Command $runtimeName -ErrorAction SilentlyContinue
        if ($pathCommand -and (Test-Path -LiteralPath $pathCommand.Source)) {
            $runtimeSource = $pathCommand.Source
        }
        if (-not $runtimeSource) {
            foreach ($cudaBin in $cudaBinCandidates) {
                $candidate = Join-Path $cudaBin $runtimeName
                if (Test-Path -LiteralPath $candidate) {
                    $runtimeSource = $candidate
                    break
                }
            }
        }
        if ($runtimeSource) {
            foreach ($ct2Dir in $ct2Dirs) {
                Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $ct2Dir.FullName $runtimeName) -Force
            }
            $copiedRuntimeNames += $runtimeName
            Write-Host "Bundled CUDA runtime: $runtimeName" -ForegroundColor Green
        } else {
            Write-Warning "CUDA runtime was not found on the build machine: $runtimeName"
        }
    }
    if ($copiedRuntimeNames.Count -eq $runtimeNames.Count) {
        $cudaRuntimeStatus = 'bundled for CTranslate2 (' + ($copiedRuntimeNames -join ', ') + ')'
    } elseif ($copiedRuntimeNames.Count -gt 0) {
        $cudaRuntimeStatus = 'partially bundled (' + ($copiedRuntimeNames -join ', ') + ')'
    }
} else {
    Write-Warning 'CTranslate2 package was not found in the release output; Whisper GPU acceleration will be unavailable.'
}

if ($WithModelCache) {
    $modelCache = Join-Path $projectRoot 'hf_cache'
    if (Test-Path -LiteralPath $modelCache) {
        Copy-Item -LiteralPath $modelCache -Destination (Join-Path $releaseDir 'hf_cache') -Recurse -Force
        Write-Host 'Bundled Hugging Face model cache.' -ForegroundColor Green
    } else {
        Write-Warning 'No hf_cache directory was found; offline model cache was skipped.'
    }
}

$ffmpegStatus = if ($SkipMediaTools) { 'not included (SkipMediaTools)' } else { 'copied when available on build PATH' }
$vlcStatus = if ($WithVlcRuntime) { 'copied when available' } else { 'not bundled; target PC can use installed VLC' }
$cacheStatus = if ($WithModelCache) { 'copied when available' } else { 'not bundled; models download on first use' }
$buildInfo = @(
    '智能素材工作站 Windows release package',
    ('Build time: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    ('FFmpeg: ' + $ffmpegStatus),
    ('VLC runtime: ' + $vlcStatus),
    ('CUDA runtime for Whisper: ' + $cudaRuntimeStatus),
    ('HF model cache: ' + $cacheStatus),
    'Unzip and run the entire folder. Do not move only the exe file.'
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $releaseDir 'BUILD_INFO.txt') -Value $buildInfo -Encoding utf8

if (-not $KeepBuildFiles -and (Test-Path -LiteralPath $workRoot)) {
    Remove-Item -LiteralPath $workRoot -Recurse -Force
}

Write-Host ''
Write-Host "Build completed: $releaseDir" -ForegroundColor Cyan
Write-Host 'Test the complete release folder on a Windows PC without the development environment before distribution.' -ForegroundColor Yellow
