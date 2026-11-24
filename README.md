# Yasno Outage Bot

Telegram alerts for **planned power outages in Kyiv**. The script checks the Yasno schedule for your queue (group and subgroup), and sends a message to a Telegram chat only when the schedule changes.

- Data source: Yasno planned-outages API (Kyiv, DTEK)
- Notifications: Telegram bot
- Runs from cron, stays silent when nothing changed
- Only standard Python plus `requests`

> **Scope:** the script is set up for **Kyiv only** (`REGION = 25`, `DSO = 902` in the script). It covers **planned** schedules. Emergency outages (accidents, attack damage) are not part of this data, so the bot will not catch them.

## How it works

Yasno groups every address into a queue such as `23.1` (group `23`, subgroup `1`). The API returns schedules per queue, not per address, so you only need to find your queue once.

On every run the script fetches today's and tomorrow's schedule, computes a fingerprint (hash) of it, and compares it with the one saved last time. If it differs, you get a Telegram message. Otherwise nothing is sent.

## Requirements

- Python 3.9 or newer
- A Telegram bot token and a chat ID (see below)
- Your group and subgroup (see below)

## Install

```bash
git clone https://github.com/avidei/yasno-outage-bot.git
cd yasno-outage-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Create a Telegram bot and get the chat ID

1. In Telegram open **@BotFather**, send `/newbot`, choose a display name and a username ending in `bot`. BotFather replies with the **token** (looks like `123456789:AA...`). Keep it secret.
2. Send any message to your new bot (for a private chat), or add the bot to a group and send a message there that the bot can see, such as `/start@your_bot_username`.
3. Open this URL in a browser, with your real token:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

4. Find the `chat` object in the response:

   ```json
   "chat": {"id": -1001234567890, "title": "My group", "type": "supergroup"}
   ```

   The number, including the minus sign, is your **chat ID**. Groups have negative IDs.

If `getUpdates` returns an empty `result`, send another message to the bot or group and reload.

## 2. Find your group and subgroup

The Yasno page shows your outage hours but **does not display the queue number**. There are four ways to get it.

### Option A: DevTools (exact)

1. Open <https://static.yasno.ua/kyiv/outages> in Chrome.
2. Press **F12** (Cmd+Option+I on Mac), open the **Network** tab and choose the **Fetch/XHR** filter.
3. On the page, enter your **street** and **building number**.
4. In the request list, click the request named **`group?regionId=25&streetId=...`** and open its **Response** tab. You will see:

   ```json
   {"group":23,"subgroup":1}
   ```

   Group is `23`, subgroup is `1`, so your queue is **`23.1`**.

### Option B: DTEK Kyiv website

DTEK Kyiv's shutdowns page (<https://www.dtek-kem.com.ua/ua/shutdowns>) can show the queue for an address. Enter your street and building there.

### Option C: match the schedule

If you do not want to open DevTools, compare the outage hours that Yasno shows for your address with the hours of every queue. Run this and look for the line that matches your address's hours:

```bash
python3 - <<'EOF'
import requests
URL = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages"
for g, v in requests.get(URL, timeout=20).json().items():
    if not isinstance(v, dict):
        continue
    iv = []
    for s in v.get("today", {}).get("slots", []):
        if s["type"] != "Definite":
            continue
        if iv and iv[-1][1] == s["start"]:
            iv[-1][1] = s["end"]
        else:
            iv.append([s["start"], s["end"]])
    print(g, [f"{a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d}" for a, b in iv])
EOF
```

Several queues can have similar hours on a given day, so use Option A, B or D if the result is not unique.

### Option D: look it up from the terminal with a street index

Use this if you prefer the terminal to DevTools. The helper script `fetch_yasno_groups.py` collects the ID of every Kyiv street, and then you ask the Yasno API for your building and group with `curl`.

1. Put `fetch_yasno_groups.py` in the project root, next to `yasno-outage-bot.py`, and run it:

   ```bash
   python fetch_yasno_groups.py
   ```

   It searches the API by street-name prefixes and saves every street ID to `kyiv_streets.json`. This takes about an hour or two. The file is reused on later runs, so you only do this once.

2. **Stop the script once `kyiv_streets.json` exists** (press Ctrl+C when it prints `Total unique streets: ...`). If you let it keep running, it moves on to every building in the city, requests the group for each one and writes `kyiv_yasno_groups.csv`. That takes far longer and sends a very large number of requests to Yasno's API, and you do not need it to find your own group.

3. Find your **street ID** in the file. Use part of the name, with the same capitalization as in the file (names start with a type such as `вул.` or `пров.`):

   ```bash
   grep Хреща kyiv_streets.json
   ```

   ```text
     "561": "вул. Набережно-Хрещатицька",
     "911": "вул. Хрещатик",
   ```

   The number is the street ID. For `вул. Хрещатик` it is `911`.

4. Find the **building ID** for your street and building number (`query` is the building number):

   ```bash
   curl -s "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/houses?regionId=25&dsoId=902&streetId=911&query=34"
   ```

   ```json
   [{"id":41301,"value":"34"}]
   ```

   If several buildings come back (for example `34`, `34а`, `340`), pick the one whose `value` matches yours and use its `id`.

5. Ask for the **group** with the street ID and building ID:

   ```bash
   curl -s "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/group?regionId=25&dsoId=902&streetId=911&houseId=41301"
   ```

   ```json
   {"group":23,"subgroup":1}
   ```

   Group is `23`, subgroup is `1`, so your queue is **`23.1`**.

6. Give the group and subgroup to the main script. On the first run, enter `23` and `1` at the **Group** and **Subgroup** prompts (if the script asks for a street first, press Enter to skip it). To add a point later, use `python yasno-outage-bot.py --add`.

Replace `911` and `41301` in the commands above with your own IDs.

**Shortcut if you only need one street:** you can skip the full street index and ask the API for the street ID directly. This is the same request the helper script makes for each prefix:

```bash
curl -sG "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/streets" \
  --data-urlencode "regionId=25" --data-urlencode "dsoId=902" --data-urlencode "query=Хрещатик"
```

Then continue from step 4.

## 3. First run

Run the script once by hand in a terminal. It asks for everything and saves it to `config.json`:

```text
$ python yasno-outage-bot.py

--- Telegram ---
Bot token (input is hidden):
Chat ID (groups are negative, e.g. -5396546821): -1001234567890
Telegram OK, test message sent.

--- New point ---
Name for this point (e.g. Home): Home
Group (e.g. 23): 23
Subgroup (e.g. 1): 1
Saved: Home (group 23.1)
```

- The token is hidden as you type or paste it.
- A test message is sent to Telegram first. Nothing is saved if it fails.
- The group is checked against the live schedule. If it does not exist, you are asked again.
- After setup the script checks the outages right away and sends the current schedule.

### Other commands

| Command | What it does |
| --- | --- |
| `python yasno-outage-bot.py` | Check outages (first run: asks for setup) |
| `python yasno-outage-bot.py --add` | Add another point (name, group, subgroup) |
| `python yasno-outage-bot.py --list` | Show saved points |
| `python yasno-outage-bot.py --remove` | Remove a saved point (shows a numbered list and asks which one) |
| `python yasno-outage-bot.py --telegram` | Re-enter the bot token and chat ID |

You can add several points, for example `Home` and `Parents`. Each one sends its own message, labelled with its name, when its schedule changes. To remove a point, run `--remove` and enter its number. To change a point's name or group, edit the `targets` list in `config.json`, or remove the point and add it again.

## 4. Run it every 15 minutes with cron (Linux)

Run the first-time setup by hand first, because cron has no terminal and cannot ask questions. Then:

1. Check the paths (use your own):

   ```bash
   cd /opt/yasno-outage-bot
   ls .venv/bin/python yasno-outage-bot.py config.json
   ```

2. Test one run exactly as cron will run it:

   ```bash
   cd /opt/yasno-outage-bot && .venv/bin/python yasno-outage-bot.py
   ```

3. Open the crontab:

   ```bash
   crontab -e
   ```

4. Add this line (adjust the folder):

   ```cron
   */15 * * * * cd /opt/yasno-outage-bot && .venv/bin/python yasno-outage-bot.py >> bot.log 2>&1
   ```

   - `*/15 * * * *` means every 15 minutes.
   - `cd ...` matters: the script keeps `config.json` and the hash files next to itself.
   - `>> bot.log 2>&1` writes any errors to `bot.log`.

5. Check that it is installed and running:

   ```bash
   crontab -l
   tail -f /opt/yasno-outage-bot/bot.log
   ```

The log stays empty when everything works. You only get a Telegram message when the schedule changes. The schedule for tomorrow is usually published in the evening, so expect a message then.

## Files

| File | Purpose |
| --- | --- |
| `yasno-outage-bot.py` | The script |
| `config.json` | Your token, chat ID and points (created on first run) |
| `hash_*.txt` | Fingerprint of the last sent schedule, one per point (created automatically) |
| `requirements.txt` | Python dependencies |
| `fetch_yasno_groups.py` | Optional helper for Option D: collects Kyiv street IDs |
| `kyiv_streets.json` | Street IDs, created by the helper script |
| `kyiv_yasno_groups.csv` | Created only if the helper script is left running past the street stage |

To force a fresh message for testing, delete the matching `hash_*.txt` file and run the script again.

## Security

`config.json` contains your bot token. The script saves it readable only by you (`chmod 600`). Never commit it. Add this to `.gitignore`:

```gitignore
.venv/
config.json
hash_*.txt
bot.log
kyiv_streets.json
kyiv_yasno_groups.csv
```

If the token ever leaks, send `/revoke` to @BotFather, pick the bot, and run `python yasno-outage-bot.py --telegram` with the new token.

## Troubleshooting

- **`Group 23.5 does not exist in the schedule`**: check the group and subgroup (Option A above). Queues are written `group.subgroup`.
- **`Telegram test failed`**: check the token, and that the chat ID is correct (groups are negative). In a group, the bot must be a member.
- **`Could not fetch the schedule`**: the Yasno API may be down or blocking the request. Try again later.
- **No messages from cron**: that is normal while the schedule is unchanged. Check `bot.log` for errors, and test the command by hand.
- **Python 3.15 and `pip` crashes with `no_type_check_decorator`**: the pip bundled with Python 3.15.2 is incompatible. Run `curl -sS https://bootstrap.pypa.io/get-pip.py | python` inside the venv, or use Python 3.13/3.14.

## Using it for another city

The script targets Kyiv. For another city or DSO, change these two constants at the top of `yasno-outage-bot.py`:

```python
REGION = 25
DSO = 902
```

Their values are in the `planned-outages` request URL on that city's Yasno page (DevTools, Network tab). The response format may differ between cities, so this is not guaranteed to work without changes.

## Disclaimer

This is an unofficial tool and is not affiliated with Yasno or DTEK. It uses a public API that may change without notice.
