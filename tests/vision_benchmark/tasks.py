"""Benchmark Task Definitions — Vision 2.0 Phase A2"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

class TaskType(Enum):
    """Tipos de tarefas no benchmark"""
    OCR = "ocr"
    GROUNDING = "grounding"
    DESCRIPTION = "description"
    AFK_DETECTION = "afk_detection"

@dataclass
class BenchmarkTask:
    """Uma tarefa individual de benchmark"""
    task_id: str
    task_type: TaskType
    image_path: str
    ground_truth: Dict[str, Any]  # JSON com resposta esperada
    
    # Metadata
    source: str  # ocrbench, screenspot-pro, afk-real, pt-br-custom
    category: Optional[str] = None
    language: str = "pt-BR"

class BenchmarkDataLoader:
    """Carregador de tasks do dataset local"""
    
    @staticmethod
    async def load_all_tasks(dataset_path: str = "tests/vision_benchmark/dataset") -> list:
        """Carrega todas as 150 tasks do dataset"""
        tasks = []
        # TODO: implement task loading from OCRBench, ScreenSpot-Pro, local PT-BR screenshots
        return tasks

    @staticmethod
    def load_from_jsonl(jsonl_path: str) -> list:
        """Carrega tasks de arquivo JSONL com ground truth"""
        tasks = []
        # TODO: implement JSONL parsing
        return tasks
