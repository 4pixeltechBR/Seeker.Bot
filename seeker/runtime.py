"""Liga banco, modelos, agenda e a janela. Tudo desta pasta, nada do Seeker antigo."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from seeker.agent import Agent, Broker, Control
from seeker.browser import PageReader, read_page_skill, submit_form_skill
from seeker.skills.feed import read_feed_skill
from seeker.skills.last30 import last30_skill
from seeker.brain import Brain
from seeker.review import review_day
from seeker.config import KEY_FIELDS, PROJECT_ROOT, Config, load_config, load_env, save_env_keys, save_models, settings_view
from seeker.mcp_hub import McpHub, configure_mcp_skill
from seeker.providers import Cascade, build_providers
from seeker.routine import RoutineBook
from seeker.schedule import TZ, Scheduler, TaskBook, format_when
from seeker.skills.gpu import gpu_skill
from seeker.mail import Mailbox
from seeker.skills.mail_skill import delete_mail_skill, read_mail_skill, send_mail_skill, write_mail_skill
from seeker.skills.maker import create_skill_tool, load_custom
from seeker.skills.research import research_skill
from seeker.skills.secret import request_secret_skill
from seeker.skills.vault import vault_skill
from seeker.secrets import hide_tokens, scrub_notes
from seeker.store import Store
from seeker.telegram_bot import TelegramBot, allowed_users
from seeker.transcript import Message
from seeker.tools import Files, Shell
from seeker.speech import LocalVoice, SpeechError
from seeker.voice import transcribe

log = logging.getLogger("seeker.runtime")


class Runtime:
    def __init__(self, config: Config, env: dict[str, str], store: Store, client: httpx.Client, providers, search):
        self.config = config
        self.env = env
        self.store = store
        self.client = client
        self.providers = providers
        self.search = search
        self.files = Files(config.roots, config.file_cap_chars)
        self.shell = Shell(config.roots[0], config.shell_timeout_seconds, config.output_cap_chars)
        self.tasks = TaskBook(store)
        self.routines = RoutineBook(store)
        self.broker = Broker()
        self.control = Control()
        self.agent = Agent(
            store,
            Cascade(providers),
            self.files,
            self.shell,
            search,
            self.tasks,
            self.broker,
            self.control,
            config.max_tool_steps,
        )
        self.agent.routines = self.routines
        self.brain = Brain(config.vault)
        self.agent.brain = self.brain
        self.scheduler = Scheduler(store, self.announce)
        self.scheduler.review_hour = config.review_hour
        self.scheduler.morning_hour = config.morning_hour
        self.scheduler.morning_minute = config.morning_minute
        self.scheduler.on_review = self.review_today
        self.scheduler.on_morning = self.post_morning
        self.scheduler.on_disk = self.post_disk
        self.scheduler.on_news = self.post_news
        self.scheduler.on_mail = self.post_mail
        self.scheduler.on_scout = self.post_scout
        self.scheduler.on_watch = self.post_watch
        self.scheduler.on_curiosity = self.post_curiosity
        self.mailbox = Mailbox(env)
        self.scheduler.on_routine = self.run_routine
        self._local_voice = None
        self._mail_cache: list[dict] = []
        self._mail_at: datetime | None = None
        self._wa_cache: list[dict] = []
        self._wa_at: datetime | None = None
        self.mcp = McpHub()
        self.telegram = TelegramBot(
            env.get("TELEGRAM_BOT_TOKEN", ""),
            allowed_users(env.get("TELEGRAM_ALLOWED_USERS", "")),
            self,
        )
        for root in config.roots:
            if root.exists():
                continue
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def start(self) -> None:
        changed = self.store.rewrite_secrets(hide_tokens)
        changed += scrub_notes(self.config.vault, hide_tokens)
        if changed:
            log.info("cofre: %s trechos deixaram de guardar chave", changed)
        self.scheduler.start()
        self.mcp.start(self.config.root / "mcp.json", self.agent.catalog)
        self.telegram.start()

    def close(self) -> None:
        self.telegram.stop()
        self.mcp.stop()
        self.scheduler.stop()
        self.control.cancel()
        self.broker.cancel_all()
        self.agent.gate.cancel_all()
        self.shell.stop()
        self.client.close()

    def settings(self) -> dict:
        return settings_view(self.config, self.env)

    def update_settings(self, keys: dict, models: dict) -> dict:
        saved = save_env_keys(self.config.root / ".env", keys)
        for key in saved:
            self.env[key] = str(keys[key]).strip()
        provider_keys = {item.env_key for item in self.config.providers}
        if models or provider_keys.intersection(saved):
            if models:
                save_models(self.config.root / "config.toml", models)
                self.config = load_config(self.config.root)
            providers, search, evidence = build_providers(self.config, self.env, self.client)
            self.providers = providers
            self.agent.cascade = Cascade(providers)
            self.search = evidence if evidence is not None else search
        if "IMAP_PASSWORD" in saved:
            self.mailbox.imap_password = self.env["IMAP_PASSWORD"]
            if not self.env.get("SMTP_PASSWORD"):
                self.mailbox.smtp_password = self.env["IMAP_PASSWORD"]
        if "TELEGRAM_BOT_TOKEN" in saved:
            self.telegram.token = self.env["TELEGRAM_BOT_TOKEN"]
            if self.telegram._thread is None:
                self.telegram.start()
        view = self.settings()
        view["saved"] = saved
        return view

    def provider_status(self) -> list[dict]:
        status = []
        for item, provider in zip(self.config.providers, self.providers, strict=False):
            status.append({"name": item.name, "model": item.model, "ready": provider.available()})
        return status

    def pulse(self) -> dict:
        now = datetime.now(TZ)
        tasks = []
        for task in self.store.pending_tasks():
            due = datetime.fromisoformat(task["due_at"])
            tasks.append(
                {
                    "id": task["id"],
                    "title": task["title"],
                    "when": format_when(due, task["repeat"]),
                    "overdue": due <= now,
                }
            )
        routines = []
        for routine in self.store.active_routines():
            due = datetime.fromisoformat(routine["due_at"])
            routines.append(
                {
                    "id": routine["id"],
                    "title": routine["instruction"],
                    "when": format_when(due, routine["repeat"]),
                    "overdue": due <= now,
                }
            )
        return {
            "tasks": tasks,
            "routines": routines,
            "suggestions": self.store.open_suggestions(),
            "notices": self.store.unseen_notices(),
            "radar": [card.public() for card in self._radar(now, mark_mail=False)],
            "secrets": self.agent.gate.pending(),
        }

    def voice(self) -> LocalVoice:
        if self._local_voice is None:
            device = "cuda"
            try:
                import torch

                if not torch.cuda.is_available():
                    device = "cpu"
            except ImportError:
                device = "cpu"
            configured_device = self.config.voice_device
            if configured_device == "cuda" and device != "cuda":
                configured_device = "cpu"
            self._local_voice = LocalVoice(
                self.store,
                device=configured_device,
                voice=self.config.voice_name,
            )
        return self._local_voice

    def transcribe(self, audio_b64: str, mime: str) -> str:
        gemini = next((item for item in self.config.providers if item.kind == "gemini"), None)
        if gemini is None:
            raise RuntimeError("Não há Gemini no config.toml para transcrever.")
        groq_key = self.env.get("GROQ_API_KEY", "")
        if groq_key:
            import base64
            import io
            files = {"file": ("audio.webm", base64.b64decode(audio_b64), mime)}
            response = self.client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                data={"model": "whisper-large-v3-turbo", "language": "pt"},
                files=files,
            )
            if response.status_code < 400:
                return str(response.json().get("text") or "").strip()
        return transcribe(
            self.client,
            gemini.base_url,
            gemini.model,
            self.env.get(gemini.env_key, ""),
            audio_b64,
            mime,
        )

    def run_routine(self, routine: dict) -> str:
        if not self.control.start():
            raise RuntimeError("ocupado")
        self.agent.routine_mode = True
        try:
            title = "Rotina: " + routine["instruction"][:42]
            chat = self.store.create_chat(title=title)
            self.agent.run(chat["id"], routine["instruction"], lambda event: None)
            answer = ""
            for message in reversed(self.store.messages(chat["id"])):
                if message["role"] == "assistant" and message["content"].strip():
                    answer = message["content"].strip()
                    break
            note = answer or "A rotina rodou sem resposta."
            self.store.add_notice("Rotina: " + note[:240])
            self.toast("Rotina: " + routine["instruction"][:80])
            return note
        finally:
            self.agent.routine_mode = False
            self.control.finish()

    def post_disk(self, when: datetime) -> None:
        from seeker.disk import disk_alerts

        lines = disk_alerts()
        if not lines:
            return
        text = "\n".join(lines)
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_news(self, when: datetime) -> None:
        from seeker.news import news_digest

        text = news_digest(lambda url: _fetch_text(self.client, url), when)
        if not text:
            return
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_scout(self, when: datetime) -> None:
        from seeker.scout import scout_digest

        text = scout_digest(lambda url: _fetch_text(self.client, url), when)
        if not text:
            return
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def announce(self, text: str) -> None:
        self.toast(text)
        if not text.startswith("Agora:"):
            return
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_curiosity(self, when: datetime) -> None:
        from seeker.curiosity import curiosity_text

        text = curiosity_text(lambda url: _fetch_text(self.client, url), self.brain, when)
        if not text:
            return
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_watch(self, now: datetime) -> None:
        from seeker.mail import new_mail

        text = new_mail(self.mailbox, self.store, now)
        if not text:
            return
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_mail(self, when: datetime) -> None:
        if not self.mailbox.ready():
            return
        try:
            from seeker.mail import mail_notice

            text = mail_notice(self.store, self.mailbox.unseen_items(8))
        except Exception:
            return
        if not text:
            return
        self.store.add_notice(text)
        self.toast(text[:120])
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text)

    def post_morning(self, when: datetime) -> None:
        from seeker.radar import format_radar, radar_keyboard, remember

        cards = self._radar(when, mark_mail=True)
        text = format_radar(cards)
        if not text:
            return
        remember(self.store, cards)
        self.store.add_notice(text)
        self.toast(text[:120])
        keyboard = radar_keyboard(cards)
        for user_id in sorted(self.telegram.allowed):
            self.telegram.send(user_id, text, reply_markup=keyboard)

    def radar_act(self, card_id: str, action: str) -> dict:
        from seeker.radar import act, remember

        now = datetime.now(TZ)
        result = act(self.store, self.tasks, card_id, action, now, complete=self.complete)
        remember(self.store, self._radar(now, mark_mail=False))
        return result

    def _radar(self, when: datetime, mark_mail: bool):
        from seeker.agenda import read_ics
        from seeker.disk import disk_alerts
        from seeker.radar import radar_cards, remember

        sources = self.config.radar_sources()
        cards = radar_cards(
            self.store,
            self.brain,
            when,
            disks=disk_alerts() if "disco" in sources else [],
            mail=self._radar_mail(when, mark_mail) if "email" in sources else [],
            events=read_ics(self.config.calendar_ics, when) if "agenda" in sources else [],
            whatsapp=self._radar_whatsapp(when) if "whatsapp" in sources else [],
            sources=sources,
        )
        remember(self.store, cards)
        return cards

    def _radar_mail(self, when: datetime, mark: bool) -> list[dict]:
        fresh: list[dict] = []
        if self.mailbox.ready() and not mark and self._mail_at is not None and when - self._mail_at < timedelta(minutes=15):
            fresh = self._mail_cache
        elif self.mailbox.ready():
            try:
                items = self.mailbox.unseen_items(5)
            except Exception:
                items = []
            if mark:
                from seeker.mail import unseen_fresh

                fresh = unseen_fresh(self.store, items)
            else:
                from seeker.mail import peek_fresh

                fresh = peek_fresh(self.store, items)
            self._mail_cache = fresh
            self._mail_at = when
        return self._merge_mail(fresh, when)

    def _merge_mail(self, fresh: list[dict], when: datetime) -> list[dict]:
        from seeker.radar import kept_mail

        merged = []
        seen = set()
        for item in [*fresh, *kept_mail(self.store, when)]:
            uid = str(item.get("uid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            merged.append(item)
        return merged

    def _radar_whatsapp(self, when: datetime) -> list[dict]:
        if self._wa_at is not None and when - self._wa_at < timedelta(seconds=60):
            return self._wa_cache
        from seeker.whatsapp import read_toasts

        try:
            self._wa_cache = read_toasts(now=when)
        except Exception:
            self._wa_cache = []
        self._wa_at = when
        return self._wa_cache

    def review_today(self, when: datetime) -> list[str]:
        return review_day(self.store, self.brain, self.complete, when)

    def complete(self, prompt: str) -> str:
        chunks: list[str] = []
        for event in Cascade(self.providers).stream([Message("user", prompt)], None):
            if event["type"] == "token":
                chunks.append(event["text"])
            elif event["type"] == "error" and not chunks:
                return ""
        return "".join(chunks)

    def toast(self, text: str) -> None:
        try:
            from winotify import Notification

            Notification(app_id="Seeker", title="Seeker", msg=text, duration="short").show()
        except Exception:
            log.info("aviso sem notificação do Windows: %s", text)


def _fetch_text(client, url: str) -> tuple[int, str]:
    try:
        response = client.get(
            url,
            headers={"User-Agent": "Seeker", "Accept": "*/*"},
            follow_redirects=True,
            timeout=20.0,
        )
        return response.status_code, response.text
    except Exception:
        return 0, ""


def build_runtime(root: Path | None = None, providers=None, search=None, client: httpx.Client | None = None) -> Runtime:
    root = (root or PROJECT_ROOT).resolve()
    config = load_config(root)
    env = load_env(root / ".env")
    store = Store(root / "data" / "seeker.db")
    http = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))
    evidence = None
    if providers is None or search is None:
        built, built_search, built_evidence = build_providers(config, env, http)
        if providers is None:
            providers = built
        if search is None:
            search = built_search
            evidence = built_evidence
    runtime = Runtime(config, env, store, http, providers, search)
    lookup = evidence if evidence is not None else search
    if lookup is not None:
        runtime.agent.catalog.add(research_skill(lookup))
    reader = PageReader(runtime.client)
    for problem in load_custom(runtime.agent.catalog, runtime.config.root):
        log.warning("ferramenta custom ignorada: %s", problem)
    runtime.agent.catalog.add(gpu_skill())
    runtime.agent.catalog.add(vault_skill(
        groq_key=env.get("GROQ_API_KEY", ""),
        key_of=lambda: runtime.env.get("GROQ_API_KEY", ""),
        brain=runtime.brain,
    ))
    runtime.agent.catalog.add(request_secret_skill())
    runtime.agent.key_status = lambda: [(label, bool(runtime.env.get(key))) for key, label in KEY_FIELDS]
    runtime.agent.catalog.add(create_skill_tool(runtime.agent.catalog, runtime.config.root))
    runtime.agent.catalog.add(read_page_skill(reader))
    runtime.agent.catalog.add(read_feed_skill(reader))
    runtime.agent.catalog.add(read_mail_skill(runtime.mailbox))
    runtime.agent.catalog.add(write_mail_skill(runtime.mailbox))
    runtime.agent.catalog.add(send_mail_skill(runtime.mailbox))
    runtime.agent.catalog.add(delete_mail_skill(runtime.mailbox))
    runtime.agent.catalog.add(last30_skill(lambda url: _fetch_text(runtime.client, url)))
    runtime.agent.catalog.add(submit_form_skill(reader))
    runtime.agent.catalog.add(
        configure_mcp_skill(runtime.mcp, runtime.agent.catalog, runtime.config.root / "mcp.json")
    )
    return runtime


def configure_logging(root: Path) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "seeker.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
