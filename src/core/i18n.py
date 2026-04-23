"""
Internationalization support for Seeker.Bot
src/core/i18n.py
"""

import json
from pathlib import Path
from typing import Optional

class I18n:
    """Simple i18n provider for Seeker.Bot"""
    
    def __init__(self, default_lang: str = "en_US"):
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.translations = {}
        self._load_translations()
    
    def _load_translations(self):
        """Load translation files"""
        locale_dir = Path(__file__).parent.parent.parent / "config" / "locales"
        
        for lang_file in locale_dir.glob("*.json"):
            lang_code = lang_file.stem
            with open(lang_file, 'r', encoding='utf-8') as f:
                self.translations[lang_code] = json.load(f)
    
    def set_language(self, lang: str):
        """Set current language"""
        if lang in self.translations:
            self.current_lang = lang
    
    def t(self, key: str, **kwargs) -> str:
        """Translate a key"""
        try:
            text = self.translations[self.current_lang].get(key)
            if text is None:
                text = self.translations[self.default_lang].get(key, f"[{key}]")
            
            if kwargs:
                text = text.format(**kwargs)
            return text
        except Exception as e:
            return f"[{key}]"

# Global i18n instance
_i18n = None

def get_i18n() -> I18n:
    """Get or create global i18n instance"""
    global _i18n
    if _i18n is None:
        _i18n = I18n()
    return _i18n

def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Translate a key with optional language override"""
    i18n = get_i18n()
    if lang:
        current = i18n.current_lang
        i18n.set_language(lang)
        result = i18n.t(key, **kwargs)
        i18n.set_language(current)
        return result
    return i18n.t(key, **kwargs)
