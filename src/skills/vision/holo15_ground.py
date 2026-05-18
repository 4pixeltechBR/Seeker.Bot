"""
Seeker.Bot — Holo1.5-3B GUI grounding arm
src/skills/vision/holo15_ground.py

Holo1.5-3B (HCompany, ~3B params) é um VLM *especializado em localizar
elementos de UI em screenshots*. Em contraste com VLMs generalistas
(Qwen3.5, MiniCPM, etc.), Holo1.5:

  - Foi treinado especificamente para retornar coordenadas (x, y) de
    botões, campos de texto, links, ícones — a partir de uma descrição
    em linguagem natural ("clique no botão 'Enviar'").
  - 92.2% no benchmark Surfer-H de tarefas web (lidera open-source).
  - Ocupa ~2-3 GB de VRAM em fp16, cabe junto com Florence-2 e Ollama.

Trade-off: Holo NÃO faz OCR genérico, NÃO descreve cena. Use ele para
o problema específico de "onde está o elemento X nesta tela". Para texto,
fica com Florence-2. Para análise rica, fica com o VLM Ollama.

Comportamento de boot:
  - Lazy load: o modelo só é baixado/instanciado na primeira chamada a
    locate_element(). Boot do bot continua rápido.
  - Disable via env: HOLO15_ENABLED=false força o caller a pular este
    arm e cair direto no fallback VLM Ollama.
  - Auto-disable se transformers/torch faltar — sem crash.

Uso:
    from src.skills.vision.holo15_ground import get_holo15_grounder
    coords = await get_holo15_grounder().locate(image_bytes, "botão de login")
"""

import asyncio
import io
import logging
import os
import re
from typing import Optional

log = logging.getLogger("seeker.vision.holo15")

# Dependência condicional — torch + transformers podem não estar instalados
# em todas as máquinas (CI, dev sem GPU). Não quebrar o import do módulo.
try:
    import torch  # noqa: F401 — availability probe
    from transformers import AutoModelForCausalLM, AutoProcessor  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError as e:
    log.warning(f"[holo15] dependências ausentes ({e}) — grounder desabilitado")
    _DEPS_AVAILABLE = False

DEFAULT_MODEL_ID = os.getenv("HOLO15_MODEL_ID", "Hcompany/Holo1.5-3B")


class Holo15Grounder:
    """
    Wrapper sync->async sobre Holo1.5 para localização de elementos de UI.

    Carrega o modelo na primeira chamada. Subsequentes reusam o singleton.
    Inferência roda em thread separada (asyncio.to_thread) para não bloquear
    o event loop — torch.generate é CPU/GPU sync.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: Optional[str] = None,
        dtype: Optional[str] = None,
    ):
        self.model_id = model_id
        if device is None:
            device = os.getenv("HOLO15_DEVICE")
        if device is None and _DEPS_AVAILABLE:
            import torch as _t
            device = "cuda" if _t.cuda.is_available() else "cpu"
        self.device = device or "cpu"
        # fp16 só faz sentido em CUDA; em CPU o fp16 fica mais lento que fp32
        self._dtype_name = dtype or ("float16" if self.device == "cuda" else "float32")

        self._model = None
        self._processor = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()  # serializa generate() — não thread-safe

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    @property
    def available(self) -> bool:
        """True se a infra (deps + opt-in) permite usar este arm."""
        if not _DEPS_AVAILABLE:
            return False
        if os.getenv("HOLO15_ENABLED", "true").lower() == "false":
            return False
        return True

    async def _ensure_loaded(self) -> bool:
        """Lazy load do modelo. Retorna True se ok, False se falhou."""
        if self.loaded:
            return True
        if not self.available:
            return False

        async with self._load_lock:
            if self.loaded:
                return True
            try:
                import torch as _t
                from transformers import AutoModelForCausalLM, AutoProcessor

                dtype = getattr(_t, self._dtype_name)
                log.info(
                    f"[holo15] Carregando {self.model_id} em {self.device}/{self._dtype_name}..."
                )

                # Roda o load em thread — pode levar 30-60s na primeira vez (~6GB download)
                def _load():
                    proc = AutoProcessor.from_pretrained(
                        self.model_id, trust_remote_code=True
                    )
                    mdl = AutoModelForCausalLM.from_pretrained(
                        self.model_id,
                        trust_remote_code=True,
                        torch_dtype=dtype,
                    ).to(self.device)
                    mdl.eval()
                    return mdl, proc

                self._model, self._processor = await asyncio.to_thread(_load)
                log.info(f"[holo15] {self.model_id} pronto.")
                return True
            except Exception as e:
                log.warning(
                    f"[holo15] falha ao carregar {self.model_id}: {e} — arm desabilitado"
                )
                return False

    async def locate(
        self,
        image_bytes: bytes,
        target_description: str,
        max_new_tokens: int = 128,
    ) -> Optional[tuple[int, int]]:
        """
        Localiza um elemento de UI descrito por target_description na imagem.

        Retorna (x, y) absolutos em pixels, ou None se o modelo não puder
        ser usado (deps faltando, load falhou, etc.) — nesse caso o caller
        deve cair no fallback VLM Ollama.

        Args:
            image_bytes: bytes do screenshot (PNG/JPG/etc)
            target_description: descrição NL do elemento ("botão Enviar")
            max_new_tokens: limite de tokens de saída. 128 cobre coords.

        Returns:
            (x, y) em pixels absolutos, ou None se indisponível/não encontrou.
        """
        if not await self._ensure_loaded():
            return None

        try:
            from PIL import Image
            import torch as _t
        except ImportError:
            log.warning("[holo15] PIL/torch ausente em locate — pulando")
            return None

        def _decode():
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")

        try:
            image = await asyncio.to_thread(_decode)
        except Exception as e:
            log.warning(f"[holo15] falha decodificando imagem: {e}")
            return None

        dtype = getattr(_t, self._dtype_name)

        # Holo1.5 espera prompt no estilo "Click on <description>"
        prompt = f"Click on {target_description}"

        def _infer() -> Optional[tuple[int, int]]:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._processor(
                text=[text],
                images=[image],
                return_tensors="pt",
            ).to(self.device, dtype)

            with _t.inference_mode():
                generated_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    num_beams=1,
                )
            generated = generated_ids[:, inputs["input_ids"].shape[1]:]
            output = self._processor.batch_decode(
                generated, skip_special_tokens=True
            )[0]

            # Holo1.5 retorna algo como "Click(x=512, y=384)" ou "(512, 384)"
            # Extrai dois números inteiros consecutivos.
            m = re.search(r"x\s*=\s*(\d+)\s*[,\s]+y\s*=\s*(\d+)", output, re.IGNORECASE)
            if not m:
                m = re.search(r"\((\d+)\s*,\s*(\d+)\)", output)
            if not m:
                # último recurso — primeiros 2 ints
                nums = re.findall(r"\d+", output)
                if len(nums) >= 2:
                    return (int(nums[0]), int(nums[1]))
                return None
            return (int(m.group(1)), int(m.group(2)))

        try:
            async with self._inference_lock:
                coords = await asyncio.to_thread(_infer)
            if coords:
                log.debug(f"[holo15] {target_description!r} → {coords}")
            else:
                log.info(f"[holo15] não localizou: {target_description!r}")
            return coords
        except Exception as e:
            log.warning(f"[holo15] falha em locate({target_description!r}): {e}")
            return None


# Singleton compartilhado
_grounder: Holo15Grounder | None = None


def get_holo15_grounder() -> Holo15Grounder:
    """Retorna instância compartilhada do Holo15Grounder."""
    global _grounder
    if _grounder is None:
        _grounder = Holo15Grounder()
    return _grounder
