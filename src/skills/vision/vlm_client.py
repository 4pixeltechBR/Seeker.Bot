import asyncio
import base64
import json
import os
import httpx
import logging

log = logging.getLogger("seeker.vision.vlm")

# Import fallback Gemini (Sprint 12 Phase A4)
try:
    from .vlm_cloud_fallback import GeminiVLMFallback, create_gemini_vlm_fallback
except ImportError:
    GeminiVLMFallback = None
    create_gemini_vlm_fallback = None

# Default model usado quando nenhum VLM_MODEL é definido via env.
# Alternativas testadas no Sprint 12 (Vision 2.0):
#   - qwen3.5:4b        (baseline, 4 GB VRAM)
#   - qwen2.5vl:7b      (Qwen2.5-VL 7B, ~7 GB VRAM, melhor OCR)
#   - qwen3-vl:8b       (Qwen3-VL 8B, ~9 GB VRAM, SOTA geral)
#   - minicpm-v         (MiniCPM-V 2.6, ~6 GB VRAM, OCR specialist)
DEFAULT_VLM_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class VLMClient:
    """
    Cliente multimodal VLM via Ollama.

    Suporta múltiplos modelos configuráveis via env var VLM_MODEL:
    - qwen3.5:4b (default)
    - qwen2.5vl:7b
    - qwen3-vl:8b
    - minicpm-v
    - qualquer modelo multimodal do Ollama

    v3 (Sprint 12 — Vision 2.0):
    - Modelo configurável via env var (VLM_MODEL)
    - Hot-swap via set_model() sem reinstanciar
    - Integração com semáforo de GPU (VRAM compartilhada com skills locais)
    - keep_alive dinâmico: 5m quando GPU livre, 0 quando ocupada
    - Fallback CPU (num_gpu=0) quando VRAM indisponível
    - Parsing centralizado de bounding boxes
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        gpu_semaphore: asyncio.Semaphore | None = None,
    ):
        # Config via env com fallback para defaults
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        self.model = model or os.getenv("VLM_MODEL", DEFAULT_VLM_MODEL)
        self.generate_endpoint = f"{self.base_url}/api/generate"

        log.info(f"[vlm] Inicializando VLMClient: model={self.model} base_url={self.base_url}")

        # Semáforo compartilhado de GPU com outras skills
        # Se None, assume GPU sempre disponível (standalone mode)
        self._gpu_semaphore = gpu_semaphore

        # Connection pool persistente — reutiliza TCP entre requests
        self._client = httpx.AsyncClient(
            timeout=300.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

        # Cache de health check (evita re-check a cada chamada)
        self._health_cache: tuple[bool, float] = (False, 0.0)
        self._health_cache_ttl = 60.0  # segundos

        # Lock de inferência: evita sobreposição de chamadas multimodais para o Ollama
        self._inference_lock = asyncio.Lock()

        # Cloud fallback (Gemini 2.5 Flash) — Sprint 12 Phase A4
        self._gemini_fallback = None
        if os.getenv("GEMINI_VLM_FALLBACK", "false").lower() == "true":
            if create_gemini_vlm_fallback:
                self._gemini_fallback = create_gemini_vlm_fallback()
                if self._gemini_fallback and self._gemini_fallback.enabled:
                    log.info("[vlm] Gemini 2.5 Flash fallback ATIVADO")

    def _is_gpu_available(self) -> bool:
        """Checa se o semáforo de GPU está livre sem bloquear."""
        if self._gpu_semaphore is None:
            return True
        # Tenta adquirir sem esperar — se conseguir, libera e retorna True
        if self._gpu_semaphore.locked():
            return False
        return True

    async def _call_with_fallback(
        self,
        ollama_coro,
        gemini_method_name: str,
        image_bytes: bytes = None,
        description: str = None,
    ) -> str:
        """
        Executa Ollama com fallback para Gemini se falhar.

        Args:
            ollama_coro: Coroutine do Ollama a executar
            gemini_method_name: Nome do método do Gemini a chamar como fallback
            image_bytes: Bytes da imagem (para Gemini)
            description: Descrição do elemento (para locate_element Gemini)

        Returns:
            Resultado do Ollama ou Gemini
        """
        try:
            # Tenta Ollama primeiro
            return await ollama_coro
        except (TimeoutError, httpx.TimeoutException, httpx.ReadTimeout, asyncio.TimeoutError) as e:
            log.warning(f"[vlm] Ollama timeout ({self.model}), usando Gemini fallback...")

            # Fallback para Gemini
            if not self._gemini_fallback or not self._gemini_fallback.enabled:
                log.error("[vlm] Gemini fallback nao disponivel, re-raising error")
                raise

            # Chama método correspondente em Gemini
            gemini_method = getattr(self._gemini_fallback, gemini_method_name, None)
            if not gemini_method:
                raise ValueError(f"Metodo '{gemini_method_name}' nao encontrado em GeminiVLMFallback")

            # Audit log
            log.info(f"[vlm] Fallback para Gemini: {gemini_method_name}")

            # Chama com os devidos argumentos
            if gemini_method_name == "locate_element":
                return await gemini_method(image_bytes, description)
            else:
                return await gemini_method(image_bytes)
        except Exception as e:
            log.error(f"[vlm] Erro em Ollama: {e}", exc_info=True)
            raise

    async def analyze_screenshot(
        self,
        image_bytes: bytes,
        prompt: str,
        force_cpu: bool = False,
    ) -> str:
        """
        Envia screenshot + prompt para o VLM.
        
        Roteamento de hardware:
        - GPU livre → roda na VRAM, keep_alive=5m (sessão fluida)
        - GPU ocupada → roda na CPU/RAM, keep_alive=0 (libera imediato)
        - force_cpu=True → força CPU independente do semáforo
        """
        gpu_available = (not force_cpu) and self._is_gpu_available()
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "keep_alive": "5m" if gpu_available else "0",
            "options": {
                "temperature": 0.1,  # Frio — OCR e coordenadas precisas
            },
        }

        # Se GPU indisponível, força offload pra CPU
        if not gpu_available:
            payload["options"]["num_gpu"] = 0
            log.info(
                f"[vlm] GPU ocupada (semáforo ativo) → rodando na CPU/RAM. "
                f"Latência estimada: 10-20s"
            )
        else:
            log.info(f"[vlm] GPU livre → VRAM, keep_alive=5m")

        try:
            async with self._inference_lock:
                res = await self._client.post(self.generate_endpoint, json=payload)
                res.raise_for_status()
                data = res.json()

                response_text = data.get("response", "").strip()

                # Log de performance
                eval_duration = data.get("eval_duration", 0)
                total_duration = data.get("total_duration", 0)
                if total_duration > 0:
                    log.info(
                        f"[vlm] Inference: {total_duration / 1e9:.1f}s total, "
                        f"{eval_duration / 1e9:.1f}s eval | "
                        f"{'GPU' if gpu_available else 'CPU'}"
                    )

                return response_text
        except httpx.TimeoutException:
            mode = "GPU" if gpu_available else "CPU"
            log.error(f"[vlm] Timeout ({mode} mode) — modelo pode estar carregando", exc_info=True)
            raise
        except Exception as e:
            log.error(f"[vlm] Falha ao analisar screenshot: {e}", exc_info=True)
            raise

    async def extract_text_from_image(self, image_bytes: bytes) -> str:
        """OCR puro via VLM."""
        prompt = (
            "Extract all the text from this image exactly as written. "
            "Preserve the original language. Do not add explanatory text."
        )
        return await self.analyze_screenshot(image_bytes, prompt)

    async def locate_element(
        self, image_bytes: bytes, description: str
    ) -> dict:
        """
        Pede ao VLM para localizar um elemento e retornar coordenadas.
        Usa fallback Gemini se Ollama falha (timeout grounding).
        Retorna dict com x, y (centro do elemento) e confidence.
        """
        prompt = (
            f"Find the UI element: '{description}'. "
            f"Return ONLY a JSON object with the center coordinates: "
            f'{{"x": <center_x_pixels>, "y": <center_y_pixels>, "confidence": <0.0-1.0>}}'
        )

        # Com fallback para Gemini
        raw_text = await self._call_with_fallback(
            self.analyze_screenshot(image_bytes, prompt),
            "locate_element",
            image_bytes=image_bytes,
            description=description,
        )
        log.info(f"[vlm] locate_element raw: {raw_text}")

        return _parse_bbox_response(raw_text)

    async def describe_page(self, image_bytes: bytes) -> str:
        """Descrição estruturada da página para decisão do agente."""
        prompt = (
            "Describe this webpage screenshot in Portuguese (PT-BR). "
            "List: 1) Page title/header 2) Main content summary "
            "3) Clickable buttons or links visible 4) Any forms or input fields. "
            "Be concise and factual."
        )
        return await self.analyze_screenshot(image_bytes, prompt)

    async def unload_model(self, model_name: str | None = None):
        """
        Força descarregamento de um modelo da VRAM (libera para outras skills).

        Args:
            model_name: nome do modelo a descarregar. Se None, usa self.model.
        """
        target = model_name or self.model
        try:
            payload = {
                "model": target,
                "keep_alive": "0",
            }
            await self._client.post(self.generate_endpoint, json=payload)
            log.info(f"[vlm] Modelo {target} descarregado da VRAM.")
        except Exception as e:
            log.warning(f"[vlm] Falha ao descarregar modelo {target}: {e}")

    async def set_model(self, new_model: str):
        """
        Hot-swap do modelo VLM sem reinstanciar o cliente.

        1. Descarrega o modelo atual da VRAM
        2. Atualiza self.model
        3. Invalida cache de health_check

        Útil para benchmarks comparativos (Sprint 12) e fallback dinâmico.
        """
        if new_model == self.model:
            log.info(f"[vlm] set_model: modelo já é {new_model}, no-op")
            return

        old_model = self.model
        # Serializa troca com o inference_lock para não colidir com chamadas em voo
        async with self._inference_lock:
            log.info(f"[vlm] set_model: trocando {old_model} → {new_model}")
            # Descarrega o anterior
            await self.unload_model(old_model)
            self.model = new_model
            # Invalida cache de health (modelo diferente pode não estar disponível)
            self._health_cache = (False, 0.0)
        log.info(f"[vlm] set_model: troca completa, modelo ativo: {self.model}")

    async def health_check(self) -> bool:
        """Verifica se o Ollama está rodando. Resultado cacheado por 60s."""
        import time as _time
        now = _time.monotonic()
        cached_result, cached_at = self._health_cache
        if (now - cached_at) < self._health_cache_ttl:
            return cached_result

        try:
            res = await self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            res.raise_for_status()
            models = res.json().get("models", [])
            available = any(m.get("name", "").startswith(self.model.split(":")[0]) for m in models)
            if not available:
                log.warning(
                    f"[vlm] Modelo {self.model} não encontrado no Ollama. "
                    f"Disponíveis: {[m['name'] for m in models]}"
                )
            self._health_cache = (available, now)
            return available
        except Exception as e:
            log.error(f"[vlm] Ollama indisponível: {e}", exc_info=True)
            self._health_cache = (False, now)
            return False

    async def close(self):
        """Fecha o client HTTP persistente."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Helpers ───────────────────────────────────────────────

def _parse_bbox_response(raw_text: str) -> dict:
    """Parse centralizado de respostas de localização do VLM."""
    # Tenta JSON direto
    try:
        clean = raw_text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        parsed = json.loads(clean)
        # Valida campos mínimos
        if "x" in parsed and "y" in parsed:
            parsed.setdefault("confidence", 0.5)
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: retorna raw com confidence 0
    log.warning(f"[vlm] Parsing de bbox falhou, retornando raw")
    return {"raw_bbox": raw_text, "x": 0, "y": 0, "confidence": 0.0}
