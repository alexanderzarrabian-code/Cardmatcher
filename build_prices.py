#!/usr/bin/env python3
"""Builds prices.json for the Card Twin Finder from tcgcsv.com (nightly TCGplayer mirror).

Runs on GitHub Actions once a night. Uses only the Python standard library.
Pokemon is categoryId 3 on tcgcsv.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

BASE = os.environ.get("TCGCSV_BASE", "https://tcgcsv.com/tcgplayer/3")
MIN_CARDS = int(os.environ.get("MIN_CARDS", "10000"))  # safety: never publish a near-empty file
OUT = os.environ.get("OUT", "prices.json")
PAUSE = float(os.environ.get("PAUSE", "0.15"))


def get(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "card-twin-finder/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # network hiccup, 5xx, bad JSON
            if attempt == tries - 1:
                raise
            print(f"  retry {attempt + 1} for {url}: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def clean_name(name, number):
    """tcgcsv names look like 'Charizard - 004/165'; drop the trailing number."""
    if number and name.endswith(" - " + number):
        return name[: -(len(number) + 3)].strip()
    return re.sub(r"\s+-\s+[A-Za-z0-9]*\d[A-Za-z0-9]*(?:/\d+)?\s*$", "", name).strip()


def main():
    groups = get(f"{BASE}/groups")["results"]
    print(f"{len(groups)} sets found")
    cards, failed = [], 0
    for g in groups:
        gid, gname = g["groupId"], g.get("name", "")
        date = (g.get("publishedOn") or "")[:7]
        try:
            products = get(f"{BASE}/{gid}/products")["results"]
            prices = get(f"{BASE}/{gid}/prices")["results"]
        except Exception as exc:
            failed += 1
            print(f"SKIPPED set {gid} {gname}: {exc}", file=sys.stderr)
            continue

        by_product = {}
        for p in prices:
            market = p.get("marketPrice")
            if market is None:
                continue
            low = p.get("lowPrice")
            by_product.setdefault(p["productId"], {})[p.get("subTypeName") or "Normal"] = [
                round(market, 2),
                round(low, 2) if low is not None else None,
            ]

        for prod in products:
            ext = {e.get("name"): e.get("value") for e in prod.get("extendedData", [])}
            number = ext.get("Number")
            if not number:  # sealed products etc. have no card number
                continue
            variants = by_product.get(prod["productId"])
            if not variants:
                continue
            pid = prod["productId"]
            card = {
                "i": pid,
                "n": clean_name(prod.get("name", ""), number),
                "s": gname,
                "d": date,
                "no": number,
                "r": ext.get("Rarity", ""),
                "v": variants,
            }
            std_img = f"https://tcgplayer-cdn.tcgplayer.com/product/{pid}_200w.jpg"
            if prod.get("imageUrl") and prod["imageUrl"] != std_img:
                card["im"] = prod["imageUrl"]
            cards.append(card)
        time.sleep(PAUSE)

    print(f"{len(cards)} priced cards, {failed} sets skipped")
    if len(cards) < MIN_CARDS or failed > max(5, len(groups) * 0.1):
        sys.exit("Too little data; not overwriting the existing prices file.")

    out = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"), "cards": cards}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
