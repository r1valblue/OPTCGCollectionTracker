#!/usr/bin/env python3
"""
scrape.py — One Piece TCG card database builder
Uses Playwright (headless Chromium) to scrape onepiece.limitlesstcg.com
 
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
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
 
BASE_URL  = "https://onepiece.limitlesstcg.com"
NAV_WAIT  = "domcontentloaded"   # faster than networkidle; we wait for specific elements
PAGE_TO   = 60_000               # 60 s per page
RETRY_TO  = 90_000               # 90 s on retry
MAX_RETRIES = 3
DELAY_OK  = 0.3                  # seconds between successful requests
DELAY_ERR = 5.0                  # seconds after a failed request
 
 
# ── helpers ──────────────────────────────────────────────────────────────────
 
def goto_with_retry(page, url, wait_selector, retries=MAX_RETRIES):
    """Navigate to url and wait for wait_selector. Retries on timeout."""
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until=NAV_WAIT, timeout=PAGE_TO)
            page.wait_for_selector(wait_selector, timeout=PAGE_TO)
            time.sleep(DELAY_OK)
            return True
        except PWTimeout:
            print(f"    ⚠ Timeout (attempt {attempt}/{retries}): {url}")
            time.sleep(DELAY_ERR * attempt)
        except Exception as e:
            print(f"    ⚠ Error (attempt {attempt}/{retries}): {e}")
            time.sleep(DELAY_ERR * attempt)
    return False
 
 
def get_card_image(page):
    """Return the first CDN image src found on the current page, or ''."""
    try:
        return page.evaluate("""() => {
            const img = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
            return img ? img.getAttribute('src') : '';
        }""")
    except Exception:
        return ""
 
 
# ── JS snippet run inside the browser to extract card data ───────────────────
 
EXTRACT_JS = """(cardId) => {
    // Name
    const h1 = document.querySelector('h1');
    let name = h1 ? h1.innerText.trim() : cardId;
    name = name.split('\\n')[0].trim()
               .replace(new RegExp('\\\\s*' + cardId + '\\\\b.*', 'i'), '').trim()
               || cardId;
 
    // Image
    const imgEl = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
    const image = imgEl ? imgEl.getAttribute('src') : '';
 
    // Full text
    const bodyText = document.body.innerText;
    const lines = bodyText.split('\\n').map(l => l.trim()).filter(Boolean);
 
    // Type / color / cost / life
    let cardType = '', color = '', cost = '', life = '';
    const typeRe = /^(Leader|Character|Event|Stage)\\s*[•·]\\s*(.+?)(?:\\s*[•·]\\s*(\\d+)\\s*(Life|Cost))?$/i;
    for (const line of lines) {
        const m = typeRe.exec(line);
        if (m) {
            cardType = m[1].trim();
            color    = m[2].replace(/\\s*[•·].*/, '').trim();
            if (m[3]) { if ((m[4]||'').toLowerCase()==='life') life=m[3]; else cost=m[3]; }
            break;
        }
    }
 
    // Power
    const powM    = bodyText.match(/(\\d{3,6})\\s*Power/i);
    const power   = powM ? powM[1] : '';
 
    // Counter
    const ctrM    = bodyText.match(/[+]?(\\d{3,5})\\s*Counter/i);
    const counter = ctrM ? '+' + ctrM[1] : '';
 
    // Attribute
    const attrM    = bodyText.match(/\\b(Slash|Strike|Special|Ranged|Wisdom)\\b/i);
    const attribute = attrM ? attrM[1] : '';
 
    // Subtypes  e.g. "Supernovas/Straw Hat Crew"
    let subtypes = [];
    for (const line of lines) {
        if (/^[A-Z][A-Za-z ]+(?: Pirates)?(\\/[A-Z][A-Za-z ]+)+$/.test(line)) {
            subtypes = line.split('/').map(s => s.trim());
            break;
        }
    }
 
    // Effect + trigger
    let effectLines = [], collecting = false, trigger = '';
    const stopWords = ['USD','EUR','Buy','Tournament','Deck','Print','Language','Block','Latest','Decks With'];
    for (const line of lines) {
        if (/^\\[/.test(line) || line.includes('DON!!')) collecting = true;
        if (collecting) {
            if (stopWords.some(w => line.includes(w))) break;
            if (line.startsWith('[Trigger]')) { trigger = line.replace('[Trigger]','').trim(); continue; }
            effectLines.push(line);
        }
    }
    const effect = effectLines.join(' ').trim();
 
    // Rarity
    const rarM  = bodyText.match(/\\b(Leader|Common|Uncommon|Rare|Super Rare|Secret Rare|Special Card|Promo)\\b/);
    const rarity = rarM ? rarM[1] : '';
 
    // Variant links  /cards/OP01-001?v=1
    const variants = [];
    document.querySelectorAll('a[href*="?v="]').forEach(a => {
        const vm = a.getAttribute('href').match(/\\?v=(\\d+)/);
        if (vm) {
            const vNum = parseInt(vm[1]);
            const vLabel = a.innerText.trim();
            if (!variants.find(x => x.num === vNum))
                variants.push({num: vNum, label: vLabel});
        }
    });
 
    return {name,image,cardType,color,cost,life,power,counter,attribute,subtypes,effect,trigger,rarity,variants};
}"""
 
 
# ── main scrape ───────────────────────────────────────────────────────────────
 
def scrape_all(new_only: bool, output_path: Path):
 
    # Load existing
    existing_cards    = []
    existing_set_codes = set()
    if output_path.exists():
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing_cards     = data
                existing_set_codes = {c["set"] for c in existing_cards if isinstance(c, dict)}
                print(f"Loaded {len(existing_cards)} existing cards ({len(existing_set_codes)} sets)")
        except Exception as e:
            print(f"Warning: {e} — starting fresh")
 
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="en-US",
        )
        page = ctx.new_page()
 
        # ── Discover sets ─────────────────────────────────────────────────
        all_sets = []
        print("\nDiscovering sets...")
 
        for discover_url in [f"{BASE_URL}/cards", f"{BASE_URL}/cards/promos"]:
            ok = goto_with_retry(page, discover_url, "table tbody tr")
            if not ok:
                print(f"  ✗ Could not load {discover_url}")
                continue
 
            rows = page.query_selector_all("table tbody tr")
            for row in rows:
                link = row.query_selector("a[href^='/cards/']")
                if not link:
                    continue
                href  = link.get_attribute("href") or ""
                slug  = href.replace("/cards/", "").strip()
                name  = link.inner_text().strip()
                if not slug or not name:
                    continue
                m    = re.match(r"^([a-z]{2,5}\d{2})", slug)
                code = m.group(1).upper() if m else slug.upper()
                all_sets.append({"code": code, "slug": slug, "name": name})
 
        # Deduplicate
        seen, unique_sets = set(), []
        for s in all_sets:
            if s["slug"] not in seen:
                seen.add(s["slug"])
                unique_sets.append(s)
 
        print(f"Found {len(unique_sets)} sets")
 
        if new_only:
            unique_sets = [s for s in unique_sets if s["code"] not in existing_set_codes]
            print(f"After new-only filter: {len(unique_sets)} sets to scrape")
 
        if not unique_sets:
            print("Nothing new to scrape.")
            browser.close()
            return
 
        # ── Scrape each set ───────────────────────────────────────────────
        all_new_cards = []
 
        for set_info in unique_sets:
            slug = set_info["slug"]
            code = set_info["code"]
            sname = set_info["name"]
            print(f"\n── {code}: {sname}")
 
            # Get card list
            set_url = f"{BASE_URL}/cards/{slug}"
            ok = goto_with_retry(page, set_url, "a[href^='/cards/'] img, .card-search-grid")
            if not ok:
                print(f"  ✗ Could not load set page, skipping")
                continue
 
            card_entries = page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('a[href^="/cards/"]').forEach(a => {
                    const href = a.getAttribute('href');
                    const m = href.match(/^\\/cards\\/([A-Z0-9]{2,6}-\\d{3}[A-Z]?)$/i);
                    if (!m) return;
                    const id  = m[1].toUpperCase();
                    const img = a.querySelector('img');
                    const src = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
                    results.push({id, imgSrc: src});
                });
                const seen = new Set();
                return results.filter(x => { if (seen.has(x.id)) return false; seen.add(x.id); return true; });
            }""")
 
            print(f"  Found {len(card_entries)} cards")
 
            for i, entry in enumerate(card_entries):
                card_id    = entry["id"]
                base_image = entry["imgSrc"]
                print(f"  [{i+1}/{len(card_entries)}] {card_id}", end="", flush=True)
 
                # Fetch card detail page
                card_url = f"{BASE_URL}/cards/{card_id}"
                ok = goto_with_retry(page, card_url, "h1")
                if not ok:
                    print(" ✗ skipped (timeout)")
                    continue
 
                try:
                    card_data = page.evaluate(EXTRACT_JS, card_id)
                except Exception as e:
                    print(f" ✗ parse error: {e}")
                    continue
 
                base_id = card_id
 
                def make_card(vid, variant_label, img):
                    return {
                        "id":        vid,
                        "baseId":    base_id,
                        "name":      card_data["name"],
                        "set":       code,
                        "setName":   sname,
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
                        "image":     img or base_image,
                        "variant":   variant_label,
                    }
 
                all_new_cards.append(make_card(base_id, "", card_data["image"] or base_image))
 
                # Variant pages
                for v in card_data["variants"]:
                    v_url = f"{BASE_URL}/cards/{card_id}?v={v['num']}"
                    v_ok  = goto_with_retry(page, v_url, "h1")
                    v_img = get_card_image(page) if v_ok else card_data["image"]
                    vid   = f"{base_id}_p{v['num']}"
                    all_new_cards.append(make_card(vid, v["label"], v_img))
 
                count = 1 + len(card_data["variants"])
                print(f" ✓  ({count} print{'s' if count > 1 else ''})")
 
                # Save progress after every card so a crash doesn't lose everything
                fetched_codes = {c["set"] for c in all_new_cards}
                kept    = [c for c in existing_cards if c.get("set") not in fetched_codes]
                merged  = kept + all_new_cards
                output_path.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
                )
 
        browser.close()
 
    print(f"\n✓ Done — {len(all_new_cards)} cards written to {output_path}")
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--out", default="cards.json")
    args = parser.parse_args()
    scrape_all(args.new_only, Path(args.out))
 
 
if __name__ == "__main__":
    main()
