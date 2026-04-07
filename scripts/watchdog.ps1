# ══════════════════════════════════════════════════════════
#  Seeker.Bot — Watchdog
#  scripts/watchdog.ps1
#
#  Mantém o bot rodando 24/7. Se crashar, reinicia.
#  Se crashar 3 vezes em 5 minutos, para (kill switch).
#
#  Pode rodar:
#    - Manual:     .\scripts\watchdog.ps1
#    - Background: Start-Process powershell -ArgumentList "-File .\scripts\watchdog.ps1" -WindowStyle Hidden
#    - Automático: via Task Scheduler (setup_watchdog.ps1)
# ══════════════════════════════════════════════════════════

# Resolve o caminho do projeto (watchdog está em scripts/)
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BotModule = "src.channels.telegram.bot"
$LogFile = Join-Path $ProjectRoot "data\watchdog.log"
$PidFile = Join-Path $ProjectRoot "data\watchdog.pid"

# Kill switch
$MaxCrashes = 3
$CrashWindow = 300  # 5 minutos

# Tracking
$CrashTimes = @()

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    # Só escreve no console se tiver console
    try { Write-Host $line } catch {}
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

# Garante que a pasta data existe
$dataDir = Join-Path $ProjectRoot "data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}

# Salva PID pra poder matar o watchdog de fora
$PID | Out-File -FilePath $PidFile -Force

Write-Log "═══════════════════════════════════════════"
Write-Log "  SEEKER.BOT WATCHDOG INICIADO"
Write-Log "  PID: $PID"
Write-Log "  Projeto: $ProjectRoot"
Write-Log "  Python: $VenvPython"
Write-Log "  Kill switch: $MaxCrashes crashes em $($CrashWindow)s"
Write-Log "═══════════════════════════════════════════"

# Verifica se o Python existe
if (-not (Test-Path $VenvPython)) {
    Write-Log "ERRO: Python não encontrado em $VenvPython"
    exit 1
}

# Limpa processos anteriores do bot (evita duplicatas)
$existingBots = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*$BotModule*"
}
if ($existingBots) {
    Write-Log "Matando instâncias anteriores do bot..."
    $existingBots | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

while ($true) {
    Write-Log "Iniciando Seeker.Bot..."
    $startTime = Get-Date

    try {
        # Roda o bot como processo filho
        $process = Start-Process -FilePath $VenvPython `
            -ArgumentList "-u", "-m", $BotModule `
            -WorkingDirectory $ProjectRoot `
            -NoNewWindow `
            -PassThru `
            -RedirectStandardOutput (Join-Path $dataDir "bot_stdout.log") `
            -RedirectStandardError (Join-Path $dataDir "bot_stderr.log")

        Write-Log "Bot iniciado (PID: $($process.Id))"

        # Espera o processo terminar
        $process.WaitForExit()
        $exitCode = $process.ExitCode
    }
    catch {
        $exitCode = -1
        Write-Log "EXCEÇÃO ao iniciar: $_"
    }

    $endTime = Get-Date
    $runtime = ($endTime - $startTime).TotalSeconds
    Write-Log "Bot encerrado. Código: $exitCode | Runtime: $([math]::Round($runtime))s"

    # Se rodou mais de 5 minutos, reseta crashes (não é loop de crash)
    if ($runtime -gt $CrashWindow) {
        $CrashTimes = @()
    }

    # Registra crash
    $CrashTimes += (Get-Date)

    # Remove crashes fora da janela
    $cutoff = (Get-Date).AddSeconds(-$CrashWindow)
    $CrashTimes = @($CrashTimes | Where-Object { $_ -gt $cutoff })

    Write-Log "Crashes recentes: $($CrashTimes.Count)/$MaxCrashes"

    # Kill switch
    if ($CrashTimes.Count -ge $MaxCrashes) {
        Write-Log "═══════════════════════════════════════════"
        Write-Log "  🔴 KILL SWITCH ATIVADO"
        Write-Log "  $MaxCrashes crashes em menos de $($CrashWindow)s"
        Write-Log "  Verifique: data\bot_stderr.log"
        Write-Log "  Para reiniciar: .\scripts\watchdog.ps1"
        Write-Log "═══════════════════════════════════════════"
        break
    }

    # Backoff antes de reiniciar
    $delay = 5 * $CrashTimes.Count  # 5s, 10s, 15s
    Write-Log "Reiniciando em $($delay)s..."
    Start-Sleep -Seconds $delay
}

# Limpa PID file
Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
Write-Log "Watchdog encerrado."
