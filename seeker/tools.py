"""Leitura presa às pastas marcadas, e um PowerShell contínuo que só corre depois do sim."""

from __future__ import annotations

import base64
import os
import queue
import subprocess
import threading
import uuid
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
SKIP_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
    "$Recycle.Bin",
    "System Volume Information",
    "Windows",
}


class ToolError(Exception):
    pass


class Files:
    def __init__(self, roots: tuple[Path, ...] | list[Path], cap: int):
        self.roots = [path.resolve() for path in roots]
        self.cap = cap

    def list_dir(self, raw: str) -> str:
        path = self._resolve(raw, allow_empty=True)
        if not path.exists():
            raise ToolError("Pasta não encontrada.")
        if not path.is_dir():
            raise ToolError("Isso é um arquivo, não uma pasta.")
        entries = []
        children = [child for child in path.iterdir() if child.name != ".env"]
        for child in sorted(children, key=lambda item: item.name.lower())[:200]:
            suffix = "\\" if child.is_dir() else ""
            entries.append(child.name + suffix)
        if not entries:
            return "Pasta vazia."
        hidden = max(0, len(children) - len(entries))
        text = "\n".join(entries)
        if hidden:
            text += f"\n… mais {hidden} itens."
        return text

    def read_file(self, raw: str) -> str:
        if not (raw or "").strip():
            raise ToolError("Diga qual arquivo ler.")
        path = self._resolve(raw, allow_empty=False)
        if not path.exists():
            raise ToolError("Arquivo não encontrado.")
        if path.is_dir():
            raise ToolError("Isso é uma pasta. Use a listagem.")
        data = path.read_bytes()
        if b"\x00" in data[:1024]:
            raise ToolError("Arquivo binário. Não li.")
        text = data.decode("utf-8", errors="replace")
        if len(text) > self.cap:
            return text[: self.cap] + "\n… arquivo cortado."
        return text

    def find_files(self, query: str, root: str = "") -> str:
        needle = " ".join((query or "").split()).casefold()
        if len(needle) < 2:
            raise ToolError("Diga pelo menos duas letras do nome.")
        starts = [self._resolve(root, allow_empty=True)] if (root or "").strip() else list(self.roots)
        hits: list[str] = []
        seen = 0
        for start in starts:
            if not start.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(start):
                seen += 1
                dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS and name != ".env"]
                for name in filenames:
                    if name == ".env" or needle not in name.casefold():
                        continue
                    hits.append(str(Path(dirpath) / name))
                    if len(hits) >= 40:
                        return "\n".join(hits) + "\n… há mais. Afine o nome."
                if seen >= 20000:
                    return ("\n".join(hits) if hits else "Procura interrompida. Afine a pasta.") + "\n… busca interrompida."
        if not hits:
            return "Nenhum arquivo com esse nome."
        return "\n".join(hits)

    def _resolve(self, raw: str, allow_empty: bool) -> Path:
        text = (raw or "").strip().strip('"')
        if not text:
            if not allow_empty:
                raise ToolError("Caminho vazio.")
            return self.roots[0]
        path = Path(text)
        if not path.is_absolute():
            path = self.roots[0] / path
        resolved = path.resolve()
        if resolved.name == ".env":
            raise ToolError("Esse arquivo fica de fora.")
        if not any(_inside(root, resolved) for root in self.roots):
            raise ToolError("Fora das pastas permitidas.")
        return resolved


def _inside(root: Path, path: Path) -> bool:
    root_n = os.path.normcase(str(root))
    path_n = os.path.normcase(str(path))
    if path_n == root_n:
        return True
    prefix = root_n if root_n.endswith(os.sep) else root_n + os.sep
    return path_n.startswith(prefix)


class Terminal:
    """Uma sessão só. O próximo comando continua na pasta em que o anterior parou."""

    def __init__(self, cwd: Path, timeout: int, cap: int):
        self.cwd = Path(cwd)
        self.timeout = timeout
        self.cap = cap
        self.log: list[str] = []
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        token = uuid.uuid4().hex[:8]
        self._done = f"__DONE_{token}__"
        self._cwd_mark = f"__CWD_{token}__"

    def text(self) -> str:
        return "\n".join(self.log[-80:])

    def run(self, command: str) -> str:
        command = " ".join((command or "").splitlines()).strip()
        if not command:
            return "Comando vazio."
        with self._lock:
            self._ensure()
            assert self._proc is not None and self._proc.stdin is not None
            self.log.append(f"PS {self.cwd}> {command}")
            self._proc.stdin.write((command + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            output, code, new_cwd = self._collect()
            if new_cwd:
                self.cwd = Path(new_cwd)
            text = _cap(output, self.cap)
            shown = f"{text}\nCódigo de saída: {code}".strip()
            self.log.append(shown)
            return shown

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self.cwd.mkdir(parents=True, exist_ok=True)
        script = f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -LiteralPath '{_ps_quote(self.cwd)}'
while ($true) {{
  $line = [Console]::In.ReadLine()
  if ($null -eq $line -or $line -eq '__EXIT__') {{ break }}
  $code = 0
  try {{
    Invoke-Expression $line 2>&1 | ForEach-Object {{ $_.ToString() }}
    if ($LASTEXITCODE) {{ $code = $LASTEXITCODE }}
  }} catch {{
    Write-Output ($_ | Out-String)
    $code = 1
  }}
  Write-Output ('{self._cwd_mark}' + (Get-Location).Path)
  Write-Output ('{self._done}' + $code)
}}
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.cwd,
            creationflags=CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._pump, name="seeker-terminal", daemon=True).start()

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in iter(proc.stdout.readline, b""):
            self._queue.put(_decode(raw).rstrip("\r\n"))
        self._queue.put(None)

    def _collect(self) -> tuple[str, int, str]:
        lines: list[str] = []
        code = 1
        found = ""
        finished = False
        deadline = threading.Event()
        timer = threading.Timer(self.timeout, deadline.set)
        timer.start()
        try:
            while not deadline.is_set():
                try:
                    line = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    break
                if line.startswith(self._done):
                    raw_code = line[len(self._done):] or "0"
                    code = int(raw_code) if raw_code.lstrip("-").isdigit() else 0
                    finished = True
                    break
                if line.startswith(self._cwd_mark):
                    found = line[len(self._cwd_mark):]
                    continue
                lines.append(line)
        finally:
            timer.cancel()
        if not finished:
            self.stop()
            lines.append(f"O comando passou de {self.timeout} segundos e foi interrompido.")
        return "\n".join(lines).strip(), code, found


class Shell:
    def __init__(self, cwd: Path, timeout: int, cap: int):
        self.session = Terminal(cwd, timeout, cap)

    @property
    def cwd(self) -> Path:
        return self.session.cwd

    def run(self, command: str) -> str:
        return self.session.run(command)

    def stop(self) -> None:
        self.session.stop()


def _ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _join(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part.strip()]
    return "\n".join(parts)


def _cap(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "\n… saída cortada."
