#!/usr/bin/env python3
"""Usage:
  python yasno-outage-bot.py             # first run: asks for Telegram + a point; later: checks outages
  python yasno-outage-bot.py --add       # add another point
  python yasno-outage-bot.py --telegram  # re-enter Telegram token / chat ID
  python yasno-outage-bot.py --list      # show saved points
"""
import getpass, hashlib, json, os, sys, requests
from pathlib import Path

# Kyiv (DTEK). For another city, change these two numbers
# (they are in the planned-outages URL on that city's Yasno page).
REGION = 25
DSO = 902
URL = ("https://app.yasno.ua/api/blackout-service/public/shutdowns/"
       f"regions/{REGION}/dsos/{DSO}/planned-outages")

DIR = Path(__file__).parent
CONFIG = DIR / "config.json"
HEADERS = {"User-Agent": "outage-bot/1.0"}


# ---------- config ----------
def load_config():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    if isinstance(cfg, list):
        cfg = {"targets": cfg}
    cfg.setdefault("targets", [])
    return cfg


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    os.chmod(CONFIG, 0o600)  # the token is inside: readable only by you


# ---------- http ----------
def fetch_outages():
    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def telegram_send(token, chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=20,
    ).raise_for_status()


# ---------- interactive setup ----------
def ask_number(prompt):
    while True:
        v = input(prompt).strip()
        if v.isdigit():
            return v
        print("Please enter a number.")


def setup_telegram(cfg):
    print("\n--- Telegram ---")
    token = getpass.getpass("Bot token (input is hidden): ").strip()
    chat_id = input("Chat ID (groups are negative, e.g. -5396546821): ").strip()
    try:
        telegram_send(token, chat_id, "✅ Outage bot connected")
    except requests.RequestException as e:
        sys.exit(f"Telegram test failed, nothing saved: {e}")
    cfg["telegram"] = {"token": token, "chat_id": chat_id}
    save_config(cfg)
    print("Telegram OK, test message sent.")


def setup_point(cfg):
    print("\n--- New point ---")
    name = input("Name for this point (e.g. Home): ").strip() or "Home"
    try:
        known = fetch_outages()
    except requests.RequestException as e:
        known = None
        print(f"(could not verify the group online: {e})")

    while True:
        key = f"{ask_number('Group (e.g. 23): ')}.{ask_number('Subgroup (e.g. 1): ')}"
        if known is None or key in known:
            break
        print(f"Group {key} does not exist in the schedule. Try again.")

    cfg["targets"].append({"name": name, "group": key})
    save_config(cfg)
    print(f"Saved: {name} (group {key})")


# ---------- outage check ----------
def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def outages(day):
    merged = []
    for s in day.get("slots", []):
        if s["type"] != "Definite":
            continue
        if merged and merged[-1][1] == s["start"]:
            merged[-1][1] = s["end"]
        else:
            merged.append([s["start"], s["end"]])
    return [f"{hhmm(a)}–{hhmm(b)}" for a, b in merged]


def check(t, data, token, chat_id):
    group = data.get(t["group"])
    if not group:
        print(f"{t['name']}: group {t['group']} not found", file=sys.stderr)
        return

    uid = hashlib.sha1(f"{t['name']}|{t['group']}".encode()).hexdigest()[:8]
    state = DIR / f"hash_{uid}.txt"
    relevant = {k: group.get(k, {}) for k in ("today", "tomorrow")}
    cur = hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()
    if state.exists() and state.read_text().strip() == cur:
        return  # nothing changed

    lines = [f"💡 <b>{t['name']}</b> (group {t['group']})"]
    for key, lbl in (("today", "Today"), ("tomorrow", "Tomorrow")):
        day = relevant[key]
        date = day.get("date", "")[:10]
        if day.get("status") == "WaitingForSchedule":
            lines.append(f"<b>{lbl} {date}:</b> schedule not published yet")
            continue
        iv = outages(day)
        lines.append(f"<b>{lbl} {date}:</b> " +
                     (", ".join(f"🔴 {i}" for i in iv) if iv else "🟢 no outages"))

    telegram_send(token, chat_id, "\n".join(lines))
    state.write_text(cur)


# ---------- main ----------
def main():
    cfg = load_config()

    if "--telegram" in sys.argv:
        return setup_telegram(cfg)
    if "--add" in sys.argv:
        return setup_point(cfg)
    if "--list" in sys.argv:
        for t in cfg["targets"]:
            print(f"{t['name']}: group {t['group']}")
        return
    if "--remove" in sys.argv:
        for i, t in enumerate(cfg["targets"], 1):
            print(f"  {i}. {t['name']} (group {t['group']})")
        n = input("Number to remove: ").strip()
        if n.isdigit() and 1 <= int(n) <= len(cfg["targets"]):
            removed = cfg["targets"].pop(int(n) - 1)
            save_config(cfg)
            print("Removed:", removed["name"])
        return

    interactive = sys.stdin.isatty()
    if not cfg.get("telegram"):
        if not interactive:
            sys.exit("Not configured. Run once in a terminal: python yasno-outage-bot.py")
        setup_telegram(cfg)
    if not cfg["targets"]:
        if not interactive:
            sys.exit("No point saved. Run once in a terminal: python yasno-outage-bot.py")
        setup_point(cfg)

    token, chat_id = cfg["telegram"]["token"], cfg["telegram"]["chat_id"]
    try:
        data = fetch_outages()
    except Exception as e:
        sys.exit(f"Could not fetch the schedule: {e}")
    for t in cfg["targets"]:
        try:
            check(t, data, token, chat_id)
        except Exception as e:
            print(f"{t['name']}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()