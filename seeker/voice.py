"""Transcrição pelo Gemini. A fala de volta usa a voz do Windows na janela."""

from __future__ import annotations

import httpx


def transcribe(client: httpx.Client, base_url: str, model: str, api_key: str, audio_b64: str, mime: str) -> str:
    if not api_key:
        raise RuntimeError("A voz precisa da chave do Gemini no .env.")
    if not audio_b64:
        raise RuntimeError("Não recebi áudio.")
    response = client.post(
        f"{base_url.rstrip('/')}/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Transcreva este áudio em português do Brasil. "
                                "Responda só com as palavras ditas, sem comentário."
                            )
                        },
                        {"inlineData": {"mimeType": mime or "audio/webm", "data": audio_b64}},
                    ],
                }
            ]
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"A transcrição falhou (HTTP {response.status_code}).")
    texts = []
    for candidate in response.json().get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text") and not part.get("thought"):
                texts.append(part["text"])
    text = " ".join(part.strip() for part in texts).strip()
    if not text:
        raise RuntimeError("Não ouvi nada.")
    return text
