"""Um turno: o modelo fala, usa ferramenta, pede licença para comando, e para quando mandam parar."""

from __future__ import annotations

import threading
from datetime import datetime

from seeker.command_risk import decision, is_destructive
from seeker.providers import Cascade
from seeker.secrets import PLACEHOLDER, SecretGate, find_secrets, guess_name, hide_tokens, known_name, label_for, redact
from seeker.schedule import TZ, TaskBook
from seeker.skills.contract import Catalog
from seeker.store import Store
from seeker.tools import Files, Shell, ToolError
from seeker.transcript import TOOL_SPECS, Message, ToolCall

SYSTEM = """Você é Seeker, assistente pessoal de uma pessoa, no computador dela.
Fale português, curto e direto.

Você agenda, lembra preferências e usa o computador quando precisa.
Ao agendar, repita o horário do jeito que a ferramenta devolver.
Quando a pessoa corrigir um hábito seu ou disser uma preferência estável, use remember.
Não guarde senha, chave ou segredo na memória. Tarefa de um dia é agenda, não memória.
Quando a pessoa quiser guardar, trocar ou informar uma chave, token ou senha de API, chame request_secret com o nome. Não peça para colar o valor no chat. Não repita valor nenhum. O cartão é o único lugar da chave. Um sim no chat não grava a chave.
Para achar um arquivo no PC, use find_files e depois read_file no caminho. Você alcança a pasta do usuário, D: e E:. Arquivo .env fica de fora.
Não invente arquivo, agenda, fonte ou resultado de comando.
Em research e em last30days, cite só as fontes numeradas. Se a skill disser que não trouxe fonte, diga que não sabe.
last30days é o que as pessoas engajaram nos últimos 30 dias. research é um fato da web. Não misture os dois.
Leitura, pesquisa, agenda, memória, rotina, read_page, read_feed e read_mail seguem sem pedir licença.
E-mail: ler a caixa é livre. Rascunho, envio e exclusão esperam o sim e mostram destinatário, assunto e texto. Uma rotina não escreve, não envia e não apaga e-mail.
Comandos de consulta também: listar, ler, procurar, mover a pasta, git status, nvidia-smi. Chame run_command direto, sem perguntar se pode.
Para VRAM por programa, use gpu_memory. No Windows, nvidia-smi --query-compute-apps volta N/A. Não repita esse comando.
Se uma ferramenta voltar vazia, N/A ou sem permissão, tente outro caminho na mesma resposta. Não encerre só com "não tenho como" enquanto houver consulta para fazer.
Se ainda faltar uma ferramenta, chame create_skill com o módulo, o teste e o risco. A criação sempre espera o sim e mostra o código. Um sim anterior não grava sozinho. Não crie ferramenta pelo terminal e não use isso para mudar o próprio programa.
Não encerre dizendo que não tem ferramenta ou que não consegue. Se a ferramenta existe, chame. Se não existe, chame create_skill. Não crie skill para burlar CAPTCHA, login ou proteção de site.
Quando a pessoa mandar um link de vídeo ou pedir para guardar um tema, use knowledge_vault. O material fica em E:\\Ideias. Uma ficha curta, com tags, vai para o cérebro em cofre e para FICHA.md na pasta. Se já existir, use a pasta existente. Os insights saem só do trecho e dos arquivos devolvidos.
Peça licença no chat só antes de apagar, sobrescrever, formatar, encerrar processo, desligar o computador, ou git clean, git reset --hard e git push --force.
Se a pessoa já disse sim nesta mensagem, chame run_command. O sim dela basta. Não existe segundo botão.
Uma rotina roda sozinha no horário. Dentro dela, não use run_command nem submit_form.
submit_form e ferramentas MCP de escrita continuam alto risco: pare e peça autorização. Não gaste dinheiro e não altere o próprio programa.
Ofereça um próximo passo só quando ele for óbvio."""

VOICE = "A pessoa está falando, não lendo. Responda em uma ou duas frases, sem lista e sem markdown."

RETRY = (
    "Você encerrou sem usar ferramenta. Se a ferramenta existe, chame agora. "
    "Se não existe, chame create_skill com o módulo, o teste e o risco, para a pessoa autorizar. "
    "Não repita que não tem ferramenta. Não crie skill para burlar CAPTCHA, login ou proteção de site."
)

_GAVE_UP = (
    "não consigo",
    "nao consigo",
    "não tenho ferramenta",
    "nao tenho ferramenta",
    "não tenho uma ferramenta",
    "não tenho as ferramentas",
    "minhas ferramentas não",
    "minhas ferramentas nao",
    "nenhuma delas permite",
    "não tenho como",
    "nao tenho como",
    "não posso criar",
    "nao posso criar",
)


def gave_up(text: str) -> bool:
    folded = (text or "").casefold()
    return any(phrase in folded for phrase in _GAVE_UP)

LABELS = {
    "list_dir": "Listar pasta",
    "read_file": "Ler arquivo",
    "find_files": "Procurar arquivo",
    "read_page": "Ler página",
    "read_feed": "Ler feed",
    "last30days": "Últimos 30 dias",
    "read_mail": "Ler e-mail",
    "write_mail": "Rascunho",
    "send_mail": "Enviar e-mail",
    "delete_mail": "Apagar e-mail",
    "submit_form": "Enviar formulário",
    "configure_mcp": "Configurar MCP",
    "web_search": "Pesquisar",
    "research": "Pesquisar",
    "run_command": "Rodar comando",
    "gpu_memory": "Ver VRAM",
    "create_skill": "Criar ferramenta",
    "knowledge_vault": "Guardar no cofre",
    "request_secret": "Cofre seguro",
    "schedule_task": "Agendar",
    "create_routine": "Criar rotina",
    "list_routines": "Ver rotinas",
    "cancel_routine": "Cancelar rotina",
    "list_tasks": "Ver agenda",
    "complete_task": "Concluir tarefa",
    "cancel_task": "Cancelar tarefa",
    "snooze_task": "Adiar tarefa",
    "quiet_hours": "Silêncio",
    "remember": "Guardar",
    "forget": "Esquecer",
}


class TurnStopped(Exception):
    pass


class Control:
    def __init__(self):
        self._lock = threading.Lock()
        self.busy = False
        self._stopped = False

    def start(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
            self._stopped = False
            return True

    def cancel(self) -> None:
        with self._lock:
            self._stopped = True

    def finish(self) -> None:
        with self._lock:
            self.busy = False
            self._stopped = False

    def stopped(self) -> bool:
        with self._lock:
            return self._stopped


class Broker:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}

    def request(self, command: str) -> tuple[str, threading.Event]:
        import uuid

        approval_id = uuid.uuid4().hex
        event = threading.Event()
        with self._lock:
            self._pending[approval_id] = {"event": event, "allow": False, "command": command}
        return approval_id, event

    def wait(self, approval_id: str) -> bool:
        with self._lock:
            item = self._pending[approval_id]
        item["event"].wait()
        with self._lock:
            allow = bool(item["allow"])
            self._pending.pop(approval_id, None)
        return allow

    def resolve(self, approval_id: str, allow: bool) -> bool:
        with self._lock:
            item = self._pending.get(approval_id)
            if item is None or item["event"].is_set():
                return False
            item["allow"] = allow
            item["event"].set()
            return True

    def resolve_latest(self, allow: bool) -> bool:
        with self._lock:
            pending = [key for key, item in self._pending.items() if not item["event"].is_set()]
        if not pending:
            return False
        return self.resolve(pending[-1], allow)

    def cancel_all(self) -> None:
        with self._lock:
            items = list(self._pending.values())
        for item in items:
            item["allow"] = False
            item["event"].set()


class Agent:
    def __init__(
        self,
        store: Store,
        cascade: Cascade,
        files: Files,
        shell: Shell,
        search,
        tasks: TaskBook,
        broker: Broker,
        control: Control,
        max_steps: int = 8,
    ):
        self.store = store
        self.cascade = cascade
        self.files = files
        self.shell = shell
        self.search = search
        self.tasks = tasks
        self.broker = broker
        self.control = control
        self.max_steps = max_steps
        self.catalog = Catalog()
        self.brain = None
        self.routines = None
        self.routine_mode = False
        self.confirmed = False
        self.origin = "desktop"
        self.gate = SecretGate()
        self.key_status = None

    def run(self, chat_id: str, user_text: str, emit, voice: bool = False, origin: str = "desktop") -> None:
        self.origin = origin if origin in {"desktop", "telegram"} else "desktop"
        safe = redact(user_text)
        self.confirmed = decision(safe) is True
        self.store.add_message(chat_id, "user", safe)
        title = self.store.maybe_retitle(chat_id, safe)
        if title:
            emit({"type": "title", "title": title, "chat_id": chat_id})
        parts: list[str] = []
        try:
            if find_secrets(user_text) and safe == PLACEHOLDER:
                text, _status = self._secret_from_paste(user_text, emit)
                if text:
                    parts.append(text)
                    emit({"type": "token", "text": text})
            else:
                self._converse(chat_id, emit, voice, parts, allow_tools=True)
        except TurnStopped:
            self._save(chat_id, parts)
            emit({"type": "notice", "text": "Parei."})
        else:
            self._save(chat_id, parts)
        self._archive(safe, parts)
        emit({"type": "done"})

    def _converse(self, chat_id: str, emit, voice: bool, parts: list[str], allow_tools: bool) -> None:
        history = self.store.transcript(chat_id)
        for item in history:
            item.content = hide_tokens(item.content)
        messages = [Message("system", self._system(voice, chat_id)), *history]
        tried = False
        retried = False
        for _ in range(self.max_steps):
            self._check()
            specs = self._tool_specs() if allow_tools else None
            text, calls, failed = self._model(messages, specs, emit, parts)
            if failed:
                return
            if calls and allow_tools:
                tried = True
                messages.append(Message("assistant", text, calls))
                for call in calls:
                    self._check()
                    result = self._exec(chat_id, call, emit)
                    messages.append(Message("tool", result, tool_call_id=call.id, name=call.name))
                continue
            if allow_tools and not tried and not retried and gave_up(text):
                retried = True
                messages.append(Message("assistant", text))
                messages.append(Message("user", RETRY))
                continue
            return
        messages.append(Message("user", "Pare de usar ferramentas. Responda com o que já tem."))
        self._model(messages, None, emit, parts)

    def _model(self, messages, tools, emit, parts: list[str]) -> tuple[str, list[ToolCall], bool]:
        chunks: list[str] = []
        calls: list[ToolCall] = []
        for event in self.cascade.stream(messages, tools):
            self._check()
            kind = event["type"]
            if kind == "token":
                chunks.append(event["text"])
                emit(event)
            elif kind == "tool_calls":
                calls = event["calls"]
            elif kind == "notice":
                self._activity(emit, "notice", "Aviso", "info", event["text"])
                emit(event)
            elif kind == "error":
                emit(event)
                text = "".join(chunks).strip()
                if text:
                    parts.append(text)
                return text, [], True
        text = "".join(chunks).strip()
        if text:
            parts.append(text)
        return text, calls, False

    def _exec(self, chat_id: str, call: ToolCall, emit) -> str:
        if "_raw" in call.arguments and len(call.arguments) == 1:
            return "Não consegui ler os argumentos."
        label = LABELS.get(call.name, call.name)
        detail = _preview(call)
        event_id = self.store.add_event(chat_id, label, "running", detail)
        emit({"type": "activity", "id": event_id, "label": label, "status": "running", "detail": detail})
        try:
            if call.name == "request_secret":
                result, status = self._secret_call(call, emit)
            else:
                skill = self.catalog.get(call.name)
                if skill is not None and skill.needs_approval:
                    result, status = self._authorized(skill, call, emit, event_id)
                elif call.name == "run_command":
                    result, status = self._command(call, emit, event_id)
                else:
                    result = self._safe(call)
                    status = "done"
        except TurnStopped:
            self.store.update_event(event_id, "denied", "Parado.")
            emit({"type": "activity", "id": event_id, "label": label, "status": "denied", "detail": "Parado."})
            raise
        except ToolError as exc:
            result = str(exc)
            status = "error"
        result = hide_tokens(result)
        shown = result if len(result) <= 1200 else result[:1200] + "\n…"
        self.store.update_event(event_id, status, shown)
        emit({"type": "activity", "id": event_id, "label": label, "status": status, "detail": shown})
        return result

    def _authorized(self, skill, call: ToolCall, emit, event_id: str) -> tuple[str, str]:
        shown = _preview(call)
        if self.routine_mode:
            self.store.add_notice(f"Rotina pediu uma ação de alto risco e eu parei: {shown}")
            return "Alto risco. Não fiz. A pessoa precisa autorizar.", "denied"
        if self.confirmed and skill.name not in {"create_skill", "write_mail", "send_mail", "delete_mail"}:
            return self.catalog.run(skill.name, call.arguments), "done"
        approval_id, _event = self.broker.request(shown)
        emit({"type": "approval", "id": approval_id, "command": shown, "event_id": event_id})
        allow = self.broker.wait(approval_id)
        if self.control.stopped():
            raise TurnStopped()
        if not allow:
            return "Você recusou.", "denied"
        return self.catalog.run(skill.name, call.arguments), "done"

    def _command(self, call: ToolCall, emit, event_id: str) -> tuple[str, str]:
        command = str(call.arguments.get("command") or "").strip()
        if self.routine_mode:
            self.store.add_notice(f"Rotina pediu um comando e eu parei: {command}")
            return "Alto risco. Não rodei. A pessoa precisa autorizar.", "denied"
        if not is_destructive(command) or self.confirmed:
            return self.shell.run(command), "done"
        approval_id, _event = self.broker.request(command)
        emit({"type": "approval", "id": approval_id, "command": command, "event_id": event_id})
        allow = self.broker.wait(approval_id)
        if self.control.stopped():
            raise TurnStopped()
        if not allow:
            return "Você recusou o comando.", "denied"
        return self.shell.run(command), "done"

    def _secret_call(self, call: ToolCall, emit) -> tuple[str, str]:
        raw_name = str(call.arguments.get("name") or "")
        name = known_name(raw_name) or guess_name(raw_name)
        call.arguments = {"name": name} if name else {}
        if self.routine_mode:
            return "Uma rotina não guarda chave.", "denied"
        if not name:
            return "Diga qual chave: Gemini, Maritaca, NVIDIA, Groq, e-mail ou Telegram. Não cole o valor.", "error"
        return self._secret_wait(name, emit)

    def _secret_from_paste(self, user_text: str, emit) -> tuple[str, str]:
        if self.routine_mode:
            return "Uma rotina não guarda chave.", "denied"
        name = guess_name(user_text)
        if not name:
            emit({"type": "secret", "id": "", "name": "", "label": ""})
            return "A chave não entrou no chat. Escolha qual é no cofre e guarde lá.", "done"
        return self._secret_wait(name, emit)

    def _secret_wait(self, name: str, emit) -> tuple[str, str]:
        label = label_for(name)
        secret_id, event = self.gate.open(name)
        emit({"type": "secret", "id": secret_id, "name": name, "label": label})
        if self.origin != "desktop":
            return f"O cartão da chave {label} está aberto no computador. Não cole o valor aqui.", "done"
        if self.control.stopped():
            self.gate.finish(secret_id, "cancelled")
            raise TurnStopped()
        event.wait()
        if self.control.stopped():
            raise TurnStopped()
        status = self.gate.take(secret_id)
        if status == "saved":
            return f"A chave {label} foi guardada no cofre. O valor não está nesta conversa.", "done"
        return "A pessoa fechou o cartão sem guardar.", "denied"

    def _safe(self, call: ToolCall) -> str:
        args = call.arguments
        name = call.name
        if name == "list_dir":
            return self.files.list_dir(str(args.get("path") or ""))
        if name == "read_file":
            return self.files.read_file(str(args.get("path") or ""))
        if name == "find_files":
            return self.files.find_files(str(args.get("query") or ""), str(args.get("path") or ""))
        if name in {"web_search", "research"} and self.catalog.has("research"):
            return self.catalog.run("research", args)
        if name == "web_search":
            return self.search(str(args.get("query") or ""))
        if self.catalog.has(name):
            return self.catalog.run(name, args)
        if name == "schedule_task":
            return self.tasks.schedule(str(args.get("title") or ""), str(args.get("when_text") or ""))
        if name == "create_routine":
            if self.routines is None:
                return "Rotina indisponível."
            return self.routines.create(str(args.get("instruction") or ""), str(args.get("when_text") or ""))
        if name == "list_routines":
            if self.routines is None:
                return "Nenhuma rotina."
            return self.routines.list_active()
        if name == "cancel_routine":
            if self.routines is None:
                return "Não achei essa rotina."
            return self.routines.cancel(str(args.get("query") or ""))
        if name == "list_tasks":
            return self.tasks.list_pending()
        if name == "complete_task":
            return self.tasks.complete(str(args.get("query") or ""))
        if name == "cancel_task":
            return self.tasks.cancel(str(args.get("query") or ""))
        if name == "snooze_task":
            return self.tasks.snooze(str(args.get("query") or ""), int(args.get("minutes") or 10))
        if name == "quiet_hours":
            return self.tasks.quiet_hours(str(args.get("text") or ""))
        if name == "remember":
            return _remember(self.store, str(args.get("text") or ""), self.brain)
        if name == "forget":
            query = str(args.get("text") or "")
            count = self.store.forget_memory(query)
            if self.brain is not None:
                count += self.brain.forget(query)
            return "Apaguei." if count else "Não achei isso na memória."
        return "Ferramenta desconhecida."

    def _system(self, voice: bool, chat_id: str) -> str:
        lines = [item["text"] for item in self.store.memories()[-40:]]
        text = SYSTEM
        if lines:
            text += "\n\nO que você já aprendeu sobre esta pessoa:\n" + "\n".join(f"- {line}" for line in lines)
        recalled = self._recall(chat_id)
        if recalled:
            text += "\n\nDo cérebro, de conversas anteriores:\n" + "\n".join(f"- {item}" for item in recalled)
        if voice:
            text += "\n\n" + VOICE
        notes = self.catalog.notes()
        if notes:
            text += "\n\n" + notes
        if self.key_status is not None:
            lines = [f"- {label}: {'guardada' if ready else 'vazia'}" for label, ready in self.key_status()]
            text += "\n\nChaves no cofre, sem valores:\n" + "\n".join(lines)
        return text

    def _recall(self, chat_id: str) -> list[str]:
        if self.brain is None:
            return []
        users = [item["content"] for item in self.store.messages(chat_id) if item["role"] == "user"]
        if not users:
            return []
        return self.brain.search(users[-1])

    def _archive(self, user_text: str, parts: list[str]) -> None:
        if self.brain is None:
            return
        answer = "\n\n".join(part for part in parts if part).strip()
        if user_text.strip() and answer:
            self.brain.log_exchange(datetime.now(TZ), hide_tokens(user_text), hide_tokens(answer))

    def _tool_specs(self) -> list[dict]:
        covered = {item["name"] for item in self.catalog.specs()}
        base = [item for item in TOOL_SPECS if item["name"] not in covered and item["name"] != "web_search"]
        return base + self.catalog.specs()

    def _save(self, chat_id: str, parts: list[str]) -> None:
        content = hide_tokens("\n\n".join(part for part in parts if part).strip())
        if content:
            self.store.add_message(chat_id, "assistant", content)

    def _check(self) -> None:
        if self.control.stopped():
            raise TurnStopped()

    def _activity(self, emit, chat_hint: str, label: str, status: str, detail: str) -> None:
        del chat_hint
        emit({"type": "activity", "id": "", "label": label, "status": status, "detail": detail})


def _remember(store: Store, text: str, brain=None) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("senha", "chave", "token", "api_key", "secret")):
        return "Isso parece segredo. Não guardei."
    saved = store.add_memory(text)
    if saved is None:
        return "Isso já estava guardado." if text.strip() else "Nada para guardar."
    if brain is not None:
        brain.write_memory(saved["text"])
    return f"Vou lembrar: {saved['text']}"


def _preview(call: ToolCall) -> str:
    args = call.arguments
    if call.name == "request_secret":
        raw_name = str(args.get("name") or "")
        name = known_name(raw_name) or guess_name(raw_name)
        return f"Abrir o cofre para {label_for(name) or 'uma chave'}"
    if call.name == "knowledge_vault":
        scope = "lote de vídeos" if args.get("scope") == "lote" else "um item"
        return f"Guardar no cofre E:\\Ideias ({scope})\n{args.get('query', '')}".strip()
    if call.name == "create_skill":
        source = str(args.get("source") or "")
        test = str(args.get("test") or "")
        return (
            f"Criar a ferramenta {args.get('name', '')} ({args.get('risk', '')}).\n"
            f"{args.get('when', '')}\n\n{source}\n\nTeste:\n{test}"
        ).strip()
    if call.name == "configure_mcp":
        from seeker.mcp_hub import describe_server, parse_servers

        specs = parse_servers(args)
        if not specs:
            return "Conectar um servidor MCP"
        return "\n".join(describe_server(spec) for spec in specs)
    if call.name in {"write_mail", "send_mail"}:
        verb = "Enviar e-mail" if call.name == "send_mail" else "Salvar rascunho"
        return f"{verb} para {args.get('to', '')}\nAssunto: {args.get('subject', '')}\n\n{args.get('body', '')}".strip()
    if call.name == "delete_mail":
        return f"Apagar o e-mail {args.get('uid', '')}".strip()
    if call.name == "submit_form":
        fields = args.get("fields") or {}
        pairs = ", ".join(f"{key}={value}" for key, value in fields.items()) if isinstance(fields, dict) else ""
        return f"Enviar formulário para {args.get('url', '')}\n{pairs}".strip()
    for key in ("command", "path", "query", "title", "when_text", "text", "url"):
        if args.get(key):
            return str(args[key])
    if call.name == "schedule_task":
        return f"{args.get('title', '')} — {args.get('when_text', '')}".strip(" —")
    return call.name
