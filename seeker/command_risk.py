"""Separa comando cotidiano de comando que apaga ou derruba a máquina."""

from __future__ import annotations

import re

_DESTRUCTIVE = (
    re.compile(r"(?i)(^|[;&|]\s*)(remove-item|rmdir|erase|del|rd|rm|ri)\b"),
    re.compile(r"(?i)\b(clear-content|set-content|clear-item)\b"),
    re.compile(r"(?i)\b(format-volume|clear-disk|initialize-disk)\b"),
    re.compile(r"(?i)\b(stop-process|taskkill|stop-service|restart-computer|stop-computer)\b"),
    re.compile(r"(?i)(^|[;&|]\s*)shutdown\b"),
    re.compile(r"(?i)\breg(?:\.exe)?\s+delete\b"),
    re.compile(r"(?i)\bgit\s+clean\b"),
    re.compile(r"(?i)\bgit\s+reset\b[^\n]*--hard\b"),
    re.compile(r"(?i)\bgit\s+push\b[^\n]*--force\b"),
    re.compile(r"(?<![>&|])>(?!>|&)"),
)

_YES = {
    "sim",
    "sim pode",
    "pode",
    "pode sim",
    "pode rodar",
    "roda",
    "rode",
    "autorizo",
    "autorizado",
    "manda",
    "confirma",
    "confirmo",
    "ok",
    "yes",
    "claro",
}

_NO = {
    "nao",
    "não",
    "cancela",
    "recuso",
    "nao pode",
    "não pode",
    "no",
    "deixa",
    "para",
}


def is_destructive(command: str) -> bool:
    text = command or ""
    return any(pattern.search(text) for pattern in _DESTRUCTIVE)


def decision(text: str) -> bool | None:
    cleaned = re.sub(r"[!?.。,;:]+", "", (text or "").casefold())
    cleaned = " ".join(cleaned.split())
    if cleaned in _YES:
        return True
    if cleaned in _NO:
        return False
    return None
