"""Abre a janela. Fechar esconde; Sair, no ícone ao lado do relógio, encerra."""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from seeker.config import PROJECT_ROOT
from seeker.runtime import build_runtime, configure_logging
from seeker.server import make_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="seeker")
    parser.add_argument("--server-only", action="store_true")
    parser.add_argument("--root", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else PROJECT_ROOT
    configure_logging(root)
    runtime = build_runtime(root)
    runtime.start()
    httpd = make_server(runtime)
    thread = threading.Thread(target=httpd.serve_forever, name="seeker-http", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    if args.server_only:
        print(url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
            runtime.close()
        return
    _open_window(url, runtime, httpd)


def _open_window(url: str, runtime, httpd) -> None:
    import webview

    window = webview.create_window(
        "Seeker",
        url,
        width=1280,
        height=840,
        min_size=(960, 640),
        background_color="#1c1915",
        text_select=True,
    )
    quitting = {"value": False}

    def hide():
        if quitting["value"]:
            return True
        window.hide()
        return False

    def show() -> None:
        window.show()

    def quit_app() -> None:
        quitting["value"] = True
        runtime.close()
        httpd.shutdown()
        window.destroy()
        icon.stop()

    window.events.closing += hide
    icon = _tray(show, quit_app)
    try:
        webview.start(gui="edgechromium", private_mode=False)
    except Exception as exc:
        print("Não abri a janela.", exc)
        print("Abra no navegador:", url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            quit_app()
    finally:
        if not quitting["value"]:
            runtime.close()
            httpd.shutdown()


def _tray(show, quit_app):
    import pystray
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), "#1c1915")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), outline="#e0a23a", width=4)
    draw.ellipse((24, 24, 40, 40), fill="#e0a23a")
    menu = pystray.Menu(
        pystray.MenuItem("Abrir", lambda _icon, _item: show()),
        pystray.MenuItem("Sair", lambda _icon, _item: quit_app()),
    )
    icon = pystray.Icon("seeker", image, "Seeker", menu)
    icon.run_detached()
    return icon


if __name__ == "__main__":
    main()
