# One Piece TCG Tracker

A free, open-source collection tracker for the One Piece Trading Card Game. Works in any browser, installs as a home screen app on iPhone and Android.

**[▶ Open the app](https://yourusername.github.io/onepiece-tcg-tracker)**

---

## Features

- **Search** the full card database by name, card ID, subtype or keyword — fully offline once loaded
- **Advanced filters** — colour, card type, attribute, counter value, effect text, cost and power range
- **Collection tracking** — mark cards as owned with quantity control
- **Wantlist** — track cards you're looking for, with Cardmarket export
- **Decklists** — structured 51-card decks (1 Leader + 50 cards) with validation and ownership cross-reference
- **Personal collections** — free-form groups for themes, character collections, favourite art, etc.
- **Card scanning** — uses your camera and on-device OCR to read the card ID — no image uploaded or stored
- **Cardmarket links** — every card links directly to Cardmarket Europe
- **Cardmarket wantlist export** — paste directly into Cardmarket's wantlist importer
- **Auto-save** — collection saves as a CSV on your device when you close the app

---

## How it works

The app is a single HTML file (`index.html`) that loads card data from `cards.json` in the same repository. A weekly GitHub Actions workflow fetches the latest card data and updates `cards.json` automatically — so the database stays current without any manual work.

```
onepiece-tcg-tracker/
├── index.html          ← the app
├── cards.json          ← card database (auto-updated weekly)
├── README.md
└── .github/
    └── workflows/
        └── update-cards.yml  ← weekly database updater
```

---

## Setup

### 1. Fork or create the repository

Create a new public GitHub repository and upload these three items:
- `index.html`
- `cards.json`
- `.github/workflows/update-cards.yml`

### 2. Enable GitHub Pages

Go to **Settings → Pages → Source → Deploy from branch → main / (root)** → Save.

Your app will be live at `https://yourusername.github.io/repository-name` within a minute or two.

### 3. Run the first database update

The database starts empty. Trigger the first update manually:

**Actions → Update card database → Run workflow**

This takes a few minutes and fetches all cards from the OPTCG API via a real browser. Once complete, `cards.json` will be committed and the app will have full card data.

After that, the workflow runs every Monday at 6am UTC automatically.

### 4. Update the app link

Edit this README and replace `yourusername` and `onepiece-tcg-tracker` with your actual GitHub username and repository name.

---

## Installing on iPhone

1. Open the app URL in **Safari**
2. Tap the **Share button** (box with arrow)
3. Tap **Add to Home Screen**

The app icon will appear on your home screen and behaves like a native app.

---

## Supported sets

| Category | Sets |
|---|---|
| Main sets | OP01–OP15 |
| Extra Boosters | EB01–EB04 |
| Premium Boosters | PRB01, PRB02 |
| Promotional cards | P-cards |
| Starter Decks | ST01–ST21 |

---

## Privacy

- Your collection data is stored only on your device as a CSV file
- Card images load from the official Bandai One Piece Card Game website
- Card scanning uses on-device OCR — photos are never uploaded
- No analytics, no tracking, no accounts required

---

## Contributing

Contributions are welcome. Open an Issue to report a bug or suggest a feature, or fork the repository and submit a Pull Request. No developer experience required — corrections to card data, set names, or this README are just as valuable as code changes.

---

## Data sources

- Card data: [OPTCG API](https://www.optcgapi.com) — community-maintained
- Card images: [en.onepiece-cardgame.com](https://en.onepiece-cardgame.com) — official Bandai website
- Market links: [Cardmarket](https://www.cardmarket.com/en/OnePiece)

---

## Licence

MIT. One Piece and all related names are the property of Eiichiro Oda / Shueisha / Toei Animation / Bandai. This project is fan-made and not affiliated with or endorsed by Bandai.
