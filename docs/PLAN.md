# Development Plan — OP TCG Tracker

This file documents the current state of the project and what needs to be built next. It exists so any contributor (human or AI assistant) can get full context quickly by reading this file.

---

## Project overview

An open source One Piece TCG collection tracker for European players. Built as a single HTML file on GitHub Pages. Non-commercial, fan-made.

**Live app:** https://r1valblue.github.io/OPTCGCollectionTracker
**Repository:** https://github.com/r1valblue/OPTCGCollectionTracker

---

## Current status

| File | Status |
|------|--------|
| `index.html` | Partially working — broken images, no card names, broken scan |
| `cards.json` | Stub entries only — no real card data |
| `.github/workflows/update-cards.yml` | Generates stubs only — no scrape |
| `docs/README.md` | Complete |

---

## What needs to be done

### Priority 1 — Build the card database

Scrape [Limitless One Piece](https://onepiece.limitlesstcg.com/cards) to build a complete `cards.json`.

**Why Limitless:**
- Complete data — all sets, all rarities, all variants
- Images accessible cross-origin (Bandai CDN blocks browser requests)
- Non-commercial fan site using Bandai-copyright data, same as this project
- Card pages are clean and scrapeable with Playwright

**Data fields needed per card:**

```json
{
  "id": "OP01-001",
  "baseId": "OP01-001",
  "name": "Roronoa Zoro",
  "set": "OP01",
  "setName": "Romance Dawn",
  "rarity": "Leader",
  "color": "Red",
  "type": "Leader",
  "cost": "5",
  "power": "5000",
  "counter": "",
  "attribute": "Slash",
  "subtypes": ["Supernovas", "Straw Hat Crew"],
  "effect": "[DON!! x1] [Your Turn] All of your Characters gain +1000 power.",
  "trigger": "",
  "image": "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/one-piece/OP01/OP01-001_EN.webp",
  "variant": ""
}
```

**Limitless URL patterns:**
- Set page: `https://onepiece.limitlesstcg.com/cards/OP01`
- Card page: `https://onepiece.limitlesstcg.com/cards/OP01-001`
- Alt art: `https://onepiece.limitlesstcg.com/cards/OP01-001?v=2`

**Approach:**
1. Fetch each set page to get list of all card IDs and variants
2. Fetch each individual card page to get full data
3. Write to `cards.json`
4. Commit to repository

This is a one-time operation that can take as long as needed. The GitHub Actions job timeout can be set to 6 hours if necessary.

**Sets to scrape:**
- Main: OP01–OP15
- Extra Boosters: EB01–EB04
- Premium Boosters: PRB01–PRB02
- Starter Decks: ST01–ST21
- Promotional: all P-cards listed on Limitless

---

### Priority 2 — Weekly update workflow

After the initial scrape, the weekly workflow should:
1. Check which sets Limitless currently lists
2. Compare against sets already in `cards.json`
3. Only scrape new sets
4. Append new cards and commit if changed

This keeps the weekly run fast (seconds for quiet weeks, minutes when a new set drops).

---

### Priority 3 — Rebuild index.html

**Current problems:**
- Images broken — Bandai CDN blocks cross-origin requests
- Cardmarket links broken — searching by ID alone returns nothing
- OCR scanning broken
- No card names or text

**What the rebuilt app needs:**

#### Browse page
- Card grid view for selected set
- Images from Limitless CDN
- Green border = owned, yellow border = wanted
- Tap card to open detail popup

#### Card detail popup
- Full card image
- Complete effect text (no truncation)
- All variants listed with individual + Own it / ☆ Want buttons
- Cardmarket search link: `https://www.cardmarket.com/en/OnePiece/Products/Search?searchString=Roronoa+Zoro+OP01`
- Limitless link: `https://onepiece.limitlesstcg.com/cards/OP01-001`

#### Advanced search
- Filter by: colour, card type, attribute, subtype contains, effect text contains, cost range, power range
- Subtype matching: partial match ("Whitebeard" matches "Whitebeard Pirates" and "Whitebeard Pirate Allies")

#### Collection tracking
- Per-variant ownership (base art and alt art tracked separately)
- Quantity controls

#### Wantlist
- Per-variant
- Cardmarket export: formatted for Cardmarket wantlist import

#### Decklists
- 1 Leader + 50 cards = 51 total
- Max 4 copies of any non-Leader card
- Cross-reference against owned cards (flag but allow)
- Progress bar

#### Personal collections
- Free-form named groups, no card limit

#### OCR scanning
- Tesseract.js loaded lazily (only when scan button tapped)
- Two CDN fallbacks
- Preprocesses image: crops bottom-right corner, greyscale, contrast boost
- Matches OP/ST/EB/PRB/P card ID patterns
- Falls back to manual ID entry

#### Save / load
- CSV auto-download on page close / visibility hidden
- One-tap load on startup
- Same format as current (backwards compatible)

#### Proxy print feature
- Card-by-card only (not batch set printing)
- Uses Limitless image
- Generates printable layout at standard card size (63mm × 88mm / 2.5" × 3.5")
- Clear disclaimer in UI: "For personal playtest use only — not for sale or tournament play"

---

## Technical constraints

| Constraint | Detail |
|-----------|--------|
| No runtime API calls | All data from cards.json on same domain |
| Cross-origin images | Must use Limitless CDN, not Bandai CDN |
| Cardmarket links | Search format: name + set code |
| Saving | CSV file, auto on close, manual in Save tab |
| Scanning | On-device OCR only, no uploads |

---

## Disclaimer (must appear in both app and README)

> Card images and text are copyright Eiichiro Oda/Shueisha, Toei Animation and/or Bandai. This project is not produced by, endorsed by, supported by, or affiliated with any of those copyright holders. For personal, non-commercial use only.

---

## Variant ID convention

| Card | ID |
|------|----|
| Base card | `OP01-001` |
| Alt art 1 | `OP01-001_p1` |
| Alt art 2 | `OP01-001_p2` |

`baseId` always strips the `_pN` suffix. All variants share the same `baseId` and are grouped together in the UI but tracked individually in the collection.

---

## Notes for AI assistants picking this up

- Read this file first, then check the current state of `index.html` and `cards.json`
- The owner is a non-developer — explain steps clearly and avoid jargon
- The project is hosted at the repo root; `docs/README.md` was moved there deliberately so GitHub Pages serves `index.html` not the README
- Prefer clean full rewrites over incremental patches when the file has accumulated many partial edits
- Test assumptions about external APIs before writing code that depends on them
