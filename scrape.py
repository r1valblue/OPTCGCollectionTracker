#!/usr/bin/env python3
"""
scrape.py — One Piece TCG card database builder
Uses Playwright (headless browser) to scrape onepiece.limitlesstcg.com
so JavaScript-rendered content is fully available.
 
Usage:
  python scrape.py              # full scrape
  python scrape.py --new-only   # only sets not already in cards.json
 
Install:
  pip install playwright
  playwright install chromium
"""
 
import argparse
import json
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
 
BASE_URL = "https://onepiece.limitlesstcg.com"
 
def scrape_all(new_only: bool, output_path: Path):
 
    # Load existing data
    existing_cards = []
    existing_set_codes = set()
    if output_path.exists():
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing_cards = data
                existing_set_codes = {c["set"] for c in existing_cards if isinstance(c, dict)}
                print(f"Loaded {len(existing_cards)} existing cards ({len(existing_set_codes)} sets)")
        except Exception as e:
            print(f"Warning: could not load existing cards.json: {e}")
 
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="en-US",
        )
        page = ctx.new_page()
        page.set_default_timeout(30000)
 
        # ── 1. Discover sets ──────────────────────────────────────────────
        all_sets = []
        print("Discovering sets...")
 
        for url in [f"{BASE_URL}/cards", f"{BASE_URL}/cards/promos"]:
            page.goto(url, wait_until="networkidle")
            # Wait for the table to appear
            try:
                page.wait_for_selector("table tbody tr", timeout=15000)
            except PWTimeout:
                print(f"  ⚠ No table found at {url}")
                continue
 
            rows = page.query_selector_all("table tbody tr")
            for row in rows:
                link = row.query_selector("a[href^='/cards/']")
                if not link:
                    continue
                href = link.get_attribute("href") or ""
                slug = href.replace("/cards/", "").strip()
                name = link.inner_text().strip()
                if not slug or not name:
                    continue
                # Derive set code from slug prefix e.g. op01-romance-dawn → OP01
                m = re.match(r"^([a-z]{2,5}\d{2})", slug)
                code = m.group(1).upper() if m else slug.upper()
                is_promo = "promos" in url
                all_sets.append({"code": code, "slug": slug, "name": name, "is_promo": is_promo})
 
        # Deduplicate
        seen_slugs = set()
        unique_sets = []
        for s in all_sets:
            if s["slug"] not in seen_slugs:
                seen_slugs.add(s["slug"])
                unique_sets.append(s)
 
        print(f"Found {len(unique_sets)} sets")
 
        if new_only:
            unique_sets = [s for s in unique_sets if s["code"] not in existing_set_codes]
            print(f"After filtering already-scraped sets: {len(unique_sets)} remaining")
 
        if not unique_sets:
            print("Nothing new to scrape.")
            browser.close()
            return
 
        # ── 2. Scrape each set ────────────────────────────────────────────
        all_new_cards = []
 
        for set_info in unique_sets:
            slug = set_info["slug"]
            code = set_info["code"]
            name = set_info["name"]
            print(f"\n── {code}: {name}")
 
            # Get card list from set page
            set_url = f"{BASE_URL}/cards/{slug}"
            try:
                page.goto(set_url, wait_until="networkidle")
                page.wait_for_selector(".card-search-grid a, .image img, a[href*='/cards/'] img", timeout=15000)
            except PWTimeout:
                print(f"  ⚠ Timed out waiting for card grid")
                continue
 
            # Collect all card links + images from the set page grid
            card_entries = page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('a[href^="/cards/"]').forEach(a => {
                    const href = a.getAttribute('href');
                    // Match /cards/OP01-001 (no query string)
                    const m = href.match(/^\\/cards\\/([A-Z0-9]{2,6}-\\d{3}[A-Z]?)$/i);
                    if (!m) return;
                    const id = m[1].toUpperCase();
                    const img = a.querySelector('img');
                    const imgSrc = img ? img.getAttribute('src') || img.getAttribute('data-src') || '' : '';
                    results.push({id, imgSrc});
                });
                // Deduplicate by id
                const seen = new Set();
                return results.filter(x => { if (seen.has(x.id)) return false; seen.add(x.id); return true; });
            }""")
 
            print(f"  Found {len(card_entries)} cards in set")
 
            for i, entry in enumerate(card_entries):
                card_id = entry["id"]
                base_image = entry["imgSrc"]
 
                print(f"  [{i+1}/{len(card_entries)}] {card_id}", end="", flush=True)
 
                card_url = f"{BASE_URL}/cards/{card_id}"
                try:
                    page.goto(card_url, wait_until="networkidle")
                    page.wait_for_selector("h1, .card-text-name", timeout=15000)
                except PWTimeout:
                    print(" ⚠ timeout")
                    continue
 
                try:
                    card_data = page.evaluate("""(cardId) => {
                        // ── Name ──
                        const h1 = document.querySelector('h1');
                        let name = h1 ? h1.innerText.trim() : cardId;
                        // Strip card ID if present in heading
                        name = name.split('\\n')[0].trim();
                        name = name.replace(new RegExp('\\\\s*' + cardId + '\\\\b.*', 'i'), '').trim();
                        if (!name) name = cardId;
 
                        // ── Main card image ──
                        const imgEl = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
                        const image = imgEl ? imgEl.getAttribute('src') : '';
 
                        // ── Full page text for parsing ──
                        const bodyText = document.body.innerText;
                        const lines = bodyText.split('\\n').map(l => l.trim()).filter(Boolean);
 
                        // ── Type + color + cost/life ──
                        let cardType = '', color = '', cost = '', life = '';
                        const typeRe = /^(Leader|Character|Event|Stage)\\s*[•·]\\s*(.+?)(?:\\s*[•·]\\s*(\\d+)\\s*(Life|Cost))?$/i;
                        for (const line of lines) {
                            const m = typeRe.exec(line);
                            if (m) {
                                cardType = m[1].trim();
                                color = m[2].replace(/\\s*[•·].*/, '').trim();
                                if (m[3]) {
                                    if (m[4] && m[4].toLowerCase() === 'life') life = m[3];
                                    else cost = m[3];
                                }
                                break;
                            }
                        }
 
                        // ── Power ──
                        const powM = bodyText.match(/(\\d{3,6})\\s*Power/i);
                        const power = powM ? powM[1] : '';
 
                        // ── Counter ──
                        const ctrM = bodyText.match(/[+]?(\\d{3,5})\\s*Counter/i);
                        const counter = ctrM ? '+' + ctrM[1] : '';
 
                        // ── Attribute ──
                        const attrM = bodyText.match(/\\b(Slash|Strike|Special|Ranged|Wisdom)\\b/i);
                        const attribute = attrM ? attrM[1] : '';
 
                        // ── Subtypes ──
                        let subtypes = [];
                        for (const line of lines) {
                            if (/^[A-Z][A-Za-z ]+(?: Pirates)?(\\/[A-Z][A-Za-z ]+)+$/.test(line)) {
                                subtypes = line.split('/').map(s => s.trim());
                                break;
                            }
                        }
 
                        // ── Effect text ──
                        let effectLines = [], collecting = false;
                        let trigger = '';
                        const stopWords = ['USD','EUR','Buy','Tournament','Deck','Print','Language','Block','Latest'];
                        for (const line of lines) {
                            if (/^\\[/.test(line) || line.includes('DON!!')) collecting = true;
                            if (collecting) {
                                if (stopWords.some(w => line.includes(w))) break;
                                if (line.startsWith('[Trigger]')) { trigger = line.replace('[Trigger]', '').trim(); continue; }
                                effectLines.push(line);
                            }
                        }
                        const effect = effectLines.join(' ').trim();
 
                        // ── Rarity ──
                        const rarM = bodyText.match(/\\b(Leader|Common|Uncommon|Rare|Super Rare|Secret Rare|Special Card|Promo)\\b/);
                        const rarity = rarM ? rarM[1] : '';
 
                        // ── Variant links ──
                        const variants = [];
                        document.querySelectorAll('a[href*="?v="]').forEach(a => {
                            const vm = a.getAttribute('href').match(/\\?v=(\\d+)/);
                            if (vm) {
                                const vNum = parseInt(vm[1]);
                                const vLabel = a.innerText.trim();
                                if (!variants.find(x => x.num === vNum)) {
                                    variants.push({num: vNum, label: vLabel});
                                }
                            }
                        });
 
                        return {name, image, cardType, color, cost, life, power, counter, attribute, subtypes, effect, trigger, rarity, variants};
                    }""", card_id)
 
                    base_id = card_id
 
                    def make_card(vid, variant_label, img):
                        return {
                            "id":        vid,
                            "baseId":    base_id,
                            "name":      card_data["name"],
                            "set":       code,
                            "setName":   name,
                            "rarity":    card_data["rarity"],
                            "color":     card_data["color"],
                            "type":      card_data["cardType"],
                            "cost":      card_data["cost"],
                            "life":      card_data["life"],
                            "power":     card_data["power"],
                            "counter":   card_data["counter"],
                            "attribute": card_data["attribute"],
                            "subtypes":  card_data["subtypes"],
                            "effect":    card_data["effect"],
                            "trigger":   card_data["trigger"],
                            "image":     img,
                            "variant":   variant_label,
                        }
 
                    # Base card
                    all_new_cards.append(make_card(base_id, "", card_data["image"] or base_image))
 
                    # Variant pages
                    for v in card_data["variants"]:
                        v_url = f"{BASE_URL}/cards/{card_id}?v={v['num']}"
                        try:
                            page.goto(v_url, wait_until="networkidle")
                            v_img = page.evaluate("""() => {
                                const img = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
                                return img ? img.getAttribute('src') : '';
                            }""")
                            vid = f"{base_id}_p{v['num']}"
                            all_new_cards.append(make_card(vid, v["label"], v_img or card_data["image"]))
                        except Exception:
                            vid = f"{base_id}_p{v['num']}"
                            all_new_cards.append(make_card(vid, v["label"], card_data["image"]))
 
                    variant_count = len(card_data["variants"])
                    print(f" ✓  ({1 + variant_count} print{'s' if variant_count else ''})")
 
                except Exception as e:
                    print(f" ✗ {e}")
 
        browser.close()
 
    # Merge and save
    fetched_codes = {c["set"] for c in all_new_cards}
    kept = [c for c in existing_cards if c.get("set") not in fetched_codes]
    merged = kept + all_new_cards
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Written {len(merged)} total cards ({len(all_new_cards)} new) → {output_path}")
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--out", default="cards.json")
    args = parser.parse_args()
    scrape_all(args.new_only, Path(args.out))
 
if __name__ == "__main__":
    main()
