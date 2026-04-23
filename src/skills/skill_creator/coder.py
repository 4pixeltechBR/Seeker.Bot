"""
Seeker.Bot — Skill Creator Engine (Patcher L3)

Motor de codificação autônoma. Gera código via DeepSeek,
pede aprovação humana via Telegram (AFK Protocol Tier 1),
e escreve o arquivo no disco apenas se aprovado.
"""
import os
import json
import logging

from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import ModelRouter, CognitiveRole
from src.skills.vision.afk_protocol import AFKProtocol, PermissionResult

log = logging.getLogger("seeker.coder")


class SkillCreatorEngine:
    """Motor de codificação autônoma do Seeker.Bot (Patcher L3)"""

    @staticmethod
    async def process_coding_request(
        prompt: str,
        afk_protocol: AFKProtocol,
        model_router: ModelRouter,
        api_keys: dict[str, str],
    ) -> str:
        """
        Recebe um pedido em linguagem natural, gera código via DeepSeek,
        pede aprovação via Telegram e escreve o arquivo no disco.
        """
        if not afk_protocol:
            return "❌ AFKProtocol não acoplado. Impossível pedir permissão para escrever código."

        sys_prompt = (
            "Você é o Seeker.Bot Godmode Coder.\n"
            "Retorne APENAS um JSON estrito seguindo esta estrutura, "
            "sem markdown envelopando (apenas o texto puro JSON):\n"
            "{\n"
            '  "file_path": "src/skills/nome_da_skill/goal.py",\n'
            '  "explicacao": "Resumo de 2 linhas sobre o que o código faz.",\n'
            '  "code": "Código Python puro completo."\n'
            "}"
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system=sys_prompt,
            temperature=0.15,
            max_tokens=4096,
        )

        log.info("[coder] Construindo lógica via DeepSeek...")
        try:
            res = await invoke_with_fallback(
                role=CognitiveRole.DEEP,
                request=req,
                router=model_router,
                api_keys=api_keys,
            )
        except Exception as e:
            log.error(f"[coder] Falha na chamada ao LLM: {e}", exc_info=True)
            return f"❌ Falha na geração de código: {e}"

        # Parse do JSON retornado pelo LLM
        try:
            texto = res.text.strip()
            # Remove envelope markdown se o LLM insistir
            if texto.startswith("```json"):
                texto = texto.split("```json", 1)[1]
            if texto.startswith("```"):
                texto = texto[3:]
            if texto.endswith("```"):
                texto = texto[:-3]
            texto = texto.strip()

            payload = json.loads(texto)
            file_path = payload["file_path"]
            explicacao = payload["explicacao"]
            codigo = payload["code"]
        except Exception as e:
            log.error(f"[coder] Falha estrutural JSON. Texto retornado:\n{res.text}", exc_info=True)
            return f"❌ Falha ao interpretar a estrutura do LLM: {e}"

        # Pede aprovação humana via Telegram (Tier 1 = irreversível)
        log.info(f"[coder] Requisitando aprovação via AFK para: {file_path}")
        reason = f"Patch Dinâmico em: {file_path}\nExplicação: {explicacao}"

        p_res = await afk_protocol.request_permission(reason, 1, action_type="write")

        if p_res != PermissionResult.APPROVED:
            log.info(f"[coder] Escrita rejeitada. AFK retornou: {p_res.name}")
            return (
                f"🚫 Escrita de código rejeitada ou expirou "
                f"(AFK: {p_res.name}). Arquivo não modificado."
            )

        # Escrita autorizada
        log.info(f"[coder] Permissão concedida! Escrevendo {file_path} no disco.")
        full_path = os.path.join(os.getcwd(), os.path.normpath(file_path))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(codigo)

        return (
            f"✅ Código implementado e salvo com sucesso em '{file_path}'.\n"
            f"Se for uma skill nova, ela será carregada no próximo boot."
        )
