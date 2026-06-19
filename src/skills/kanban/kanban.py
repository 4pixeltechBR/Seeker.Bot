import os
import json
import logging
import uuid
import time

log = logging.getLogger("seeker.kanban")

class KanbanBoard:
    """Quadro Kanban local para gerenciamento e rastreamento de tarefas do Seeker.Bot."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "data",
            "kanban_board.json"
        )
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load_board(self) -> list[dict]:
        if not os.path.exists(self.file_path):
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"[kanban] Falha ao carregar kanban board: {e}")
            return []

    def _save_board(self, tasks: list[dict]) -> None:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[kanban] Falha ao salvar kanban board: {e}")

    def add_task(self, title: str) -> str:
        """Adiciona uma nova tarefa à coluna Backlog."""
        if not title or not title.strip():
            return "❌ Título da tarefa é obrigatório."

        tasks = self._load_board()
        task_id = f"T-{len(tasks) + 1}-{uuid.uuid4().hex[:4].upper()}"
        new_task = {
            "id": task_id,
            "title": title.strip(),
            "column": "backlog",
            "created_at": time.time(),
        }
        tasks.append(new_task)
        self._save_board(tasks)
        log.info(f"[kanban] Tarefa '{title}' criada com sucesso ID={task_id}")
        return f"✅ Tarefa criada com sucesso no Backlog. ID: `{task_id}`"

    def move_task(self, task_id: str, target_column: str) -> str:
        """Move uma tarefa para uma nova coluna (backlog, todo, in_progress, done)."""
        target_column = target_column.lower().strip().replace(" ", "_")
        valid_columns = {"backlog", "todo", "in_progress", "done"}
        if target_column not in valid_columns:
            return f"❌ Coluna destino inválida. Use uma das seguintes: {', '.join(valid_columns)}"

        tasks = self._load_board()
        for task in tasks:
            if task["id"].upper() == task_id.upper():
                old_col = task["column"]
                task["column"] = target_column
                self._save_board(tasks)
                log.info(f"[kanban] Tarefa {task_id} movida de '{old_col}' para '{target_column}'")
                return f"✅ Tarefa `{task_id}` movida de `{old_col}` para `{target_column}`."

        return f"❌ Nenhuma tarefa encontrada com o ID: `{task_id}`"

    def list_tasks(self) -> str:
        """Retorna as tarefas formatadas em formato Markdown."""
        tasks = self._load_board()
        if not tasks:
            return "🗂️ O quadro Kanban local está vazio."

        columns = {
            "backlog": [],
            "todo": [],
            "in_progress": [],
            "done": []
        }

        for task in tasks:
            col = task.get("column", "backlog")
            if col in columns:
                columns[col].append(task)
            else:
                columns["backlog"].append(task)

        output = ["### 🗂️ QUADRO KANBAN LOCAL"]
        for col_name, col_tasks in columns.items():
            col_title = col_name.upper().replace("_", " ")
            output.append(f"\n📌 **{col_title}** ({len(col_tasks)}):")
            if not col_tasks:
                output.append("  *(Nenhuma tarefa)*")
            else:
                for t in col_tasks:
                    output.append(f"  - `[{t['id']}]` {t['title']}")

        return "\n".join(output)
