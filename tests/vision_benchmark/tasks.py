"""
Vision 2.0 Benchmark — Dataclasses e loaders de tasks.

Cada task consiste em:
- image_path: caminho para a screenshot rotulada
- category: OCR / GROUNDING / DESCRIPTION / AFK
- ground_truth: valor esperado (texto, bbox, palavras-chave, ou estado)
- prompt_override: opcional, permite customizar o prompt padrão da categoria
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

log = logging.getLogger("seeker.vision.benchmark.tasks")

DATASET_ROOT = Path(__file__).parent / "dataset"


class TaskCategory(Enum):
    """Categorias de tarefas do benchmark."""
    OCR = "ocr"                    # Extração de texto exato
    GROUNDING = "grounding"        # Localização de elemento UI (x, y)
    DESCRIPTION = "description"    # Descrição geral de cena
    AFK = "afk"                    # Detecção de estado (idle/active/modal/error)


@dataclass
class BenchmarkTask:
    """Uma task individual do benchmark."""
    task_id: str
    category: TaskCategory
    image_path: Path
    ground_truth: dict  # estrutura depende da categoria
    prompt_override: str | None = None
    metadata: dict = field(default_factory=dict)

    def load_image(self) -> bytes:
        """Carrega os bytes da imagem. Levanta FileNotFoundError se ausente."""
        if not self.image_path.exists():
            raise FileNotFoundError(f"Image not found: {self.image_path}")
        return self.image_path.read_bytes()

    def to_dict(self) -> dict:
        """Serializa para JSON-compatível."""
        return {
            "task_id": self.task_id,
            "category": self.category.value,
            "image_path": str(self.image_path),
            "ground_truth": self.ground_truth,
            "prompt_override": self.prompt_override,
            "metadata": self.metadata,
        }


def load_dataset(
    categories: list[TaskCategory] | None = None,
    dataset_root: Path = DATASET_ROOT,
    limit: int | None = None,
) -> list[BenchmarkTask]:
    """
    Carrega todas as tasks de um dataset.

    Args:
        categories: filtra por categorias. Se None, carrega todas.
        dataset_root: raiz do dataset (default: tests/vision_benchmark/dataset)
        limit: máximo de tasks por categoria (útil para smoke tests)

    Cada categoria deve ter uma pasta com:
        - imagens (.png, .jpg)
        - um labels.json mapeando nome_arquivo → ground_truth

    Returns:
        Lista de BenchmarkTask carregadas.
    """
    if categories is None:
        categories = list(TaskCategory)

    tasks: list[BenchmarkTask] = []

    for category in categories:
        cat_dir = dataset_root / category.value
        if not cat_dir.exists():
            log.warning(f"[benchmark] Categoria {category.value} não existe em {cat_dir}")
            continue

        labels_file = cat_dir / "labels.json"
        if not labels_file.exists():
            log.warning(f"[benchmark] labels.json não encontrado em {cat_dir}")
            continue

        try:
            with labels_file.open("r", encoding="utf-8") as f:
                labels = json.load(f)
        except json.JSONDecodeError as e:
            log.error(f"[benchmark] labels.json inválido em {cat_dir}: {e}")
            continue

        count = 0
        for img_name, gt in labels.items():
            img_path = cat_dir / img_name
            if not img_path.exists():
                log.warning(f"[benchmark] Imagem {img_name} ausente em {cat_dir}")
                continue

            prompt_override = None
            metadata = {}
            if isinstance(gt, dict):
                prompt_override = gt.pop("_prompt", None)
                metadata = gt.pop("_metadata", {})

            tasks.append(
                BenchmarkTask(
                    task_id=f"{category.value}/{img_name}",
                    category=category,
                    image_path=img_path,
                    ground_truth=gt if isinstance(gt, dict) else {"value": gt},
                    prompt_override=prompt_override,
                    metadata=metadata,
                )
            )
            count += 1
            if limit and count >= limit:
                break

        log.info(f"[benchmark] Carregadas {count} tasks de {category.value}")

    return tasks


def save_results(results: list[dict], output_path: Path):
    """Serializa resultados do benchmark em JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    log.info(f"[benchmark] Resultados salvos em {output_path}")


def load_results(input_path: Path) -> list[dict]:
    """Carrega resultados salvos previamente."""
    with input_path.open("r", encoding="utf-8") as f:
        return json.load(f)
