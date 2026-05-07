#!/usr/bin/env python3
"""
scrape.py — Limitless One Piece card scraper
Builds cards.json from https://onepiece.limitlesstcg.com

Usage:
  python scrape.py              # full scrape (all sets)
  python scrape.py --new-only   # only sets not already in cards.json
  python scrape.py --sets OP01 OP02 ST01   # specific sets only

Requirements:
  pip install requests beautifulsoup4
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://onepiece.limitlesstcg.com"

HEADERS = {
    "User-Agent": "OPTCGCollectionTracker/1.0 (https://github.com/r1valblue/OPTCGCollectionTracker; non-commercial fan project)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Polite delay between requests (seconds)
REQUEST_DELAY = 0.5


def get(url: str, retries: int = 3) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object. Retries on failure."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = 2 ** attempt * 2
                print(f"  ⚠ Retry {attempt+1}/{retries} for {url} ({e}) — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"  ✗ Failed after {retries} attempts: {url} ({e})")
                raise


# ---------------------------------------------------------------------------
# Set discovery
# ---------------------------------------------------------------------------

def discover_sets() -> list:
    """
    Fetch the /cards index and /cards/promos pages and return a list of
    {"code": "OP01", "slug": "op01-romance-dawn", "name": "Romance Dawn", "is_promo": False}
    """
    sets = []

    # --- Main products page ---
    soup = get(f"{BASE_URL}/cards")
    for row in soup.select("table tbody tr"):
        link = row.find("a", href=re.compile(r"^/cards/[a-z0-9\-]+$"))
        if not link:
            continue
        href = link["href"]          # e.g. /cards/op01-romance-dawn
        slug = href.split("/cards/")[1]
        name = link.get_text(strip=True)

        # Derive short code from slug prefix (op01 → OP01, st01 → ST01, etc.)
        code_match = re.match(r"^([a-z]{2,4}\d{2})", slug)
        if not code_match:
            continue
        code = code_match.group(1).upper()

        sets.append({"code": code, "slug": slug, "name": name, "is_promo": False})

    # --- Promos page ---
    soup = get(f"{BASE_URL}/cards/promos")
    for row in soup.select("table tbody tr"):
        link = row.find("a", href=re.compile(r"^/cards/[a-z0-9\-]+$"))
        if not link:
            continue
        href = link["href"]
        slug = href.split("/cards/")[1]
        name = link.get_text(strip=True)
        sets.append({"code": slug, "slug": slug, "name": name, "is_promo": True})

    # Deduplicate by slug
    seen = set()
    unique = []
    for s in sets:
        if s["slug"] not in seen:
            seen.add(s["slug"])
            unique.append(s)

    main_count = sum(1 for s in unique if not s['is_promo'])
    promo_count = sum(1 for s in unique if s['is_promo'])
    print(f"Discovered {len(unique)} sets ({main_count} main, {promo_count} promo)")
    return unique


# ---------------------------------------------------------------------------
# Card ID discovery from a set page
# ---------------------------------------------------------------------------

def get_card_ids_from_set(slug: str) -> list:
    """
    Fetch a set page and return list of (card_id, image_url) tuples.
    card_id is like "OP01-001", image_url is the CDN webp.
    """
    soup = get(f"{BASE_URL}/cards/{slug}")
    results = []

    for a in soup.select("a[href^='/cards/']"):
        href = a["href"]
        # Match card ID pattern: /cards/OP01-001 (no query string variant here)
        m = re.match(r"^/cards/([A-Z0-9]{2,5}-\d{3}[A-Z]?)$", href, re.IGNORECASE)
        if not m:
            continue
        card_id = m.group(1).upper()

        img = a.find("img")
        image_url = img["src"] if img and img.get("src") else ""

        results.append((card_id, image_url))

    # Deduplicate by card_id (keep first occurrence = base print)
    seen = set()
    unique = []
    for cid, img in results:
        if cid not in seen:
            seen.add(cid)
            unique.append((cid, img))

    return unique


# ---------------------------------------------------------------------------
# Individual card page parsing
# ---------------------------------------------------------------------------

def parse_card_page(soup: BeautifulSoup, card_id: str, set_code: str, set_name: str, base_image: str) -> list:
    """
    Parse a card detail page and return a list of card dicts —
    one for the base print and one per alternate variant.
    """
    # --- Card image ---
    img_tag = soup.select_one("img[src*='cdn.digitaloceanspaces']")
    image = img_tag["src"] if img_tag else base_image

    # --- Card name ---
    # Try common selectors for the card name heading
    name = ""
    for sel in ["h1", ".card-text-name", ".card-name", "h2"]:
        tag = soup.select_one(sel)
        if tag:
            candidate = tag.get_text(strip=True)
            # Reject nav/site headings
            if candidate and "limitless" not in candidate.lower() and len(candidate) < 80:
                name = candidate
                break

    # Clean up: strip trailing card ID, newlines
    name = re.split(r"\s*[\n\r]+\s*", name)[0].strip()
    name = re.sub(r"\s*\b" + re.escape(card_id) + r"\b.*", "", name, flags=re.IGNORECASE).strip()
    if not name:
        name = card_id

    # --- Full page text for attribute extraction ---
    page_text = soup.get_text(separator="\n")
    lines = [l.strip() for l in page_text.splitlines() if l.strip()]

    rarity = ""
    color = ""
    card_type = ""
    cost = ""
    power = ""
    counter = ""
    attribute = ""
    subtypes = []
    effect = ""
    trigger = ""
    life = ""

    # Card type + color: "Leader • Red • 5 Life" or "Character • Blue • 4 Cost"
    type_color_re = re.compile(
        r"^(Leader|Character|Event|Stage)\s*[•·]\s*(.+?)(?:\s*[•·]\s*(\d+)\s*(Life|Cost))?$",
        re.IGNORECASE,
    )
    for line in lines:
        m = type_color_re.match(line)
        if m:
            card_type = m.group(1).strip()
            color = re.sub(r"\s*[•·].*", "", m.group(2)).strip()
            if m.group(3):
                if m.group(4) and m.group(4).lower() == "life":
                    life = m.group(3)
                else:
                    cost = m.group(3)
            break

    # Power: "5000 Power"
    power_match = re.search(r"(\d{3,6})\s*Power", page_text, re.IGNORECASE)
    if power_match:
        power = power_match.group(1)

    # Cost standalone (if not caught above): "4\nCost" or "Cost 4"
    if not cost:
        cost_match = re.search(r"(?:^|\n)\s*(\d{1,2})\s*\n\s*Cost\s*(?:\n|$)", page_text)
        if cost_match:
            cost = cost_match.group(1)

    # Counter: "+1000 Counter"
    counter_match = re.search(r"[+]?(\d{3,5})\s*Counter", page_text, re.IGNORECASE)
    if counter_match:
        counter = "+" + counter_match.group(1)

    # Attribute
    attr_match = re.search(r"\b(Slash|Strike|Special|Ranged|Wisdom)\b", page_text, re.IGNORECASE)
    if attr_match:
        attribute = attr_match.group(1).capitalize()

    # Subtypes: line like "Supernovas/Straw Hat Crew"
    for line in lines:
        if re.match(r"^[A-Z][A-Za-z ]+(?: Pirates)?(?:/[A-Z][A-Za-z ]+)+$", line):
            subtypes = [s.strip() for s in line.split("/")]
            break

    # Effect text: collect lines starting from first [bracket] effect
    effect_lines = []
    collecting = False
    STOP_WORDS = {"USD", "EUR", "Buy", "Tournament", "Deck", "Print", "Language", "Block"}
    for line in lines:
        if re.match(r"^\[", line) or "DON!!" in line:
            collecting = True
        if collecting:
            if any(sw in line for sw in STOP_WORDS):
                break
            if line.startswith("[Trigger]"):
                trigger = line[len("[Trigger]"):].strip()
                continue
            effect_lines.append(line)
    effect = " ".join(effect_lines).strip()

    # Rarity
    rar_match = re.search(
        r"\b(Leader|Common|Uncommon|Rare|Super Rare|Secret Rare|Special Card|Promo)\b",
        page_text,
    )
    if rar_match:
        rarity = rar_match.group(1)

    # --- Variants (alt arts) ---
    variants = []
    for a in soup.select("a[href*='?v=']"):
        href = a["href"]
        v_match = re.search(r"\?v=(\d+)", href)
        if v_match:
            v_num = int(v_match.group(1))
            v_label = a.get_text(strip=True)
            if (v_num, v_label) not in variants:
                variants.append((v_num, v_label))

    base_id = card_id

    def make_card(variant_suffix, variant_label, variant_image):
        vid = base_id + (f"_p{variant_suffix}" if variant_suffix else "")
        return {
            "id": vid,
            "baseId": base_id,
            "name": name,
            "set": set_code,
            "setName": set_name,
            "rarity": rarity,
            "color": color,
            "type": card_type,
            "cost": cost,
            "life": life,
            "power": power,
            "counter": counter,
            "attribute": attribute,
            "subtypes": subtypes,
            "effect": effect,
            "trigger": trigger,
            "image": variant_image,
            "variant": variant_label,
        }

    cards = [make_card("", "", image)]

    for v_num, v_label in variants:
        # Fetch variant page for its specific image
        variant_image = image  # will be updated below
        cards.append(make_card(str(v_num), v_label, variant_image))

    return cards


def fetch_variant_image(card_id: str, v_num: int) -> str:
    """Fetch a ?v=N card page and return its image URL."""
    try:
        soup = get(f"{BASE_URL}/cards/{card_id}?v={v_num}")
        img_tag = soup.select_one("img[src*='cdn.digitaloceanspaces']")
        if img_tag:
            return img_tag["src"]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape_set(set_info: dict, existing_ids: set) -> list:
    """Scrape all cards in a set. Returns list of card dicts."""
    slug = set_info["slug"]
    code = set_info["code"]
    name = set_info["name"]
    print(f"\n── {code}: {name}")

    try:
        card_ids = get_card_ids_from_set(slug)
    except Exception as e:
        print(f"  ✗ Could not fetch set page: {e}")
        return []

    print(f"  Found {len(card_ids)} cards")
    all_cards = []

    for i, (card_id, base_image) in enumerate(card_ids):
        if card_id in existing_ids:
            print(f"  ↷ {card_id} already in cards.json — skipping")
            continue

        print(f"  [{i+1}/{len(card_ids)}] {card_id}", end="", flush=True)
        try:
            soup = get(f"{BASE_URL}/cards/{card_id}")
            cards = parse_card_page(soup, card_id, code, name, base_image)

            # Fetch real images for variants
            for card in cards[1:]:
                v_match = re.search(r"_p(\d+)$", card["id"])
                if v_match:
                    v_num = int(v_match.group(1))
                    vimg = fetch_variant_image(card_id, v_num)
                    if vimg:
                        card["image"] = vimg

            all_cards.extend(cards)
            count = len(cards)
            print(f" ✓  ({count} print{'s' if count > 1 else ''})")
        except Exception as e:
            print(f" ✗ {e}")

    return all_cards


def main():
    parser = argparse.ArgumentParser(description="Scrape Limitless One Piece → cards.json")
    parser.add_argument("--new-only", action="store_true",
                        help="Only scrape sets not already represented in cards.json")
    parser.add_argument("--sets", nargs="+", metavar="CODE",
                        help="Only scrape these set codes (e.g. OP01 ST01)")
    parser.add_argument("--out", default="cards.json",
                        help="Output file path (default: cards.json)")
    args = parser.parse_args()

    output_path = Path(args.out)

    # Load existing data
    existing_cards = []
    existing_ids = set()
    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                existing_cards = json.load(f)
            existing_ids = {c["id"] for c in existing_cards}
            print(f"Loaded {len(existing_cards)} existing cards from {output_path}")
        except Exception as e:
            print(f"Warning: could not load existing cards.json: {e}")

    # Discover sets
    print("Discovering sets from Limitless...")
    all_sets = discover_sets()

    # Filter by --sets flag
    if args.sets:
        target_codes = {s.upper() for s in args.sets}
        all_sets = [s for s in all_sets if s["code"].upper() in target_codes]
        print(f"Filtered to {len(all_sets)} sets: {[s['code'] for s in all_sets]}")

    # Filter by --new-only
    if args.new_only and not args.sets:
        existing_set_codes = {c["set"] for c in existing_cards}
        all_sets = [s for s in all_sets if s["code"].upper() not in existing_set_codes]
        print(f"New-only mode: {len(all_sets)} sets to scrape")

    if not all_sets:
        print("Nothing to scrape — cards.json is already up to date.")
        sys.exit(0)

    # Scrape each set
    new_cards = []
    for set_info in all_sets:
        cards = scrape_set(set_info, existing_ids)
        new_cards.extend(cards)

    # Merge and write
    all_cards = existing_cards + new_cards
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Written {len(all_cards)} total cards ({len(new_cards)} new) → {output_path}")


if __name__ == "__main__":
    main()
