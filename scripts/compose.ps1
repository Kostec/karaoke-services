# Обёртка над docker compose: всегда Linux-движок Docker Desktop (контекст desktop-linux),
# активный по умолчанию Windows-движок не трогаем.
# Примеры:
#   ./scripts/compose.ps1 up -d --build
#   ./scripts/compose.ps1 --profile test run --rm tests
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & docker --context desktop-linux compose @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
