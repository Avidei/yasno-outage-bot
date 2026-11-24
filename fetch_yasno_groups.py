import csv
import itertools
import json
import os
import time
import requests

REGION_ID = 25
DSO_ID = 902
BASE_URL = "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2"
STREETS_CACHE = "kyiv_streets.json"
OUTPUT_FILE = "kyiv_yasno_groups.csv"

UA_LETTERS = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
UA_CHARS = UA_LETTERS + "0123456789-."
HOUSE_CHARS = "0123456789" + UA_LETTERS + "/-"

# Set to the exact max items the API returns in one response (e.g., 10, 20, or 50)
PAGE_LIMIT = 10

# Common Ukrainian street type prefixes (all >= 3 chars)
STREET_SEEDS = [
    "вул", "про", "бул", "пл.", "узв", "наб", "шос",
    "але", "туп", "мік", "ж/м", "с/т", "кв-", "ост"
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://static.yasno.ua/",
})


def fetch_json(endpoint, params):
    while True:
        try:
            r = session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            if r.status_code == 200:
                time.sleep(0.15)
                return r.json()
            if r.status_code == 429:
                print("Rate limited (429). Sleeping 15 seconds...")
                time.sleep(15)
                continue
            if r.status_code in (400, 404):
                return []
            print(f"HTTP {r.status_code} on {endpoint}. Retrying in 5s...")
            time.sleep(5)
        except requests.RequestException as e:
            print(f"Network error: {e}. Retrying in 3s...")
            time.sleep(3)


def collect_streets():
    if os.path.exists(STREETS_CACHE):
        with open(STREETS_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
            print(f"Loaded {len(cached)} streets from {STREETS_CACHE}")
            return {int(k): v for k, v in cached.items()}

    streets = {}
    visited = set()

    def search_prefix(prefix):
        if prefix in visited:
            return
        visited.add(prefix)

        data = fetch_json("streets", {"regionId": REGION_ID, "dsoId": DSO_ID, "query": prefix})
        if not isinstance(data, list):
            return
        for item in data:
            streets[item["id"]] = item["value"]

        # Deepen search if response hits PAGE_LIMIT (up to 6 chars, e.g. "вул. а")
        if len(data) >= PAGE_LIMIT and len(prefix) < 6:
            for ch in UA_CHARS + " ":
                search_prefix(prefix + ch)

    for seed in STREET_SEEDS:
        search_prefix(seed)
        print(f"Seed '{seed}': total unique streets = {len(streets)}")

    with open(STREETS_CACHE, "w", encoding="utf-8") as f:
        json.dump(streets, f, ensure_ascii=False, indent=2)

    return streets


def collect_houses(street_id):
    houses = {}
    # Test if houses endpoint accepts empty query or 1-digit queries
    for q in ["", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]:
        data = fetch_json("houses", {"regionId": REGION_ID, "dsoId": DSO_ID, "streetId": street_id, "query": q})
        if not isinstance(data, list):
            continue
        for h in data:
            houses[h["id"]] = h["value"]
        if q == "" and 0 < len(data) < PAGE_LIMIT:
            return houses
        if len(data) >= PAGE_LIMIT and q != "":
            for ch in HOUSE_CHARS:
                sub = fetch_json("houses", {"regionId": REGION_ID, "dsoId": DSO_ID, "streetId": street_id, "query": q + ch})
                if isinstance(sub, list):
                    for h in sub:
                        houses[h["id"]] = h["value"]
    return houses


def main():
    print("1. Collecting streets...")
    streets = collect_streets()
    print(f"Total unique streets: {len(streets)}")

    done_streets = set()
    file_exists = os.path.exists(OUTPUT_FILE)

    if file_exists:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done_streets.add(int(row["street_id"]))
        print(f"Resuming: {len(done_streets)} streets already processed.")

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["street_id", "street_name", "house_id", "house_number", "group"])

        for idx, (s_id, s_name) in enumerate(streets.items(), 1):
            if s_id in done_streets:
                continue

            houses = collect_houses(s_id)
            for h_id, h_num in houses.items():
                grp = fetch_json("group", {
                    "regionId": REGION_ID,
                    "dsoId": DSO_ID,
                    "streetId": s_id,
                    "houseId": h_id
                })
                if isinstance(grp, dict) and "group" in grp:
                    group_str = f"{grp['group']}.{grp['subgroup']}"
                    writer.writerow([s_id, s_name, h_id, h_num, group_str])

            f.flush()
            print(f"[{idx}/{len(streets)}] {s_name} — houses saved: {len(houses)}")


if __name__ == "__main__":
    main()
