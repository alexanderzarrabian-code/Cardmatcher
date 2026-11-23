#!/usr/bin/env python3
"""Builds prices.json (English) and prices_jp.json (Japanese) for Binder Buddy from tcgcsv.com.

Runs on GitHub Actions once a night. Uses only the Python standard library.
English Pokemon is categoryId 3 on tcgcsv. The Japanese category is looked up by name
("Pokemon Japan") so its id never has to be hard-coded.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

BASE = os.environ.get("TCGCSV_BASE", "https://tcgcsv.com/tcgplayer/3")
ROOT = BASE.rsplit("/", 1)[0]  # https://tcgcsv.com/tcgplayer
MIN_CARDS = int(os.environ.get("MIN_CARDS", "10000"))  # safety: never publish a near-empty file
MIN_CARDS_JP = int(os.environ.get("MIN_CARDS_JP", "3000"))
OUT = os.environ.get("OUT", "prices.json")
OUT_JP = os.environ.get("OUT_JP", "prices_jp.json")
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


def build(base, out_path, min_cards):
    """Returns True if out_path was written, False if the safety checks refused to overwrite it."""
    groups = get(f"{base}/groups")["results"]
    print(f"{len(groups)} sets found")
    cards, failed = [], 0
    for g in groups:
        gid, gname = g["groupId"], g.get("name", "")
        date = (g.get("publishedOn") or "")[:7]
        try:
            products = get(f"{base}/{gid}/products")["results"]
            prices = get(f"{base}/{gid}/prices")["results"]
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
    if len(cards) < min_cards or failed > max(5, len(groups) * 0.1):
        print(f"Too little data; not overwriting {out_path}.", file=sys.stderr)
        return False

    out = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"), "cards": cards}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote {out_path} ({os.path.getsize(out_path) / 1e6:.1f} MB)")
    return True


def find_japan_category():
    """Look up the 'Pokemon Japan' category id by name; None if it can't be found."""
    try:
        cats = get(f"{ROOT}/categories")["results"]
    except Exception as exc:
        print(f"Could not list categories: {exc}", file=sys.stderr)
        return None
    for c in cats:
        name = (c.get("name") or c.get("displayName") or "").lower()
        if "pokemon" in name and "japan" in name:
            return c["categoryId"]
    return None


def main():
    print("== English ==")
    if not build(BASE, OUT, MIN_CARDS):
        sys.exit("English prices failed the safety checks; nothing was overwritten.")
    # Japanese is best-effort: if anything goes wrong, the English file is already saved
    # and the previous Japanese file (if any) is kept.
    print("== Japanese ==")
    cid = find_japan_category()
    if cid is None:
        print("Pokemon Japan category not found; skipping Japanese.", file=sys.stderr)
        return
    print(f"Pokemon Japan is category {cid}")
    try:
        build(f"{ROOT}/{cid}", OUT_JP, MIN_CARDS_JP)
    except Exception as exc:
        print(f"Japanese build failed, keeping the old file: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
