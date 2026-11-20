#!/usr/bin/env python3
"""
Patrilog LOTS watcher: alerts on any lot change (status, surface, new/removed).
Uses a real headless browser because patrilog.com has bot protection.
Setup:  pip install playwright && playwright install chromium
Run:    python lots_watch.py      (TG_TOKEN / TG_CHAT env vars = Telegram alerts)
"""
import json, os, sys, urllib.parse, urllib.request
from pathlib import Path

SITE = "https://patrilog.com/"
API = "getLots.php"
STATE = Path(__file__).with_name("lots_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def notify(title, body):
    print("\a" + title + "\n" + body)
    tok, chat = os.getenv("TG_TOKEN", ""), os.getenv("TG_CHAT", "")
    if tok and chat:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n\n{body[:3500]}"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15)
        except Exception as e:
            print("Telegram failed:", e)


def find_items(data):
    """Biggest list of dicts found anywhere in the JSON."""
    best, stack = [], [data]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            if x and all(isinstance(i, dict) for i in x) and len(x) > len(best):
                best = x
            stack.extend(x)
        elif isinstance(x, dict):
            stack.extend(x.values())
    return best


def index(items):
    """Unique key per lot: 'num (shortid)' so lots with the same number in different projects never collide."""
    out = {}
    for n, it in enumerate(items):
        ident = str(it.get("id", n))[:8]
        num = it.get("num", it.get("numero", it.get("lot", "?")))
        out[f"{num} ({ident})"] = it
    return out


def brief(it):
    return ", ".join(f"{k}={v}" for k, v in list(it.items())[:6])


def compare(old, new):
    msgs = []
    for k in sorted(new.keys() - old.keys()):
        msgs.append(f"➕ New lot {k}: {brief(new[k])}")
    for k in sorted(old.keys() - new.keys()):
        msgs.append(f"➖ Removed lot {k}")
    for k in sorted(new.keys() & old.keys()):
        if new[k] != old[k]:
            fields = sorted(set(old[k]) | set(new[k]))
            ch = [f"{f}: {old[k].get(f)} → {new[k].get(f)}" for f in fields if old[k].get(f) != new[k].get(f)]
            msgs.append(f"✏️ Lot {k}: " + ", ".join(ch))
    return msgs


def fetch_lots():
    from playwright.sync_api import sync_playwright
    got = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = b.new_context(locale="fr-FR", viewport={"width": 1366, "height": 850}, user_agent=UA).new_page()

        def on_resp(r):
            if API in r.url and r.status == 200 and "body" not in got:
                try:
                    got["body"] = r.json()
                except Exception:
                    pass

        page.on("response", on_resp)
        page.goto(SITE, wait_until="networkidle", timeout=60000)
        if "body" not in got:  # click "Recherche" to trigger the lots request
            try:
                page.get_by_text("Recherche").first.click(timeout=8000)
            except Exception:
                pass
            for _ in range(20):
                if "body" in got:
                    break
                page.wait_for_timeout(1000)
        b.close()
    return got.get("body")


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def main():
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    try:
        data = fetch_lots()
    except Exception as e:
        data = None
        print("browser error:", e)
    items = find_items(data) if data else []
    if not items:
        fails = state.get("_fails", 0) + 1
        state["_fails"] = fails
        print(f"No lots data ({fails} in a row): blocked or API changed")
        if fails == 6:
            notify("⚠️ Patrilog lots watcher", "No lots data for 6 checks in a row (blocked or API changed).")
        save(state)
        return
    new = index(items)
    old = state.get("lots") if state.get("v") == 2 else None
    state["_fails"] = 0
    if old is None:
        print(f"Baseline saved: {len(new)} lots. Sample: {brief(items[0])}")
    else:
        msgs = compare(old, new)
        if msgs:
            print(f"CHANGE: {len(msgs)} lot change(s)")
            notify("🔔 Patrilog lots changed!", f"{len(msgs)} change(s)\n\n" + "\n".join(msgs[:25]))
        else:
            print(f"no change ({len(new)} lots)")
    state["lots"], state["v"] = new, 2
    save(state)


if __name__ == "__main__":
    main()
