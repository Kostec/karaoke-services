# Резервная копия правок UltraSinger: git format-patch origin/main..karaoke-local
# из локального репозитория UltraSinger в patches/karaoke-local.patch этого репозитория.
# Репозиторий UltraSinger только читается: ни fetch, ни checkout, ни запись в него.
# Примеры:
#   ./scripts/export-ultrasinger-patch.ps1
#   ./scripts/export-ultrasinger-patch.ps1 -Repo D:/Projects/UltraSinger -Base origin/main -Branch karaoke-local
param(
    [string]$Repo = 'D:/Projects/UltraSinger',
    [string]$Base = 'origin/main',
    [string]$Branch = 'karaoke-local'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root 'patches'
$outFile = Join-Path $outDir "$Branch.patch"

if (-not (Test-Path (Join-Path $Repo '.git'))) {
    throw "Не найден git-репозиторий UltraSinger: $Repo"
}
foreach ($ref in @($Base, $Branch)) {
    & git -C $Repo rev-parse --verify --quiet "$ref^{commit}" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "В $Repo нет ветки или ссылки '$ref'" }
}

$count = [int](& git -C $Repo rev-list --count "$Base..$Branch")
if ($count -eq 0) { throw "В '$Branch' нет коммитов поверх '$Base' — сохранять нечего" }

New-Item -ItemType Directory -Force $outDir | Out-Null
# Патчи пишет сам git (байт в байт, без перекодировки консолью PowerShell) во временную папку,
# затем склеиваем их в один файл. Применять так: git am patches/karaoke-local.patch
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("us-patch-" + [guid]::NewGuid())
try {
    & git -C $Repo format-patch --no-signature -o $tmp "$Base..$Branch" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git format-patch завершился с кодом $LASTEXITCODE" }
    $stream = [System.IO.File]::Create($outFile)
    try {
        foreach ($f in (Get-ChildItem $tmp -Filter '*.patch' | Sort-Object Name)) {
            $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
            $stream.Write($bytes, 0, $bytes.Length)
        }
    } finally { $stream.Dispose() }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

$head = (& git -C $Repo rev-parse --short $Branch).Trim()
Write-Host "Сохранено коммитов: $count ($Base..$Branch, $head) -> $outFile"
