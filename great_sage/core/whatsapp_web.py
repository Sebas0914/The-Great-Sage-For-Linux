"""Visible Firefox automation for WhatsApp Web on Linux.

Uses the locally installed geckodriver through its W3C WebDriver HTTP API,
so there is no extra Python dependency. It reuses Firefox's default profile
to retain the user's WhatsApp login and refuses to send unless one exact
contact match is visible and the opened chat header matches that contact.
"""

import configparser
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)
_LOCK = threading.RLock()
_SESSION = None


class WhatsAppError(RuntimeError):
    pass


class _WebDriver:
    ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

    def __init__(self, port, process, session_id):
        self.base = f"http://127.0.0.1:{port}"
        self.process = process
        self.session_id = session_id

    def request(self, path, payload=None, timeout=10):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = json.loads(response.read() or b"{}")
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise WhatsAppError(f"Firefox automation failed: {exc}") from exc
        if body.get("value") and isinstance(body["value"], dict):
            error = body["value"].get("error")
            if error:
                raise WhatsAppError(body["value"].get("message", error))
        return body.get("value")

    def command(self, path, payload=None, timeout=10):
        return self.request(f"/session/{self.session_id}{path}", payload, timeout)

    def script(self, source, args=None):
        return self.command("/execute/sync", {"script": source, "args": args or []})

    def element(self, css):
        result = self.command("/element", {"using": "css selector", "value": css})
        return (result or {}).get(self.ELEMENT_KEY)

    def keys(self, element_id, text):
        self.command(f"/element/{element_id}/value",
                     {"text": text, "value": list(text)}, timeout=20)


def _firefox_profile():
    candidates = [
        Path.home() / ".mozilla/firefox/profiles.ini",
        Path.home() / "snap/firefox/common/.mozilla/firefox/profiles.ini",
    ]
    for ini in candidates:
        if not ini.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        profiles = []
        for section in parser.sections():
            if not section.startswith("Profile"):
                continue
            raw = parser.get(section, "Path", fallback="")
            if not raw:
                continue
            path = Path(raw)
            if parser.getboolean(section, "IsRelative", fallback=True):
                path = ini.parent / path
            if path.is_dir():
                profiles.append((parser.getboolean(section, "Default", fallback=False), path))
        if profiles:
            return next((path for default, path in profiles if default), profiles[0][1])
    raise WhatsAppError("Firefox has no existing profile to reuse. Open Firefox once, then retry.")


def _firefox_is_running():
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").lower()
        except OSError:
            continue
        if b"firefox" in cmd and b"geckodriver" not in cmd:
            return True
    return False


def _new_session():
    global _SESSION
    if _SESSION is not None and _SESSION.process.poll() is None:
        return _SESSION
    if _firefox_is_running():
        raise WhatsAppError(
            "Firefox is already running without Great Sage's WebDriver session. "
            "I cannot inspect or send through that live window from this process, "
            "so no message was sent. WhatsApp can be opened in a tab in the "
            "existing Firefox; message sending will work when Firefox is started "
            "in Great Sage's automation session."
        )
    driver = shutil.which("geckodriver")
    if not driver:
        raise WhatsAppError("Firefox automation needs geckodriver, which is not installed.")
    firefox = shutil.which("firefox")
    if not firefox:
        raise WhatsAppError("Firefox is not installed.")
    profile = _firefox_profile()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [driver, "--host", "127.0.0.1", "--port", str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WhatsAppError("geckodriver stopped before Firefox could start.")
        try:
            urllib.request.urlopen(base + "/status", timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.15)
    else:
        process.terminate()
        raise WhatsAppError("geckodriver did not become ready in time.")

    req = urllib.request.Request(
        base + "/session",
        data=json.dumps({
            "capabilities": {"alwaysMatch": {
                "browserName": "firefox",
                "moz:firefoxOptions": {
                    "binary": firefox,
                    "args": ["--profile", str(profile), "--new-window"],
                },
            }},
        }).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = json.loads(response.read())
        value = body.get("value", {})
        session_id = value.get("sessionId") or body.get("sessionId")
        if not session_id:
            raise WhatsAppError("Firefox did not provide a WebDriver session.")
    except Exception as exc:
        process.terminate()
        if isinstance(exc, WhatsAppError):
            raise
        raise WhatsAppError(f"Could not start Firefox with its saved profile: {exc}") from exc
    _SESSION = _WebDriver(port, process, session_id)
    return _SESSION


def _wait_script(driver, source, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = driver.script(source)
        if value:
            return value
        time.sleep(0.25)
    return None


def _visible_firefox_send(contact: str, message: str) -> str:
    """Use OCR-verified keyboard/mouse control when Firefox is already open.

    Firefox does not let WebDriver attach to an ordinary running session.
    In that case, keep the user's logged-in profile and operate its visible
    WhatsApp tab; never launch a second profile or send without confirming
    both the contact header and the draft text on screen.
    """
    wmctrl, xdotool = shutil.which("wmctrl"), shutil.which("xdotool")
    spectacle, tesseract = shutil.which("spectacle"), shutil.which("tesseract")
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not all((wmctrl, xdotool, spectacle, tesseract, firefox)):
        raise WhatsAppError(
            "Firefox is already running, but visible desktop control is missing "
            "(wmctrl, xdotool, Spectacle, or Tesseract). No message was sent."
        )

    def windows():
        out = subprocess.run([wmctrl, "-lGx"], capture_output=True,
                             text=True, timeout=4, check=False).stdout
        found = []
        for line in out.splitlines():
            cols = line.split(None, 7)
            if len(cols) >= 8 and "firefox" in cols[6].casefold():
                try:
                    found.append((cols[0], *(int(v) for v in cols[2:6]), cols[7]))
                except ValueError:
                    pass
        return found

    def capture(window_id):
        geometry = next((w[1:5] for w in windows() if w[0] == window_id), (0, 0, 0, 0))
        fd, path = tempfile.mkstemp(prefix="great-sage-wa-", suffix=".png")
        os.close(fd)
        try:
            shot = subprocess.run(
                [spectacle, "--background", "--nonotify", "--activewindow",
                 "--output", path], capture_output=True, text=True,
                timeout=12, check=False,
            )
            if shot.returncode != 0 or not os.path.getsize(path):
                raise WhatsAppError("Could not capture Firefox; no message was sent.")
            ocr = subprocess.run([tesseract, path, "stdout", "tsv", "-l", "eng"],
                                 capture_output=True, text=True, timeout=10,
                                 check=False)
            lines = {}
            for raw in ocr.stdout.splitlines()[1:]:
                col = raw.split("\t")
                if len(col) < 12 or not col[11].strip():
                    continue
                key = tuple(col[1:5])
                row = lines.setdefault(key, {"text": [], "l": None, "t": None,
                                              "r": 0, "b": 0})
                row["text"].append(col[11].strip())
                left, top = int(col[6]), int(col[7])
                row["l"] = left if row["l"] is None else min(row["l"], left)
                row["t"] = top if row["t"] is None else min(row["t"], top)
                row["r"] = max(row["r"], left + int(col[8]))
                row["b"] = max(row["b"], top + int(col[9]))
            result = []
            for row in lines.values():
                row["text"] = " ".join(row["text"])
                row["x"] = geometry[0] + (row["l"] + row["r"]) // 2
                row["y"] = geometry[1] + (row["t"] + row["b"]) // 2
                result.append(row)
            return result, geometry
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def norm(value):
        plain = unicodedata.normalize("NFKD", value.casefold())
        plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
        return " ".join("".join(ch if ch.isalnum() else " " for ch in plain).split())

    found = windows()
    if not found:
        subprocess.Popen([firefox, "--new-tab", "https://web.whatsapp.com/"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not found:
            time.sleep(0.25)
            found = windows()
    if not found:
        raise WhatsAppError("Could not bring the existing Firefox window forward.")
    window_id, x, y, width, height, title = found[0]
    subprocess.run([wmctrl, "-ia", window_id], capture_output=True,
                   timeout=4, check=False)
    if "whatsapp" not in title.casefold():
        subprocess.Popen([firefox, "--new-tab", "https://web.whatsapp.com/"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 35
    lines = []
    while time.monotonic() < deadline:
        time.sleep(0.6)
        lines, _ = capture(window_id)
        page = " ".join(norm(row["text"]) for row in lines)
        if any(x in page for x in ("search", "buscar", "chats")):
            break
        if "use whatsapp on your phone" in page or "scan the qr" in page:
            raise WhatsAppError("WhatsApp Web is not logged in in Firefox; no message was sent.")
    else:
        raise WhatsAppError("WhatsApp did not finish loading in Firefox; no message was sent.")

    search = next((row for row in lines
                   if row["x"] < x + width * 0.48 and row["y"] < y + 270
                   and any(word in norm(row["text"]) for word in ("search", "buscar"))), None)
    if not search:
        raise WhatsAppError("Could not locate WhatsApp's visible contact search; no message was sent.")
    subprocess.run([xdotool, "mousemove", str(search["x"]), str(search["y"]), "click", "1"],
                   check=True, timeout=4)
    subprocess.run([xdotool, "key", "ctrl+a"], check=True, timeout=4)
    subprocess.run([xdotool, "type", "--clearmodifiers", "--delay", "12", contact],
                   check=True, timeout=8)
    deadline = time.monotonic() + 15
    exact = None
    while time.monotonic() < deadline:
        time.sleep(0.4)
        lines, _ = capture(window_id)
        contact_text = norm(contact)
        exact = next((row for row in lines
                      if row["x"] < x + width * 0.5 and row["y"] > y + 100
                      and (norm(row["text"]) == contact_text
                           or norm(row["text"]).startswith(contact_text + " "))),
                     None)
        if exact:
            break
    if not exact:
        raise WhatsAppError(
            f"WhatsApp did not show one visible exact match for {contact!r}; no message was sent."
        )
    subprocess.run([xdotool, "mousemove", str(exact["x"]), str(exact["y"]), "click", "1"],
                   check=True, timeout=4)
    time.sleep(0.8)
    lines, _ = capture(window_id)
    header = next((row for row in lines
                   if row["x"] > x + width * 0.48 and row["y"] < y + 220
                   and (norm(row["text"]) == contact_text
                        or norm(row["text"]).startswith(contact_text + " "))),
                  None)
    if not header:
        raise WhatsAppError("The open chat header did not match the exact contact; no message was sent.")

    compose_x = x + int(width * 0.68)
    compose_y = y + height - 58
    subprocess.run([xdotool, "mousemove", str(compose_x), str(compose_y), "click", "1"],
                   check=True, timeout=4)
    subprocess.run([xdotool, "type", "--clearmodifiers", "--delay", "12", message],
                   check=True, timeout=10)
    time.sleep(0.35)
    lines, _ = capture(window_id)
    expected = norm(message)
    draft = next((row for row in lines if row["y"] > y + height * 0.65
                  and expected and expected in norm(row["text"])), None)
    if not draft:
        raise WhatsAppError("I could not verify the message draft on screen; it was not sent.")
    subprocess.run([xdotool, "key", "Return"], check=True, timeout=4)
    time.sleep(0.8)
    lines, _ = capture(window_id)
    sent = next((row for row in lines if row["x"] > x + width * 0.45
                 and expected and expected in norm(row["text"])), None)
    if not sent:
        raise WhatsAppError("WhatsApp did not show the sent message in the verified chat.")
    return f"Sent WhatsApp message to {contact}."


def send_message(contact: str, message: str) -> str:
    """Send to one exact, verified WhatsApp Web contact in the visible Firefox."""
    contact = " ".join((contact or "").split()).strip()
    message = (message or "").strip()
    if not contact or not message:
        raise WhatsAppError("WhatsApp needs both a contact name and message text.")
    if len(message) > 4000:
        raise WhatsAppError("The WhatsApp message is too long (maximum 4000 characters).")

    with _LOCK:
        if _firefox_is_running():
            return _visible_firefox_send(contact, message)
        driver = _new_session()
        driver.command("/url", {"url": "https://web.whatsapp.com/"}, timeout=25)
        logged_in = _wait_script(
            driver,
            "return !!document.querySelector('#pane-side, [data-testid=chat-list]');",
            timeout=45,
        )
        if not logged_in:
            raise WhatsAppError(
                "WhatsApp Web is not logged in in Firefox. Sign in there and repeat the request."
            )

        search_id = _wait_script(driver, """
          const side = document.querySelector('#side') || document.querySelector('#pane-side');
          const items = [...(side || document).querySelectorAll('[contenteditable=true][role=textbox], input')];
          const el = items.find(x => /search|buscar|contact|contacto/i.test(
            (x.getAttribute('aria-label') || '') + ' ' + (x.getAttribute('placeholder') || '')
          ));
          if (!el) return null;
          el.setAttribute('data-great-sage-search', '1'); return true;
        """, timeout=20)
        if not search_id:
            raise WhatsAppError("WhatsApp Web did not expose its contact search box.")
        search_id = driver.element('[data-great-sage-search="1"]')
        if not search_id:
            raise WhatsAppError("Could not focus WhatsApp's contact search box.")
        driver.command(f"/element/{search_id}/click", {})
        driver.keys(search_id, "\ue009a")
        driver.keys(search_id, contact)

        escaped = json.dumps(contact, ensure_ascii=False)
        result = _wait_script(driver, f"""
          const q = {escaped}.toLocaleLowerCase();
          const pane = document.querySelector('#pane-side');
          const cells = [...(pane || document).querySelectorAll('[role=gridcell]')];
          const rows = cells.length ? cells : [...(pane || document).querySelectorAll('[role=row]')];
          const matches = rows.filter(row => row.innerText.split('\\n').some(
            line => line.trim().toLocaleLowerCase() === q
          ));
          if (matches.length === 0) return null;
          if (matches.length !== 1) return {{count: matches.length}};
          matches[0].setAttribute('data-great-sage-contact', '1'); return {{count: 1}};
        """, timeout=15)
        if not result or result.get("count") != 1:
            count = 0 if not result else result.get("count", 0)
            raise WhatsAppError(
                f"WhatsApp found {count} exact matches for {contact!r}; no message was sent."
            )
        contact_id = driver.element('[data-great-sage-contact="1"]')
        if not contact_id:
            raise WhatsAppError("The exact contact result disappeared before it could be opened.")
        driver.command(f"/element/{contact_id}/click", {})

        header = _wait_script(driver, """
          const main = document.querySelector('#main');
          if (!main) return null;
          const title = main.querySelector('header span[title]');
          return title ? title.getAttribute('title') : null;
        """, timeout=10)
        if " ".join(str(header or "").split()).casefold() != contact.casefold():
            raise WhatsAppError(
                f"The opened WhatsApp chat was {header!r}, not {contact!r}; no message was sent."
            )

        editor_ready = _wait_script(driver, """
          const el = document.querySelector('#main footer [contenteditable=true][role=textbox]')
            || document.querySelector('#main footer [contenteditable=true]');
          if (!el) return false;
          el.setAttribute('data-great-sage-composer', '1'); return true;
        """, timeout=10)
        if not editor_ready:
            raise WhatsAppError("WhatsApp did not show a message composer; no message was sent.")
        editor_id = driver.element('[data-great-sage-composer="1"]')
        if not editor_id:
            raise WhatsAppError("Could not focus the WhatsApp message composer.")
        driver.command(f"/element/{editor_id}/click", {})
        driver.keys(editor_id, message)
        driver.keys(editor_id, "\ue007")

        sent = _wait_script(driver, f"""
          const q = {json.dumps(message, ensure_ascii=False)}.trim();
          return [...document.querySelectorAll('#main .message-out')].some(
            node => node.innerText.trim() === q
          );
        """, timeout=8)
        if not sent:
            raise WhatsAppError("WhatsApp did not confirm the message in the verified chat.")
        return f"Sent WhatsApp message to {contact}."
