from datetime import datetime

from seeker.agent import Agent, Broker, Control
from seeker.providers import Cascade
from seeker.routine import RoutineBook
from seeker.schedule import TZ, Scheduler, TaskBook
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=TZ)


def test_cria_rotina_diaria_e_avanca(tmp_path):
    book = RoutineBook(Store(tmp_path / "s.db"), clock=lambda: NOW)
    text = book.create("pesquise o clima e me diga", "todo dia útil às 8h")
    assert "Rotina" in text
    assert "08:00" in text
    due = datetime.fromisoformat(book.store.active_routines()[0]["due_at"])
    assert due == datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
    later = datetime(2026, 10, 1, 8, 1, tzinfo=TZ)
    ready = book.due(later)
    assert len(ready) == 1
    book.mark_ran(ready[0], later)
    nxt = datetime.fromisoformat(book.store.active_routines()[0]["due_at"])
    assert nxt == datetime(2026, 10, 2, 8, 0, tzinfo=TZ)


def test_rotina_nao_roda_comando(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()

    class Spy:
        def __init__(self):
            self.commands = []

        def run(self, command):
            self.commands.append(command)
            return "ok"

        def stop(self):
            pass

    class Scripted:
        name = "Teste"

        def __init__(self):
            self.steps = [
                [{"type": "tool_calls", "calls": [ToolCall("1", "run_command", {"command": "Remove-Item x"})]}],
                [{"type": "token", "text": "parei"}],
            ]

        def available(self):
            return True

        def stream(self, messages, tools):
            yield from self.steps.pop(0)

    shell = Spy()
    agent = Agent(store, Cascade([Scripted()]), Files((root,), 1000), shell, lambda query: "", TaskBook(store), Broker(), Control())
    agent.routine_mode = True
    agent.run(chat["id"], "apague tudo", lambda event: None)
    assert shell.commands == []
    assert any("parei" in notice["text"] or "comando" in notice["text"] for notice in store.unseen_notices())


def test_agenda_dispara_a_rotina_uma_vez(tmp_path):
    store = Store(tmp_path / "s.db")
    book = RoutineBook(store, clock=lambda: NOW)
    book.create("pesquise o clima e me diga", "todo dia útil às 8h")
    ran = []
    when = datetime(2026, 10, 1, 8, 5, tzinfo=TZ)
    scheduler = Scheduler(store, lambda text: None, clock=lambda: when)
    scheduler.on_routine = lambda routine: ran.append(routine["instruction"])
    scheduler.tick()
    scheduler.tick()
    assert ran == ["pesquise o clima e me diga"]
    assert datetime.fromisoformat(store.active_routines()[0]["due_at"]) == datetime(2026, 10, 2, 8, 0, tzinfo=TZ)
