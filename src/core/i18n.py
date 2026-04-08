"""
Seeker.Bot — Internationalization (i18n) Support
src/core/i18n.py

Simples sistema de tradução baseado em JSON.
Suporta português (pt_BR) e inglês (en_US).
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("seeker.i18n")

# Cache de locales carregadas
_LOCALES: dict[str, dict[str, str]] = {}


def get_locales_dir() -> Path:
    """Retorna caminho para o diretório de locales."""
    return Path(__file__).parent.parent.parent / "config" / "locales"


def load_locale(lang: str = "pt_BR") -> dict[str, str]:
    """Carrega um locale JSON e armazena em cache."""
    if lang in _LOCALES:
        return _LOCALES[lang]

    locales_dir = get_locales_dir()
    locale_file = locales_dir / f"{lang}.json"

    if not locale_file.exists():
        log.warning(f"[i18n] Locale {lang} não encontrado em {locale_file}")
        return {}

    try:
        with open(locale_file, "r", encoding="utf-8") as f:
            locale_data = json.load(f)
            _LOCALES[lang] = locale_data
            log.info(f"[i18n] Loaded locale {lang} with {len(locale_data)} entries")
            return locale_data
    except Exception as e:
        log.error(f"[i18n] Erro ao carregar {locale_file}: {e}")
        return {}


def get_text(key: str, lang: Optional[str] = None) -> str:
    """
    Retorna texto traduzido para um key.

    Args:
        key: Chave da tradução (ex: "cmd.start")
        lang: Idioma (pt_BR, en_US). Se None, usa variável de ambiente LANGUAGE

    Returns:
        Texto traduzido, ou a chave se não encontrado
    """
    if lang is None:
        lang = os.getenv("LANGUAGE", "pt_BR")

    locale = load_locale(lang)
    return locale.get(key, key)  # Fallback: retorna a chave se não encontrado


def get_all_commands(lang: Optional[str] = None) -> dict[str, str]:
    """Retorna dicionário de todos os comandos traduzidos."""
    if lang is None:
        lang = os.getenv("LANGUAGE", "pt_BR")

    locale = load_locale(lang)
    return {k: v for k, v in locale.items() if k.startswith("cmd.")}


def get_all_skills(lang: Optional[str] = None) -> dict[str, str]:
    """Retorna dicionário de todas as skills traduzidas."""
    if lang is None:
        lang = os.getenv("LANGUAGE", "pt_BR")

    locale = load_locale(lang)
    return {k: v for k, v in locale.items() if k.startswith("skill.")}


def get_niches(lang: Optional[str] = None) -> dict[str, str]:
    """Retorna dicionário de nichos traduzidos."""
    if lang is None:
        lang = os.getenv("LANGUAGE", "pt_BR")

    locale = load_locale(lang)
    return {k: v for k, v in locale.items() if k.startswith("niches.")}
