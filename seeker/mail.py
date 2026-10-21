"""E-mail da conta do Victor. Ler é livre. Rascunho, envio e exclusão esperam o sim."""

from __future__ import annotations

import imaplib
import smtplib
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage

SLOTS = ((9, 0), (21, 0))
WATCH_EVERY = timedelta(minutes=15)


def mail_slot(now: datetime) -> str | None:
    day = now.date().isoformat()
    if (now.hour, now.minute) >= (21, 0):
        return f"{day}_2100"
    if (now.hour, now.minute) >= (9, 0):
        return f"{day}_0900"
    return None


def new_mail(box, store, now: datetime) -> str:
    """Avisa só o e-mail que ainda não foi contado. A primeira leitura só marca."""
    if not getattr(box, "ready", lambda: False)() or not _watch_due(store, now):
        return ""
    store.set_setting("mail_watch_at", now.isoformat(timespec="minutes"))
    try:
        items = box.unseen_items(15)
    except Exception:
        return ""
    uids = [str(item["uid"]) for item in items]
    if store.get_setting("mail_seen_ready") != "yes":
        remember_seen(store, uids)
        return ""
    novel = [item for item in items if str(item["uid"]) not in _seen(store)]
    remember_seen(store, uids)
    if not novel:
        return ""
    lines = [mail_line(item) for item in novel]
    lines.append("Para rascunhar, enviar ou apagar, diga o número. Eu mostro o texto e espero um sim.")
    return "Chegou e-mail\n\n" + "\n".join(lines)


def remember_seen(store, uids: list[str]) -> None:
    found = _seen(store)
    found.update(str(uid) for uid in uids if str(uid).isdigit())
    store.set_setting("mail_seen", ",".join(sorted(found)[-80:]))
    store.set_setting("mail_seen_ready", "yes")


def _seen(store) -> set[str]:
    return {item for item in store.get_setting("mail_seen", "").split(",") if item.isdigit()}


def _watch_due(store, now: datetime) -> bool:
    raw = store.get_setting("mail_watch_at", "")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return now - last >= WATCH_EVERY


def unseen_fresh(store, items: list[dict]) -> list[dict]:
    """Devolve o que ainda não foi avisado e marca esses números."""
    fresh = peek_fresh(store, items)
    if fresh:
        remember_seen(store, [str(item["uid"]) for item in fresh])
    return fresh


def peek_fresh(store, items: list[dict]) -> list[dict]:
    return [item for item in items if str(item.get("uid") or "") not in _seen(store)]


def mail_notice(store, items: list[dict]) -> str:
    """Lista só o que ainda não foi avisado e marca esses números."""
    fresh = unseen_fresh(store, items)
    if not fresh:
        return ""
    return format_unseen(fresh)


def format_unseen(items: list[dict]) -> str:
    if not items:
        return "Nenhum e-mail novo."
    lines = ["E-mail", ""]
    for item in items:
        lines.append(mail_line(item))
    lines.append("")
    lines.append("Para rascunhar, enviar ou apagar, diga o número.")
    return "\n".join(lines)


class Mailbox:
    def __init__(self, env: dict[str, str]):
        self.imap_host = env.get("IMAP_SERVER") or env.get("IMAP_HOST") or ""
        self.imap_user = env.get("IMAP_USER") or ""
        self.imap_password = env.get("IMAP_PASSWORD") or ""
        self.smtp_host = env.get("SMTP_HOST") or ""
        self.smtp_port = int(env.get("SMTP_PORT") or "587")
        self.smtp_user = env.get("SMTP_USER") or self.imap_user
        self.smtp_password = env.get("SMTP_PASSWORD") or self.imap_password

    def ready(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password and self.smtp_host)

    def unseen(self, limit: int = 8) -> str:
        if not self.ready():
            return "O e-mail não está configurado."
        try:
            return format_unseen(self.unseen_items(limit))
        except Exception:
            return "Não consegui ler a caixa."

    def unseen_items(self, limit: int = 8) -> list[dict]:
        limit = max(1, min(int(limit or 8), 15))
        with self._imap() as imap:
            imap.select("INBOX", readonly=True)
            status, data = imap.uid("SEARCH", None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return []
            uids = data[0].split()[-limit:]
            return [self._header(imap, uid.decode()) for uid in uids]

    def draft(self, to: str, subject: str, body: str) -> str:
        self._check(to, subject, body)
        message = self._message(to, subject, body)
        with self._imap() as imap:
            folder = _drafts_folder(imap)
            imap.append(folder, "", imaplib.Time2Internaldate(time.time()), message.as_bytes())
        return f"Rascunho salvo para {to}."

    def send(self, to: str, subject: str, body: str) -> str:
        self._check(to, subject, body)
        message = self._message(to, subject, body)
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.smtp_user, self.smtp_password)
            smtp.send_message(message)
        return f"Enviei para {to}."

    def delete(self, uid: str) -> str:
        if not str(uid).isdigit():
            return "Diga o número do e-mail."
        if not self.ready():
            return "O e-mail não está configurado."
        with self._imap() as imap:
            trash = _trash_folder(imap)
            imap.select("INBOX")
            if trash:
                imap.uid("COPY", uid, trash)
            imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            imap.expunge()
        return f"Apaguei o e-mail {uid}."

    def _imap(self) -> imaplib.IMAP4_SSL:
        imap = imaplib.IMAP4_SSL(self.imap_host, 993)
        imap.login(self.imap_user, self.imap_password)
        return imap

    def _message(self, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.smtp_user
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return message

    def _check(self, to: str, subject: str, body: str) -> None:
        if not self.ready():
            raise ValueError("O e-mail não está configurado.")
        if "@" not in to or not subject.strip() or not body.strip():
            raise ValueError("Faltam destinatário, assunto ou texto.")

    def _header(self, imap: imaplib.IMAP4_SSL, uid: str) -> dict:
        status, data = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        text = ""
        if status == "OK" and data and isinstance(data[0], tuple):
            text = data[0][1].decode("utf-8", "replace")
        sender = person(_field(text, "From")) or "Alguém"
        subject = readable(_field(text, "Subject")) or "(sem assunto)"
        return {"uid": uid, "from": sender[:80], "subject": subject[:120]}


def mail_line(item: dict) -> str:
    who = person(str(item.get("from") or "")) or "Alguém"
    subject = readable(str(item.get("subject") or "")) or "(sem assunto)"
    return f"- {who}: {subject}. Número {item['uid']}."


def readable(value: str) -> str:
    text = value or ""
    try:
        return " ".join(str(make_header(decode_header(text))).split())
    except Exception:
        return " ".join(text.split())


def person(value: str) -> str:
    text = readable(value)
    if "<" in text:
        name = text.split("<", 1)[0].strip().strip('"')
        if name:
            return name
    if "@" in text:
        return text.split("@", 1)[0]
    return text


def _field(header: str, name: str) -> str:
    prefix = name.lower() + ":"
    for line in _unfold(header).splitlines():
        if line.lower().startswith(prefix):
            return " ".join(line.split(":", 1)[1].split())
    return ""


def _unfold(header: str) -> str:
    lines = (header or "").replace("\r\n", "\n").split("\n")
    folded = []
    for line in lines:
        if folded and (line.startswith(" ") or line.startswith("\t")):
            folded[-1] += " " + line.strip()
        else:
            folded.append(line)
    return "\n".join(folded)


def _folders(imap: imaplib.IMAP4_SSL) -> list[str]:
    status, data = imap.list()
    if status != "OK" or not data:
        return []
    found = []
    for row in data:
        if not row:
            continue
        text = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
        name = text.rsplit(' "/" ', 1)[-1].strip().strip('"')
        found.append(name)
    return found


def _drafts_folder(imap: imaplib.IMAP4_SSL) -> str:
    for name in _folders(imap):
        folded = name.casefold()
        if folded.endswith("drafts") or folded.endswith("rascunhos"):
            return f'"{name}"' if " " in name or "/" in name else name
    return "Drafts"


def _trash_folder(imap: imaplib.IMAP4_SSL) -> str:
    for name in _folders(imap):
        folded = name.casefold()
        if folded.endswith("trash") or folded.endswith("lixeira") or folded.endswith("bin"):
            return f'"{name}"' if " " in name or "/" in name else name
    return ""
