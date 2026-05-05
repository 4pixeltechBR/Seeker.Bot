param (
    [string]$DriveLetter = "I:"
)

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "🚀 Seeker.Bot Storage Watchdog" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# 1. Verifica se a unidade já existe
if (Test-Path "$DriveLetter\") {
    Write-Host "[OK] Unidade $DriveLetter encontrada e acessível." -ForegroundColor Green
    exit 0
}

Write-Host "[!] Unidade $DriveLetter não encontrada. Tentando forçar montagem..." -ForegroundColor Yellow

# 2. Tenta forçar o refresh do Google Drive Desktop se o processo estiver rodando
$gdProcess = Get-Process "GoogleDriveFS" -ErrorAction SilentlyContinue
if ($gdProcess) {
    Write-Host "[*] Processo Google Drive detectado. Forçando sinal de I/O..."
    # Tenta listar drives para forçar o Windows a re-escanear montagens de rede
    Get-PSDrive -PSProvider FileSystem | Out-Null
    Start-Sleep -Seconds 2
} else {
    Write-Host "[ERR] Google Drive Desktop não está rodando. Por favor, inicie o app." -ForegroundColor Red
}

# 3. Verificação final
if (Test-Path "$DriveLetter\") {
    Write-Host "[OK] Unidade $DriveLetter montada com sucesso após refresh." -ForegroundColor Green
    exit 0
} else {
    Write-Host "[FAIL] Não foi possível encontrar a unidade $DriveLetter." -ForegroundColor Red
    Write-Host "Certifique-se de que o Google Drive Desktop está configurado para montar como $DriveLetter"
    exit 1
}
