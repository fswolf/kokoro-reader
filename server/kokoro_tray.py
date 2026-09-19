#!/usr/bin/env python3
"""System-tray front end for the Kokoro Reader TTS server.

Starts/stops the server as a child process and shows its state in the tray.
Quitting the tray stops the server.

Needs: python3-gobject, gtk3, and an AppIndicator library
(libayatana-appindicator-gtk3, or the older libappindicator-gtk3).
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

# Ayatana is the maintained fork; fall back to the old name.
AppIndicator = None
for _name in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(_name, "0.1")
        AppIndicator = getattr(__import__("gi.repository", fromlist=[_name]), _name)
        break
    except (ValueError, ImportError):
        continue
if AppIndicator is None:
    sys.exit(
        "No AppIndicator library found.\n"
        "  sudo dnf install python3-gobject libayatana-appindicator-gtk3"
    )

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "start_server.sh")
PORT = int(os.environ.get("KOKORO_PORT", "8899"))
BASE = "http://127.0.0.1:%d" % PORT
VOICE = os.environ.get("KOKORO_VOICE", "am_adam")

ICON_ON = "audio-speakers"
ICON_OFF = "audio-volume-muted"
POLL_SECONDS = 3


def get_json(path, timeout=0.6):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


class Tray:
    def __init__(self):
        self.proc = None            # server we started ourselves
        self.up = False             # server reachable (ours or not)
        self.foreign = False        # something else is on the port

        self.ind = AppIndicator.Indicator.new(
            "kokoro-reader", ICON_OFF,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title("Kokoro Reader")

        self.menu = Gtk.Menu()
        self.item_status = Gtk.MenuItem(label="Checking…")
        self.item_status.set_sensitive(False)
        self.item_toggle = Gtk.MenuItem(label="Start server")
        self.item_toggle.connect("activate", self.on_toggle)
        self.item_restart = Gtk.MenuItem(label="Restart server")
        self.item_restart.connect("activate", self.on_restart)
        self.item_test = Gtk.MenuItem(label="Test voice")
        self.item_test.connect("activate", self.on_test)
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self.on_quit)

        for w in (self.item_status, Gtk.SeparatorMenuItem(), self.item_toggle,
                  self.item_restart, self.item_test, Gtk.SeparatorMenuItem(), item_quit):
            self.menu.append(w)
        self.menu.show_all()
        self.ind.set_menu(self.menu)

        self.refresh()
        GLib.timeout_add_seconds(POLL_SECONDS, self.refresh)

    # ---------- server control ----------
    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        if not os.access(LAUNCHER, os.X_OK):
            self.notify("start_server.sh is not executable")
            return
        # start_new_session so we can signal the whole process group
        self.proc = subprocess.Popen(
            [LAUNCHER],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            self.proc = None
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self.proc = None

    # ---------- ui ----------
    def refresh(self):
        health = get_json("/health")
        self.up = health is not None
        mine = bool(self.proc and self.proc.poll() is None)
        self.foreign = self.up and not mine

        self.ind.set_icon_full(ICON_ON if self.up else ICON_OFF, "Kokoro Reader")

        if self.foreign:
            label = "Running on :%d (not started here)" % PORT
        elif self.up:
            loaded = "model loaded" if health.get("loaded") else "loading model…"
            label = "Running on :%d — %s" % (PORT, loaded)
        elif mine:
            label = "Starting…"
        else:
            label = "Stopped"
        self.item_status.set_label(label)

        self.item_toggle.set_label("Stop server" if mine else "Start server")
        self.item_toggle.set_sensitive(not self.foreign)
        self.item_restart.set_sensitive(mine)
        self.item_test.set_sensitive(self.up)
        return True  # keep the timer

    def notify(self, text):
        subprocess.Popen(["notify-send", "Kokoro Reader", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------- menu handlers ----------
    def on_toggle(self, _w):
        if self.proc and self.proc.poll() is None:
            self.stop()
        else:
            self.start()
        self.refresh()

    def on_restart(self, _w):
        self.stop()
        self.start()
        self.refresh()

    def on_test(self, _w):
        threading.Thread(target=self._speak_test, daemon=True).start()

    def _speak_test(self):
        body = json.dumps({"text": "Kokoro reader is running.", "voice": VOICE}).encode()
        req = urllib.request.Request(
            BASE + "/tts", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                wav = r.read()
        except (urllib.error.URLError, OSError) as e:
            GLib.idle_add(self.notify, "Test failed: %s" % e)
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            path = f.name
        for player in (["pw-play", path], ["paplay", path], ["aplay", "-q", path]):
            try:
                subprocess.run(player, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        os.unlink(path)

    def on_quit(self, _w):
        self.stop()
        Gtk.main_quit()


def main():
    tray = Tray()
    # Start the server on launch unless told not to, or unless one is already up.
    if os.environ.get("KOKORO_TRAY_AUTOSTART", "1") != "0" and not tray.up:
        tray.start()
        tray.refresh()

    signal.signal(signal.SIGINT, lambda *_: tray.on_quit(None))
    signal.signal(signal.SIGTERM, lambda *_: tray.on_quit(None))
    Gtk.main()
    tray.stop()


if __name__ == "__main__":
    main()
