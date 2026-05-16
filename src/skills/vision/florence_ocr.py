"""
Seeker.Bot — Florence-2 OCR specialist arm
src/skills/vision/florence_ocr.py

Florence-2 (Microsoft, 230M ou 770M params) é um VLM *especializado em OCR
+ tasks visuais estruturadas* (DETECT, CAPTION, OCR_WITH_REGION). Em contraste
com Qwen3-VL 8B (generalista), Florence-2:

  - 10-20× mais rápido em OCR puro (~150-300ms vs ~3s)
  - Ocupa apenas ~500 MB de VRAM em fp16 (vs ~16 GB do Qwen3-VL)
  - Não compete com o slot principal do Ollama (carrega via HuggingFace direto)

Trade-off: Florence-2 NÃO faz raciocínio, NÃO segue instruções complexas.
Útil só para extrair texto bruto. Para análise rica, fica com Qwen3-VL/Gemini.

Comportamento de boot:
  - Lazy load: o modelo só é baixado/instanciado na primeira chamada a
    ocr_fast(). Boot do bot continua rápido.
  - Disable via env: FLORENCE_OCR_ENABLED=false força o caller a pular este
    arm e cair direto no fallback Qwen3-VL.
  - Auto-disable se transformers/torch faltar — sem crash.

Uso:
    from src.skills.vision.florence_ocr import get_florence_ocr
    text = await get_florence_ocr().extract_text(image_bytes)
"""

import asyncio
import io
import logging
import os
from typing import Optional

log = logging.getLogger("seeker.vision.florence")

# Dependência condicional — torch + transformers podem não estar instalados
# em todas as máquinas (CI, dev sem GPU). Não quebrar o import do módulo.
try:
    import torch  # noqa: F401 — availability probe
    from transformers import AutoModelForCausalLM, AutoProcessor  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError as e:
    log.warning(f"[florence] dependências ausentes ({e}) — OCR arm desabilitado")
    _DEPS_AVAILABLE = False

DEFAULT_MODEL_ID = os.getenv("FLORENCE_MODEL_ID", "microsoft/Florence-2-base")
DEFAULT_TASK = "<OCR>"  # "<OCR>" = texto puro; "<OCR_WITH_REGION>" = texto + bboxes


class FlorenceOCR:
    """
    Wrapper sync->async sobre Florence-2 para OCR rápido em prints.

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
        # device: cuda se disponível, senão CPU. Pode forçar via env FLORENCE_DEVICE.
        if device is None:
            device = os.getenv("FLORENCE_DEVICE")
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
        if os.getenv("FLORENCE_OCR_ENABLED", "true").lower() == "false":
            return False
        return True

    async def _ensure_loaded(self) -> bool:
        """Lazy load do modelo. Retorna True se ok, False se falhou."""
        if self.loaded:
            return True
        if not self.available:
            return False

        async with self._load_lock:
            if self.loaded:  # outro coroutine carregou enquanto esperávamos
                return True
            try:
                import torch as _t
                from transformers import AutoModelForCausalLM, AutoProcessor

                dtype = getattr(_t, self._dtype_name)
                log.info(
                    f"[florence] Carregando {self.model_id} em {self.device}/{self._dtype_name}..."
                )

                # Roda o load em thread — pode levar 10-30s na primeira vez (download)
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
                log.info(f"[florence] {self.model_id} pronto.")
                return True
            except Exception as e:
                log.warning(
                    f"[florence] falha ao carregar {self.model_id}: {e} — arm desabilitado"
                )
                # Não tenta de novo até reset manual; evita loop de download falhando
                return False

    async def extract_text(
        self,
        image_bytes: bytes,
        task: str = DEFAULT_TASK,
        max_new_tokens: int = 1024,
    ) -> Optional[str]:
        """
        OCR rápido sobre image_bytes. Retorna texto extraído (str) ou None
        se o modelo não puder ser usado (deps faltando, load falhou, etc.) —
        nesse caso o caller deve cair no fallback Qwen3-VL/Gemini.

        Args:
            image_bytes: bytes da imagem (PNG/JPG/etc)
            task: Florence-2 task token. Padrão "<OCR>" devolve só texto.
                  Use "<OCR_WITH_REGION>" para texto + bboxes (mais lento, fica em json).
            max_new_tokens: limite de tokens de saída. 1024 cobre prints normais.

        Returns:
            Texto extraído (string vazia se nenhum texto encontrado), ou None
            se este arm não estiver disponível.
        """
        if not await self._ensure_loaded():
            return None

        try:
            from PIL import Image
            import torch as _t
        except ImportError:
            log.warning("[florence] PIL/torch ausente em extract_text — pulando")
            return None

        # Converte bytes -> PIL Image em thread (PIL.open é I/O-bound mas blocking)
        def _decode():
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return img

        try:
            image = await asyncio.to_thread(_decode)
        except Exception as e:
            log.warning(f"[florence] falha decodificando imagem: {e}")
            return None

        dtype = getattr(_t, self._dtype_name)

        def _infer() -> str:
            inputs = self._processor(text=task, images=image, return_tensors="pt").to(
                self.device, dtype
            )
            with _t.inference_mode():
                generated_ids = self._model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=max_new_tokens,
                    # Greedy: num_beams=1 para evitar OOM com qualquer outro modelo
                    # já carregado na GPU. Florence-2 base + beam=3 já passou de
                    # 7GB pico em alguns prints densos.
                    num_beams=1,
                    do_sample=False,
                )
            raw = self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed = self._processor.post_process_generation(
                raw, task=task, image_size=(image.width, image.height)
            )
            # Para "<OCR>" o parsed é {"<OCR>": "texto..."}
            # Para "<OCR_WITH_REGION>" é {"<OCR_WITH_REGION>": {"quad_boxes": [...], "labels": [...]}}
            value = parsed.get(task, "")
            if isinstance(value, dict):
                # OCR_WITH_REGION: junta os labels
                return "\n".join(value.get("labels", []) or [])
            return str(value or "")

        # Inferência serializada — generate() não é thread-safe
        async with self._inference_lock:
            try:
                text = await asyncio.to_thread(_infer)
            except Exception as e:
                log.warning(f"[florence] inference falhou: {e}")
                return None

        log.debug(f"[florence] OCR ok: {len(text)} chars extraídos")
        return text

    async def unload(self) -> None:
        """Libera VRAM. Útil antes de tarefas que precisam do espaço."""
        if not self.loaded:
            return
        try:
            import torch as _t
            self._model = None
            self._processor = None
            if self.device == "cuda":
                _t.cuda.empty_cache()
            log.info("[florence] modelo descarregado, VRAM liberada")
        except ImportError:
            self._model = None
            self._processor = None


# ── Singleton ───────────────────────────────────────────────────────

_florence: Optional[FlorenceOCR] = None


def get_florence_ocr() -> FlorenceOCR:
    """Retorna a instância compartilhada do Florence-2 OCR arm."""
    global _florence
    if _florence is None:
        _florence = FlorenceOCR()
    return _florence
