import pytest
import os
import tempfile
from src.skills.kanban.kanban import KanbanBoard

def test_kanban_board_crud():
    pipeline_mock = MagicMock()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        board = KanbanBoard(pipeline_mock)
        board.file_path = os.path.join(temp_dir, "kanban_board.json")
        
        # 1. Lista quadro vazio
        res_list_empty = board.list_tasks()
        assert "vazio" in res_list_empty
        
        # 2. Adiciona tarefas
        res_add1 = board.add_task("Implementar testes unitários")
        assert "ID:" in res_add1
        
        res_add2 = board.add_task("Refatorar crawler")
        
        # Carrega tarefas e valida
        tasks = board._load_board()
        assert len(tasks) == 2
        task_id = tasks[0]["id"]
        
        # 3. Lista quadro preenchido
        res_list = board.list_tasks()
        assert "Implementar testes unitários" in res_list
        assert "Refatorar crawler" in res_list
        
        # 4. Move tarefa
        res_move = board.move_task(task_id, "in_progress")
        assert "in_progress" in res_move
        
        tasks_after_move = board._load_board()
        assert tasks_after_move[0]["column"] == "in_progress"

from unittest.mock import MagicMock
