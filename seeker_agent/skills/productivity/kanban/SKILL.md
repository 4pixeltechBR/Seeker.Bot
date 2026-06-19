---
name: kanban
description: "Local Markdown-backed Kanban Board for task management."
version: 1.0.0
author: Seeker.Bot + Seeker Agent
license: MIT
platforms: [windows, linux, macos]
prerequisites:
  commands: [python]
metadata:
  seeker_agent:
    tags: [kanban, tasks, productivity, management, markdown]
---

# Kanban — Local Task Management Board

This skill enables the agent to manage project tasks locally using a Markdown-based Kanban board. It supports adding tasks, moving tasks between stages (Backlog, Todo, In Progress, Done), and listing all active tasks in a structured Markdown outline.

The board data is stored in `E:/Seeker.Bot/data/kanban_board.json`.

---

## Command Reference

All actions are executed using the Seeker CLI:

```powershell
# Windows
& "E:\Seeker.Bot\.venv\Scripts\python.exe" "E:\Seeker.Bot\scripts\seeker_cli.py" kanban <action> [arguments]

# Linux/macOS
E:/Seeker.Bot/.venv/bin/python E:/Seeker.Bot/scripts/seeker_cli.py kanban <action> [arguments]
```

### Actions:

#### 1. Add Task
Adds a new task to the **Backlog** column.
```bash
seeker_cli kanban add "Task Title or Description"
```
*Output:* Returns the task ID (e.g. `T-5-ABCD`).

#### 2. Move Task
Moves an existing task to another column.
```bash
seeker_cli kanban move <task_id> <column>
```
*Columns:* `backlog`, `todo`, `in_progress`, `done`

#### 3. List Board
Prints the entire Kanban board with tasks organized by stage.
```bash
seeker_cli kanban list
```

---

## Agent Usage Guidelines

Use this board to:
- Organize your planned implementation changes.
- Track completed features.
- Surface active TODOs in the session.
