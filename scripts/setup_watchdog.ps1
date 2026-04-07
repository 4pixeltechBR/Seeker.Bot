# ══════════════════════════════════════════════════════════
#  Seeker.Bot — Setup do Watchdog no Windows
#  scripts/setup_watchdog.ps1
#
#  Registra o watchdog no Task Scheduler do Windows.
#  Resultado: Seeker.Bot inicia automaticamente com o Windows.
#
#  Uso (rodar como Administrador):
#    .\scripts\setup_watchdog.ps1
#
#  Para remover:
#    .\scripts\setup_watchdog.ps1 -Remove
# ══════════════════════════════════════════════════════════

param(
    [switch]$Remove
)

$TaskName = "SeekerBot-Watchdog"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$WatchdogScript = Join-Path $ProjectRoot "scripts\watchdog.ps1"

# ── REMOVER ───────────────────────────────────────────────
if ($Remove) {
    Write-Host ""
    Write-Host "  Removendo tarefa '$TaskName'..." -ForegroundColor Yellow
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "  ✅ Tarefa removida com sucesso." -ForegroundColor Green
    }
    catch {
        Write-Host "  ❌ Tarefa não encontrada ou erro: $_" -ForegroundColor Red
    }
    Write-Host ""
    exit
}

# ── VALIDAÇÕES ────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   SEEKER.BOT — SETUP DO WATCHDOG         ║" -ForegroundColor Cyan
Write-Host "  ╚═══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Verifica se está rodando como admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "  ⚠️  Recomendado rodar como Administrador para" -ForegroundColor Yellow
    Write-Host "     garantir que a tarefa inicie com o Windows." -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "  Continuar mesmo assim? (s/n)"
    if ($continue -ne "s") { exit }
}

# Verifica se o watchdog existe
if (-not (Test-Path $WatchdogScript)) {
    Write-Host "  ❌ Watchdog não encontrado: $WatchdogScript" -ForegroundColor Red
    exit 1
}

# Verifica se o venv existe
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "  ❌ Python venv não encontrado: $VenvPython" -ForegroundColor Red
    Write-Host "     Execute: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "  Projeto: $ProjectRoot"
Write-Host "  Watchdog: $WatchdogScript"
Write-Host "  Python: $VenvPython"
Write-Host ""

# ── REGISTRAR TAREFA ──────────────────────────────────────

# Remove tarefa existente se houver
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  → Removendo tarefa existente..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}
catch {}

# Ação: rodar PowerShell com o watchdog, janela oculta
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WatchdogScript`"" `
    -WorkingDirectory $ProjectRoot

# Trigger: no logon do usuário atual
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: reiniciar se falhar, não parar se rodando em bateria
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Registra
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Seeker.Bot Watchdog - Mantém o bot rodando 24/7" `
        -RunLevel Highest `
        -Force

    Write-Host "  ✅ Tarefa '$TaskName' registrada com sucesso!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  O Seeker.Bot agora inicia automaticamente quando" -ForegroundColor Cyan
    Write-Host "  você fizer login no Windows." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Comandos úteis:" -ForegroundColor Gray
    Write-Host "    Iniciar agora:  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "    Parar:          Stop-ScheduledTask -TaskName '$TaskName'"
    Write-Host "    Status:         Get-ScheduledTask -TaskName '$TaskName' | Select State"
    Write-Host "    Remover:        .\scripts\setup_watchdog.ps1 -Remove"
    Write-Host "    Ver logs:       Get-Content data\watchdog.log -Tail 20"
    Write-Host ""

    # Pergunta se quer iniciar agora
    $startNow = Read-Host "  Iniciar o Seeker.Bot agora? (s/n)"
    if ($startNow -eq "s") {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
        $task = Get-ScheduledTask -TaskName $TaskName
        if ($task.State -eq "Running") {
            Write-Host ""
            Write-Host "  🚀 Seeker.Bot rodando em background!" -ForegroundColor Green
            Write-Host "     Manda mensagem no Telegram pra testar." -ForegroundColor Cyan
        }
        else {
            Write-Host ""
            Write-Host "  ⚠️  Estado: $($task.State)" -ForegroundColor Yellow
            Write-Host "     Verifique: Get-Content data\watchdog.log -Tail 20" -ForegroundColor Yellow
        }
    }
}
catch {
    Write-Host "  ❌ Falha ao registrar: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Tente rodar como Administrador:" -ForegroundColor Yellow
    Write-Host "    Start-Process powershell -Verb RunAs -ArgumentList '-File .\scripts\setup_watchdog.ps1'"
}

Write-Host ""
