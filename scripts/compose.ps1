# Обёртка над docker compose: всегда Linux-движок Docker Desktop (контекст desktop-linux),
# активный по умолчанию Windows-движок не трогаем.
# Примеры:
#   ./scripts/compose.ps1 up -d --build
#   ./scripts/compose.ps1 --profile test run --rm tests
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    # Docker пишет ход сборки в stderr; в Windows PowerShell 5.1 при 'Stop' это ломало запуск
    # (например, при `2>&1 | ...`). Ошибкой считаем только код выхода docker.
    $ErrorActionPreference = 'Continue'
    & docker --context desktop-linux compose @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
