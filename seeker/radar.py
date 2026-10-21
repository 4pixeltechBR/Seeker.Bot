"""Radar das 8h30. Um cartão por decisão. Sem decisão, fica quieto."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from seeker.agenda import within
from seeker.whatsapp import is_group
from seeker.schedule import TZ, TaskBook
from seeker.store import Store

SOURCES = ("tarefa", "disco", "email", "agenda", "whatsapp")
ACTIONS = {
    "tarefa": ("concluir", "arquivar"),
    "disco": ("arquivar",),
    "email": ("rascunho", "arquivar"),
    "whatsapp": ("rascunho", "arquivar"),
}
HINTS = {
    frozenset({"concluir", "arquivar"}): "Concluir ou arquivar.",
    frozenset({"rascunho", "arquivar"}): "Rascunho ou arquivar.",
    frozenset({"remarcar", "arquivar"}): "Remarcar ou arquivar.",
    frozenset({"concluir", "remarcar", "arquivar"}): "Concluir, remarcar ou arquivar.",
    frozenset({"arquivar"}): "Arquivar.",
}
LABELS = {
    "tarefa": "Tarefa",
    "disco": "Disco",
    "email": "E-mail",
    "agenda": "Agenda",
    "whatsapp": "WhatsApp",
}
BUTTONS = {
    "concluir": "Concluir",
    "arquivar": "Arquivar",
    "rascunho": "Rascunho",
    "remarcar": "Remarcar",
}
CODES = {"c": "concluir", "a": "arquivar", "r": "rascunho", "m": "remarcar", "y": "sim", "n": "nao"}


@dataclass(frozen=True)
class RadarCard:
    id: str
    source: str
    line: str
    actions: tuple[str, ...]
    ref: str

    def public(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "line": format_line(self),
            "actions": list(self.actions),
        }


def radar_text(
    store: Store,
    brain,
    now: datetime,
    disks: list[str] | None = None,
    mail: list[dict] | str = "",
    events: list[dict] | None = None,
    whatsapp: list[dict] | None = None,
    sources: tuple[str, ...] = SOURCES,
) -> str:
    return format_radar(radar_cards(store, brain, now, disks=disks, mail=mail, events=events, whatsapp=whatsapp, sources=sources))


def radar_cards(
    store: Store,
    brain,
    now: datetime,
    disks: list[str] | None = None,
    mail: list[dict] | str = "",
    events: list[dict] | None = None,
    whatsapp: list[dict] | None = None,
    sources: tuple[str, ...] = SOURCES,
) -> list[RadarCard]:
    """A lição de ontem fica no cofre. brain existe para o chamador antigo."""
    del brain
    now = now.astimezone(TZ)
    chosen = set(sources)
    hidden = _hidden(store, now)
    cards: list[RadarCard] = []
    agenda_refs: set[str] = set()
    if "agenda" in chosen:
        cards.extend(_agenda(store, now, events or [], hidden, agenda_refs))
    if "whatsapp" in chosen:
        cards.extend(_people(whatsapp or [], "whatsapp", hidden))
    if "email" in chosen:
        cards.extend(_people(_mail_items(mail), "email", hidden))
    if "tarefa" in chosen:
        cards.extend(_tasks(store, now, hidden, agenda_refs))
    if "disco" in chosen:
        cards.extend(_disk(disks or [], hidden))
    return [card for card in cards if card.id not in hidden][:8]


def format_radar(cards: list[RadarCard]) -> str:
    if not cards:
        return ""
    return "Radar\n\n" + "\n".join(f"- {format_line(card)}" for card in cards)


def format_line(card: RadarCard) -> str:
    hint = HINTS.get(frozenset(card.actions), "")
    body = f"{LABELS[card.source]}: {card.line}"
    return f"{body}. {hint}".strip()


def kept_mail(store: Store, now: datetime) -> list[dict]:
    """E-mail que já virou cartão continua no Radar até ser arquivado."""
    now = now.astimezone(TZ)
    hidden = _hidden(store, now)
    try:
        cards = json.loads(store.get_setting("radar_open", "") or "[]")
    except json.JSONDecodeError:
        return []
    items = []
    for card in cards:
        if card.get("source") != "email" or card.get("id") in hidden:
            continue
        uid = str(card.get("ref") or "")
        line = str(card.get("line") or "")
        rest = line[len(uid) + 1 :] if uid and line.startswith(uid + " ") else line
        sender, _, subject = rest.partition(" — ")
        if uid:
            items.append({"uid": uid, "from": sender, "subject": subject})
    return items


def remember(store: Store, cards: list[RadarCard]) -> None:
    payload = json.dumps(
        [{"id": card.id, "source": card.source, "line": card.line, "actions": list(card.actions), "ref": card.ref} for card in cards],
        ensure_ascii=False,
    )
    if store.get_setting("radar_open") != payload:
        store.set_setting("radar_open", payload)


def radar_keyboard(cards: list[RadarCard]) -> dict | None:
    rows = []
    for card in cards:
        row = []
        subject = _subject(card.line)
        for action in card.actions:
            code = next(key for key, name in CODES.items() if name == action)
            row.append({"text": f"{BUTTONS[action]} {subject}"[:40], "callback_data": f"rd:{code}:{card.id}"})
        rows.append(row)
    if not rows:
        return None
    return {"inline_keyboard": rows}


def act(store: Store, tasks: TaskBook, card_id: str, action: str, now: datetime, complete=None) -> dict:
    """Concluir, arquivar e remarcar mexem na agenda local. Rascunho não envia."""
    now = now.astimezone(TZ)
    action = CODES.get(action, action)
    if action == "sim":
        return _confirm_move(store, tasks, card_id, now)
    if action == "nao":
        store.set_setting(f"radar_move_{card_id}", "")
        return {"text": "Deixei como está."}
    card = _open_card(store, card_id)
    if card is None:
        return {"text": "Esse cartão já saiu."}
    if action not in card["actions"] and action != "remarcar":
        return {"text": "Esse cartão não tem essa ação."}
    if action == "arquivar":
        _hide(store, now, card_id)
        _accept_seen(store, card)
        return {"text": "Arquivei por hoje."}
    if action == "concluir":
        ref = _task_ref(card)
        if card["source"] not in {"tarefa", "agenda"} or not ref:
            return {"text": "Esse cartão não é uma tarefa."}
        text = tasks.complete(ref)
        _hide(store, now, card_id)
        return {"text": text}
    if action == "remarcar":
        return _propose_move(store, card)
    if action == "rascunho":
        if complete is None:
            return {"text": "Não consegui escrever o rascunho."}
        draft = complete(_draft_prompt(card)).strip()
        if not draft:
            return {"text": "Não consegui escrever o rascunho."}
        return {"text": "Rascunho, você envia:\n" + draft[:3500]}
    return {"text": "Não entendi essa ação."}


def _accept_seen(store: Store, card: dict) -> None:
    ref = str(card.get("ref") or "")
    if ref.startswith("mudou:"):
        task = store.get_task(ref.split(":", 1)[1])
        if task:
            store.set_setting(f"agenda_seen_{task['id']}", task["due_at"])
        return
    if ref.startswith("ics:"):
        uid = ref[4:]
        nxt = store.get_setting(f"agenda_next_ics_{uid}", "")
        if nxt:
            store.set_setting(f"agenda_seen_ics_{uid}", nxt)


def _propose_move(store: Store, card: dict) -> dict:
    ref = _task_ref(card)
    task = store.get_task(ref) if ref else None
    if task is None:
        return {"text": "Esse compromisso é só leitura."}
    due = datetime.fromisoformat(task["due_at"]).astimezone(TZ)
    proposed = due + timedelta(hours=1)
    if proposed.date() != due.date():
        proposed = due.replace(hour=min(due.hour + 1, 23))
    store.set_setting(f"radar_move_{card['id']}", f"{task['id']}|{proposed.isoformat(timespec='minutes')}")
    return {"confirm": f"Mover {task['title']} para {proposed.strftime('%H:%M')}?"}


def _confirm_move(store: Store, tasks: TaskBook, card_id: str, now: datetime) -> dict:
    raw = store.get_setting(f"radar_move_{card_id}", "")
    task_id, _, due = raw.partition("|")
    if not task_id or not due:
        return {"text": "Não tenho um horário novo esperando."}
    task = store.get_task(task_id)
    if task is None:
        return {"text": "Não achei essa tarefa."}
    store.update_task(task_id, due_at=due, status="pending")
    store.set_setting(f"agenda_seen_{task_id}", due)
    store.set_setting(f"radar_move_{card_id}", "")
    _hide(store, now, card_id)
    del tasks
    return {"text": f"Movi {task['title']} para {datetime.fromisoformat(due).astimezone(TZ).strftime('%H:%M')}."}


def _draft_prompt(card: dict) -> str:
    return (
        "Escreva só o texto que o Victor vai copiar e enviar. "
        "Português do Brasil, curto. Não diga que enviou. "
        "Não invente preço, horário ou nome que não esteja abaixo.\n"
        f"Origem: {LABELS.get(card['source'], card['source'])}\n"
        f"Pedido: {card['line']}"
    )


def _tasks(store: Store, now: datetime, hidden: set[str], agenda_refs: set[str]) -> list[RadarCard]:
    cards = []
    for task, due in _today(store, now):
        if task["id"] in agenda_refs:
            continue
        card = _card("tarefa", task["id"], f"{task['title']} às {due.strftime('%H:%M')}", ACTIONS["tarefa"])
        if card.id not in hidden:
            cards.append(card)
    return cards


def _agenda(store: Store, now: datetime, events: list[dict], hidden: set[str], agenda_refs: set[str]) -> list[RadarCard]:
    """Um cartão por fato. Horário mudado vale mais que conflito, e conflito vale mais que a tarefa."""
    cards = []
    today = _today(store, now)
    changed: dict[str, str] = {}
    for task, due in today:
        seen = store.get_setting(f"agenda_seen_{task['id']}", "")
        current = task["due_at"]
        if not seen:
            store.set_setting(f"agenda_seen_{task['id']}", current)
            continue
        if seen != current:
            changed[task["id"]] = _clock(seen)
    clusters = _clusters(_conflicts(today))
    covered: set[str] = set()
    for cluster in clusters:
        ids = {task["id"] for task, _due in cluster}
        movers = [(task, due) for task, due in cluster if task["id"] in changed]
        if not movers:
            continue
        task, due = movers[-1]
        others = [(other, when) for other, when in cluster if other["id"] != task["id"]]
        line = f"{task['title']} mudou de {changed[task['id']]} para {due.strftime('%H:%M')}"
        clash = _named(others)
        if clash:
            line += f" e conflita com {clash}"
        _add_agenda(cards, hidden, "mudou:" + task["id"], line, ("concluir", "remarcar", "arquivar"))
        covered.update(ids)
    for task, due in today:
        if task["id"] in covered or task["id"] not in changed:
            continue
        line = f"{task['title']} mudou de {changed[task['id']]} para {due.strftime('%H:%M')}"
        _add_agenda(cards, hidden, "mudou:" + task["id"], line, ("concluir", "remarcar", "arquivar"))
        covered.add(task["id"])
    for cluster in clusters:
        ids = {task["id"] for task, _due in cluster}
        if ids & covered:
            continue
        later = cluster[-1][0]
        _add_agenda(cards, hidden, "conflito:" + later["id"], _conflict_line(cluster), ("remarcar", "arquivar"))
        covered.update(ids)
    agenda_refs.update(covered)
    for event in events:
        reason = _event_reason(store, event, now)
        if not reason:
            continue
        card = _card("agenda", "ics:" + event["uid"], reason, ("arquivar",))
        if card.id not in hidden:
            cards.append(card)
    return cards


def _event_reason(store: Store, event: dict, now: datetime) -> str:
    start = event["start"].astimezone(TZ)
    key = f"agenda_seen_ics_{event['uid']}"
    current = start.isoformat(timespec="minutes")
    seen = store.get_setting(key, "")
    if not seen:
        store.set_setting(key, current)
    elif seen != current:
        store.set_setting(f"agenda_next_ics_{event['uid']}", current)
        return f"{event['title']} mudou de {_clock(seen)} para {start.strftime('%H:%M')}"
    if not event.get("description") and within(start, now):
        return f"{event['title']} às {start.strftime('%H:%M')} está sem preparo"
    return ""


def _add_agenda(cards: list[RadarCard], hidden: set[str], ref: str, line: str, actions: tuple[str, ...]) -> None:
    card = _card("agenda", ref, line, actions)
    if card.id not in hidden:
        cards.append(card)


def _named(items: list[tuple[dict, datetime]]) -> str:
    return " e ".join(f"{task['title']} às {due.strftime('%H:%M')}" for task, due in items)


def _conflict_line(cluster: list[tuple[dict, datetime]]) -> str:
    bits = [f"{task['title']} às {due.strftime('%H:%M')}" for task, due in cluster]
    if len(bits) == 2:
        return f"conflito entre {bits[0]} e {bits[1]}"
    return "conflito entre " + ", ".join(bits[:-1]) + " e " + bits[-1]


def _clusters(pairs: list[tuple[tuple[dict, datetime], tuple[dict, datetime]]]) -> list[list[tuple[dict, datetime]]]:
    parent: dict[str, str] = {}
    nodes: dict[str, tuple[dict, datetime]] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for earlier, later in pairs:
        nodes[earlier[0]["id"]] = earlier
        nodes[later[0]["id"]] = later
        parent[find(later[0]["id"])] = find(earlier[0]["id"])
    groups: dict[str, list[tuple[dict, datetime]]] = {}
    for item_id, item in nodes.items():
        groups.setdefault(find(item_id), []).append(item)
    return [sorted(group, key=lambda item: item[1]) for group in groups.values()]


def _subject(line: str) -> str:
    if line.startswith("conflito entre "):
        names = [part.split(" às ")[0].strip() for part in line[len("conflito entre ") :].split(" e ")]
        return " e ".join(names)[:32]
    head = line.split(" e conflita com ")[0]
    for marker in (" mudou de ", " — ", " às ", " está "):
        if marker in head:
            head = head.split(marker, 1)[0]
            break
    parts = head.split(" ", 1)
    if parts and parts[0].isdigit() and len(parts) == 2:
        head = parts[1]
    return head.strip()[:32]


def _conflicts(today: list[tuple[dict, datetime]]) -> list[tuple[tuple[dict, datetime], tuple[dict, datetime]]]:
    ordered = sorted(today, key=lambda item: item[1])
    pairs = []
    for earlier, later in zip(ordered, ordered[1:]):
        if later[1] - earlier[1] <= timedelta(minutes=30):
            pairs.append((earlier, later))
    return pairs


def _people(items: list[dict], source: str, hidden: set[str]) -> list[RadarCard]:
    cards = []
    for item in items:
        if source == "email":
            ref = str(item.get("uid") or "")
            line = f"{ref} {item.get('from') or ''} — {item.get('subject') or ''}".strip()
        else:
            title = str(item.get("title") or "")
            body = str(item.get("body") or "")
            if is_group(title, body):
                continue
            ref = str(item.get("id") or "")
            line = f"{title} — {body}".strip(" —")
        if not ref:
            continue
        card = _card(source, ref, line, ACTIONS[source])
        if card.id not in hidden:
            cards.append(card)
    return cards


def _disk(disks: list[str], hidden: set[str]) -> list[RadarCard]:
    cards = []
    for item in disks:
        text = " ".join(str(item).split())
        if not text:
            continue
        card = _card("disco", text, text, ACTIONS["disco"])
        if card.id not in hidden:
            cards.append(card)
    return cards


def _card(source: str, ref: str, line: str, actions: tuple[str, ...]) -> RadarCard:
    digest = hashlib.sha256(f"{source}\n{ref}".encode()).hexdigest()[:8]
    return RadarCard(digest, source, line, actions, ref)


def _today(store: Store, now: datetime) -> list[tuple[dict, datetime]]:
    rows = []
    for task in store.pending_tasks():
        due = datetime.fromisoformat(task["due_at"]).astimezone(TZ)
        if due.date() == now.date():
            rows.append((task, due))
    return rows


def _mail_items(mail: list[dict] | str) -> list[dict]:
    if isinstance(mail, list):
        return mail
    items = []
    for line in (mail or "").splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        numbered = re.search(r"Número (\d+)\s*\.?$", body)
        if numbered:
            uid = numbered.group(1)
            core = body[: numbered.start()].strip().rstrip(".")
            sender, _, subject = core.partition(": ")
            items.append({"uid": uid, "from": sender, "subject": subject})
            continue
        uid, _, rest = body.partition(" ")
        sender, _, subject = rest.partition(" — ")
        if uid.isdigit():
            items.append({"uid": uid, "from": sender, "subject": subject})
    return items


def _hidden(store: Store, now: datetime) -> set[str]:
    raw = store.get_setting(f"radar_hide_{now.date().isoformat()}", "")
    return {item for item in raw.split(",") if len(item) == 8}


def _hide(store: Store, now: datetime, card_id: str) -> None:
    found = _hidden(store, now)
    found.add(card_id)
    store.set_setting(f"radar_hide_{now.date().isoformat()}", ",".join(sorted(found)))


def _open_card(store: Store, card_id: str) -> dict | None:
    try:
        cards = json.loads(store.get_setting("radar_open", "") or "[]")
    except json.JSONDecodeError:
        return None
    for card in cards:
        if card.get("id") == card_id:
            return card
    return None


def _task_ref(card: dict) -> str:
    ref = str(card.get("ref") or "")
    if ref.startswith("ics:"):
        return ""
    if ":" in ref:
        return ref.split(":", 1)[1]
    return ref


def _clock(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone(TZ).strftime("%H:%M")
    except ValueError:
        return value[-5:]
