#!/usr/bin/env python3
"""
Patrilog Watch: detects ANY change on https://patrilog.com/
Zero dependencies (Python 3.8+).  Run:  python patrilog_watch.py
"""
import difflib, hashlib, html, json, os, re, subprocess, sys, time
import urllib.request, urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

# ───────── CONFIG ─────────
URL = "https://patrilog.com/"
EXTRA_URLS = []
INTERVAL = 60
TIMEOUT = 25
STATE = Path(__file__).with_name("patrilog_state.json")
LOG = Path(__file__).with_name("patrilog_changes.log")
TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT = os.getenv("TG_CHAT", "")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


# ───────── FETCH + NORMALIZE ─────────
def clean_url(u):
    return re.sub(r"[?&](v|ver|_|t|ts|cb|timestamp)=[^&#]*", "", u)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.scripts, self._skip = [], [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip = True
            if tag == "script" and a.get("src"):
                self.scripts.append(clean_url(a["src"]))
        if tag == "link" and a.get("href"):
            self.scripts.append(clean_url(a["href"]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, d):
        if not self._skip and d.strip():
            self.out.append(re.sub(r"\s+", " ", html.unescape(d)).strip())


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def snapshot(url):
    raw = fetch(url)
    if "<html" in raw.lower() or "<body" in raw.lower():
        p = TextExtractor()
        p.feed(raw)
        lines = ["[TEXT] " + t for t in p.out] + ["[ASSET] " + s for s in sorted(set(p.scripts))]
    else:
        try:
            raw = json.dumps(json.loads(raw), indent=1, sort_keys=True, ensure_ascii=False)
        except Exception:
            pass
        lines = raw.splitlines()
    return lines


def digest(lines):
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# ───────── ALERTS ─────────
def notify(title, body):
    print("\a", end="")
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(body[:200])} with title {json.dumps(title)}'])
        elif sys.platform.startswith("linux"):
            subprocess.run(["notify-send", title, body[:200]])
        elif sys.platform == "win32":
            import winsound
            for _ in range(3):
                winsound.Beep(1200, 250)
    except Exception:
        pass
    if TG_TOKEN and TG_CHAT:
        try:
            data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": f"{title}\n\n{body[:3500]}"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data, timeout=15)
        except Exception as e:
            print("Telegram failed:", e)


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ───────── MAIN LOOP ─────────
def main():
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    urls = [URL] + EXTRA_URLS
    fails = 0
    log(f"Watching {len(urls)} URL(s) every {INTERVAL}s. Ctrl+C to stop.")
    while True:
        for u in urls:
            try:
                lines = snapshot(u)
                fails = 0
            except Exception as e:
                fails += 1
                log(f"fetch error ({fails}) {u}: {e}")
                if fails == 10:
                    notify("Patrilog Watch: site unreachable", f"{u} failed 10 times in a row. {e}")
                continue
            h, old = digest(lines), state.get(u)
            if old is None:
                log(f"Baseline saved for {u} ({len(lines)} lines)")
            elif old["hash"] != h:
                diff = [d for d in difflib.unified_diff(old["lines"], lines, "before", "after", lineterm="", n=0)
                        if d[:1] in "+-" and d[:3] not in ("+++", "---")]
                summary = "\n".join(diff[:25]) or "(content changed)"
                log(f"CHANGE DETECTED on {u}\n{summary}")
                notify("🔔 Patrilog changed!", f"{u}\n\n{summary}")
            else:
                print(f"[{datetime.now():%H:%M:%S}] no change", end="\r")
            state[u] = {"hash": h, "lines": lines}
            STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        if "--once" in sys.argv:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
