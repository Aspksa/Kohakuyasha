from __future__ import annotations

import threading
import webbrowser
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from . import autostart


def create_icon_image(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (16, 16, 22, 255))
    draw = ImageDraw.Draw(image)
    gold = (232, 190, 86, 255)
    white = (245, 241, 226, 255)
    dark = (16, 16, 22, 255)
    draw.ellipse((5, 5, size - 5, size - 5), outline=gold, width=3)
    draw.polygon([(18, 25), (22, 10), (31, 23)], fill=white, outline=gold)
    draw.polygon([(46, 25), (42, 10), (33, 23)], fill=white, outline=gold)
    draw.polygon([(18, 26), (32, 18), (46, 26), (42, 45), (32, 54), (22, 45)], fill=white)
    draw.polygon([(24, 34), (29, 32), (27, 38)], fill=dark)
    draw.polygon([(40, 34), (35, 32), (37, 38)], fill=dark)
    draw.polygon([(29, 43), (35, 43), (32, 47)], fill=gold)
    return image


class TrayController:
    def __init__(self, *, url: str, on_restart: Callable[[], None], on_shutdown: Callable[[], None], on_quick_test: Callable[[], None], project_root) -> None:
        self.url = url
        self.on_restart = on_restart
        self.on_shutdown = on_shutdown
        self.on_quick_test = on_quick_test
        self.project_root = project_root
        self.icon: pystray.Icon | None = None
        self._lock = threading.Lock()

    def set_url(self, url: str) -> None:
        with self._lock:
            self.url = url

    def _open(self, *_):
        with self._lock:
            url = self.url
        webbrowser.open(url)

    @staticmethod
    def _background(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _autostart_label(self, _item):
        return "✓ Автозапуск" if autostart.is_enabled() else "Автозапуск"

    def _toggle_autostart(self, *_):
        def work():
            try:
                if autostart.is_enabled():
                    autostart.disable()
                else:
                    autostart.enable(self.project_root)
            finally:
                if self.icon:
                    self.icon.update_menu()
        self._background(work)

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Открыть Kohakuyasha", self._open, default=True),
            pystray.MenuItem("Быстрый тест", lambda *_: self._background(self.on_quick_test)),
            pystray.MenuItem(self._autostart_label, self._toggle_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Перезапустить ядро", lambda *_: self._background(self.on_restart)),
            pystray.MenuItem("Выход", lambda *_: self._background(self.on_shutdown)),
        )
        self.icon = pystray.Icon("Kohakuyasha", create_icon_image(), "Kohakuyasha", menu)
        self.icon.run()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()
