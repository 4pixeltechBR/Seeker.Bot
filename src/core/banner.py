"""
Banner de inicialização do Seeker.Bot.

Imprime polvo estilizado em ASCII + nome do projeto no terminal stdout.
Chamado pelo src/__main__.py durante o boot, antes do asyncio.run(main()).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime


# Cores ANSI (Windows 10+ habilita por padrão no Terminal; cmd.exe antigo
# ignora, mas as sequências não causam erro).
class C:
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def _build_polvo() -> str:
    """Gera polvo proceduralmente: cabeça elíptica + 8 tentáculos sinusoidais.

    Cada tentáculo é uma curva senoidal que parte de um ponto na borda
    inferior da cabeça e desce ondulando até a base, com ventosas espaçadas.

    O resultado é centralizado horizontalmente em uma largura fixa (WIDTH).
    """
    import math

    WIDTH = 60
    HEIGHT = 14
    RAMP = "█▓▒░·"

    cx, cy = WIDTH / 2, 4  # centro da cabeça
    rx, ry = 13, 3.5  # raios da elipse (mais larga que alta)

    canvas = [[" "] * WIDTH for _ in range(HEIGHT)]

    # ── Cabeça (elipse) com gradiente ─────────────────────────────
    for y in range(HEIGHT):
        for x in range(WIDTH):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            d2 = dx * dx + dy * dy
            if d2 <= 1.0:
                if d2 > 0.78:
                    ch = RAMP[0]  # █ borda
                elif d2 > 0.5:
                    ch = RAMP[1]  # ▓
                elif d2 > 0.25:
                    ch = RAMP[2]  # ▒
                else:
                    ch = RAMP[3]  # ░ interior
                canvas[y][x] = ch
            elif d2 <= 1.15:
                canvas[y][x] = RAMP[4]  # · antialias

    # ── Olhos grandes e expressivos ────────────────────────────────
    eye_y = int(cy)
    # olho esquerdo
    for i, ch in enumerate("oO"):
        x = int(cx) - 5 + i
        if 0 <= x < WIDTH:
            canvas[eye_y][x] = ch
    # olho direito
    for i, ch in enumerate("Oo"):
        x = int(cx) + 3 + i
        if 0 <= x < WIDTH:
            canvas[eye_y][x] = ch

    # ── Boca (sorriso suave) ──────────────────────────────────────
    mouth_y = int(cy) + 1
    for i, ch in enumerate("\\v/ "):
        x = int(cx) - 2 + i
        if 0 <= x < WIDTH and canvas[mouth_y][x] in (" ", "░", "▒", RAMP[4]):
            canvas[mouth_y][x] = ch

    # ── 8 tentáculos descendo da borda inferior da cabeça ────────
    n_tentacles = 8
    tentacle_top_y = int(cy + ry)  # linha de partida (borda inferior)
    for i in range(n_tentacles):
        # distribui tentáculos uniformemente ao longo da borda inferior
        # 0% a 100% da largura da cabeça
        if n_tentacles == 1:
            t_pos = 0.5
        else:
            t_pos = i / (n_tentacles - 1)
        # ponto de partida na borda da elipse
        start_x = cx - rx + t_pos * 2 * rx
        # pequeno ajuste para começar exatamente na borda inferior
        start_x = int(round(start_x))

        # parâmetros do tentáculo
        length = 5  # quantas linhas desce
        amp = 3.5  # amplitude da ondulação lateral
        freq = 1.5  # frequência da onda
        phase = i * 0.7  # fases diferentes para entrelaçamento

        for t in range(length):
            progress = (t + 1) / length
            # x oscila com seno
            x = start_x + math.sin(progress * math.pi * freq + phase) * amp
            y = tentacle_top_y + (t + 1)
            x_int = int(round(x))
            y_int = int(round(y))
            if 0 <= y_int < HEIGHT and 0 <= x_int < WIDTH:
                # alterna entre tentáculo (│) e ventosa (o)
                ch = "o" if t % 2 == 0 else "│"
                canvas[y_int][x_int] = ch

    # Converte canvas em string
    lines = ["".join(row).rstrip() for row in canvas]
    return "\n".join(lines)


POLVO = _build_polvo()


def _supports_ansi() -> bool:
    """Detecta se o terminal provavelmente suporta ANSI escape codes."""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    # Windows 10+ (build 14931) habilita ANSI em cmd.exe/PowerShell por padrão.
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # Habilita ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) no console
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                if mode.value & 0x0004:
                    return True
                # Tenta habilitar
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            pass
        return False
    # Unix-like: sempre tem ANSI
    return True


def _enable_windows_utf8() -> bool:
    """Define o code page do console Windows para 65001 (UTF-8) para o polvo
    e demais caracteres acentuados renderizarem corretamente no cmd.exe.
    Returns True se o code page agora é UTF-8."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        # Também reconfigura o stdout para UTF-8 (Python)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        # Verifica se está de fato em UTF-8
        import ctypes as _c

        cp = _c.windll.kernel32.GetConsoleOutputCP()
        return cp == 65001
    except Exception:
        return False


def print_banner() -> None:
    """Imprime o cabeçalho do Seeker.Bot no terminal."""
    utf8_ok = _enable_windows_utf8()
    use_color = _supports_ansi()

    if use_color:
        cyan = C.CYAN
        magenta = C.MAGENTA
        yellow = C.YELLOW
        bold = C.BOLD
        dim = C.DIM
        reset = C.RESET
    else:
        cyan = magenta = yellow = bold = dim = reset = ""

    if utf8_ok:
        # Banner com box-drawing characters e bloco (Unicode)
        name_lines = [
            f"  {bold}{magenta}███████╗███████╗███████╗██╗  ██╗███████╗██████╗ {reset}",
            f"  {bold}{magenta}██╔════╝██╔════╝██╔════╝██║ ██╔╝██╔════╝██╔══██╗{reset}",
            f"  {bold}{magenta}███████╗█████╗  █████╗  █████╔╝ █████╗  ██████╔╝{reset}",
            f"  {bold}{magenta}╚════██║██╔══╝  ██╔══╝  ██╔═██╗ ██╔══╝  ██╔══██╗{reset}",
            f"  {bold}{magenta}███████║███████╗███████╗██║  ██╗███████╗██║  ██║{reset}",
            f"  {bold}{magenta}╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝{reset}",
        ]
    else:
        # Fallback ASCII puro (cp1252 / cmd.exe antigo)
        name_lines = [
            f"  {bold}{magenta}+====================================================+{reset}",
            f"  {bold}{magenta}|  S E E K E R . B O T   -   Agente Inteligente    |{reset}",
            f"  {bold}{magenta}+====================================================+{reset}",
        ]

    lines = [
        "",
        f"{cyan}{POLVO}{reset}",
        "",
        *name_lines,
        "",
        f"  {bold}{yellow}>> Agente Inteligente <<{reset}",
        "",
        f"  {dim}v3.12  -  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{reset}",
        "",
    ]

    for line in lines:
        try:
            print(line)
        except UnicodeEncodeError:
            # Fallback: remove caracteres não-ASCII se o terminal não suportar
            print(line.encode("ascii", "replace").decode("ascii"))

    sys.stdout.flush()


if __name__ == "__main__":
    print_banner()
