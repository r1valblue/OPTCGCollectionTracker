#!/usr/bin/env python3

import argparse
import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL    = “https://onepiece.limitlesstcg.com”
NAV_TIMEOUT = 120_000   # 2 min per page navigation
DELAY       = 1.0       # seconds between requests

# Ad/tracker domains to block (speeds up networkidle without losing card data)

BLOCK_DOMAINS = [
“googletagmanager.com”, “google-analytics.com”, “doubleclick.net”,
“googlesyndication.com”, “adservice.google.com”, “amazon-adsystem.com”,
“playwire.com”, “ramp.com”, “moatads.com”, “scorecardresearch.com”,
]

def should_block(url: str) -> bool:
return any(d in url for d in BLOCK_DOMAINS)

def goto(page, url, retries=3):
“”“Navigate and wait for networkidle. Retries on timeout.”””
for attempt in range(1, retries + 1):
try:
page.goto(url, wait_until=“networkidle”, timeout=NAV_TIMEOUT)
time.sleep(DELAY)
return True
except PWTimeout:
wait = attempt * 15
print(f”    ⚠ timeout attempt {attempt}/{retries} — waiting {wait}s”)
time.sleep(wait)
except Exception as e:
wait = attempt * 15
print(f”    ⚠ error attempt {attempt}/{retries}: {e} — waiting {wait}s”)
time.sleep(wait)
return False

EXTRACT_JS = “””(cardId) => {
const h1 = document.querySelector(‘h1’);
let name = h1 ? h1.innerText.trim() : cardId;
name = name.split(’\n’)[0].trim()
.replace(new RegExp(’\\s*’ + cardId + ‘\\b.*’, ‘i’), ‘’).trim()
|| cardId;

```
const imgEl = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
const image = imgEl ? imgEl.src : '';

const bodyText = document.body.innerText;
const lines = bodyText.split('\\n').map(l => l.trim()).filter(Boolean);

let cardType='', color='', cost='', life='';
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

const powM     = bodyText.match(/(\\d{3,6})\\s*Power/i);
const power    = powM ? powM[1] : '';
const ctrM     = bodyText.match(/[+]?(\\d{3,5})\\s*Counter/i);
const counter  = ctrM ? '+' + ctrM[1] : '';
const attrM    = bodyText.match(/\\b(Slash|Strike|Special|Ranged|Wisdom)\\b/i);
const attribute = attrM ? attrM[1] : '';

let subtypes = [];
for (const line of lines) {
    if (/^[A-Z][A-Za-z ]+(?: Pirates)?(\\/[A-Z][A-Za-z ]+)+$/.test(line)) {
        subtypes = line.split('/').map(s => s.trim());
        break;
    }
}

let effectLines=[], collecting=false, trigger='';
const stopWords=['USD','EUR','Buy','Tournament','Print','Language','Decks With'];
for (const line of lines) {
    if (/^\\[/.test(line) || line.includes('DON!!')) collecting = true;
    if (collecting) {
        if (stopWords.some(w => line.includes(w))) break;
        if (line.startsWith('[Trigger]')) { trigger=line.replace('[Trigger]','').trim(); continue; }
        effectLines.push(line);
    }
}
const effect = effectLines.join(' ').trim();

const rarM   = bodyText.match(/\\b(Leader|Common|Uncommon|Rare|Super Rare|Secret Rare|Special Card|Promo)\\b/);
const rarity = rarM ? rarM[1] : '';

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

return {name,image,cardType,color,cost,life,power,counter,
        attribute,subtypes,effect,trigger,rarity,variants};
```

}”””

def scrape_all(new_only: bool, output_path: Path):

```
existing_cards     = []
existing_set_codes = set()
existing_base_ids  = set()

if output_path.exists():
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            existing_cards     = data
            existing_set_codes = {c["set"]    for c in existing_cards if isinstance(c, dict)}
            existing_base_ids  = {c["baseId"] for c in existing_cards if isinstance(c, dict)}
            print(f"Loaded {len(existing_cards)} existing cards ({len(existing_set_codes)} sets)")
    except Exception as e:
        print(f"Warning: {e} — starting fresh")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        locale="en-US",
    )

    # Block ad/tracker requests only — card images still load normally
    ctx.route("**/*", lambda route: (
        route.abort() if should_block(route.request.url) else route.continue_()
    ))

    page = ctx.new_page()

    # ── Discover sets ─────────────────────────────────────────────────
    print("\nDiscovering sets...")
    all_sets = []

    for discover_url in [f"{BASE_URL}/cards", f"{BASE_URL}/cards/promos"]:
        ok = goto(page, discover_url)
        if not ok:
            print(f"  ✗ Could not load {discover_url}")
            continue
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            link = row.query_selector("a[href^='/cards/']")
            if not link:
                continue
            href  = (link.get_attribute("href") or "").strip()
            slug  = href.replace("/cards/", "")
            name  = link.inner_text().strip()
            if not slug or not name:
                continue
            m    = re.match(r"^([a-z]{2,5}\d{2})", slug)
            code = m.group(1).upper() if m else slug.upper()
            all_sets.append({"code": code, "slug": slug, "name": name})

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
        print("Nothing to scrape.")
        browser.close()
        return

    # ── Scrape each set ───────────────────────────────────────────────
    # Work on a copy so we preserve everything already saved
    all_cards = list(existing_cards)

    for set_info in unique_sets:
        slug  = set_info["slug"]
        code  = set_info["code"]
        sname = set_info["name"]
        print(f"\n── {code}: {sname}")

        ok = goto(page, f"{BASE_URL}/cards/{slug}")
        if not ok:
            print(f"  ✗ Could not load set page — skipping")
            continue

        card_ids = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('a[href^="/cards/"]').forEach(a => {
                const href = a.getAttribute('href');
                const m = href.match(/^\\/cards\\/([A-Z0-9]{2,6}-\\d{3}[A-Z]?)$/i);
                if (!m) return;
                results.push(m[1].toUpperCase());
            });
            const seen = new Set();
            return results.filter(x => { if(seen.has(x)) return false; seen.add(x); return true; });
        }""")

        print(f"  Found {len(card_ids)} cards")

        for i, card_id in enumerate(card_ids):
            if card_id in existing_base_ids:
                print(f"  [{i+1}/{len(card_ids)}] {card_id} ↷ already done")
                continue

            print(f"  [{i+1}/{len(card_ids)}] {card_id}", end="", flush=True)

            ok = goto(page, f"{BASE_URL}/cards/{card_id}")
            if not ok:
                print(" ✗ skipped after retries")
                continue

            try:
                card_data = page.evaluate(EXTRACT_JS, card_id)
            except Exception as e:
                print(f" ✗ parse error: {e}")
                continue

            def make_card(vid, variant_label, img):
                return {
                    "id":        vid,
                    "baseId":    card_id,
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
                    "image":     img,
                    "variant":   variant_label,
                }

            all_cards.append(make_card(card_id, "", card_data["image"]))
            existing_base_ids.add(card_id)

            for v in card_data["variants"]:
                v_ok  = goto(page, f"{BASE_URL}/cards/{card_id}?v={v['num']}")
                v_img = card_data["image"]  # fallback to base image
                if v_ok:
                    try:
                        v_img = page.evaluate("""() => {
                            const img = document.querySelector('img[src*="cdn.digitaloceanspaces"]');
                            return img ? img.src : '';
                        }""") or card_data["image"]
                    except Exception:
                        pass
                vid = f"{card_id}_p{v['num']}"
                all_cards.append(make_card(vid, v["label"], v_img))

            count = 1 + len(card_data["variants"])
            print(f" ✓  ({count} print{'s' if count > 1 else ''})")

            # Save after every card so a timeout never loses progress
            output_path.write_text(
                json.dumps(all_cards, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

    browser.close()

print(f"\n✓ Done — {len(all_cards)} total cards in {output_path}")
```

def main():
parser = argparse.ArgumentParser()
parser.add_argument(”–new-only”, action=“store_true”)
parser.add_argument(”–out”, default=“cards.json”)
args = parser.parse_args()
scrape_all(args.new_only, Path(args.out))

if **name** == “**main**”:
main()
