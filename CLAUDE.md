# Twoo's Treat Temple (repo: gf-drinks)

An iPhone home-screen web app (PWA) listing food and drinks with **no gluten ingredients** at UK restaurants and coffee shops, built from each restaurant's published allergen guide. Used by someone with coeliac disease, so accuracy beats completeness. Live at https://t-800isinevitable.github.io/gf-drinks/

## How it fits together

- `restaurants/<id>/restaurant.json` names a **reader** (`tools/adapters/<reader>.py`) plus display details, `tips`, `gaps` (what the guide doesn't tell a coeliac) and `recheckDays`.
- Readers: `starbucks_uk_pdf`, `pret_uk_pdf`, `five_guys_uk_pdf` (automatic, from PDFs in `guides/`; newest edition wins) and `manual_csv` (hand-kept `menu.csv`, see `restaurants/_template/`).
- `tools/adapters/notices.py` extracts each guide's own warnings word for word for the Warnings page.
- `tools/build.py` builds `site/data/restaurants.json` and `site/data/r/<id>.json`; `tools/check.py` validates. `site/data/` is generated, not committed.
- `site/` is the app: `index.html`, `app.js`, `styles.css`, `sw.js` (offline, network-first; bump `CACHE` when shell files change), `manifest.webmanifest`, `phrases.json` (coeliac card).
- `.github/workflows/publish.yml` builds, checks and deploys to GitHub Pages on every push to `main` (pushes touching only `inbox/` are ignored).
- `inbox/` receives uploads from the app's Add menu button. A daily scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md` and opens a pull request per upload for the owner to approve.

## Gluten rules (don't loosen these)

- Gluten = wheat, rye, barley, **oats**, spelt, kamut, or "gluten"/malt, as the guide marks them. Oats count because the guides list them as gluten cereals.
- When two sources in a guide disagree (e.g. allergen column vs ingredients), treat the item as containing gluten and record a warning.
- Five Guys "1" (not suitable due to preparation) in the gluten column = Avoid, with the reason shown.
- Never call anything "gluten free". Say "no gluten ingredients". None of the guides make gluten free claims or claim to test for gluten.
- Readers must fail the build (`SystemExit`) rather than publish if the layout looks different (missing headings, unmatched marks, too few rows). A failed build keeps the previous live menus.
- Quote restaurant warnings word for word; don't paraphrase them as if they were the restaurant's words.

## Working conventions

- **British English, no em-dashes**, plain warm wording in anything user-facing (app text, README, PR descriptions).
- Changes go through a branch and pull request, then merge; the publish workflow deploys from `main`.
- Before publishing: `pip install -r tools/requirements.txt && python tools/build.py && python tools/check.py`, then preview with `python -m http.server -d site 8000` at iPhone width (light and dark). Check horizontal overflow and the browser console.
- When adding a restaurant from a new PDF layout, write a reader, compare its output row by row against the rendered pages, and add a cross-check between the guide's own sources where possible.
- Verify facts before stating them; label educated guesses as guesses.

## Known gaps

- Starbucks guides cover drinks only (food is a separate guide not yet added).
- Not yet tested on a real device: installing, in-app upload with a real GitHub key, the first daily scan of a real menu. The German coeliac card hasn't been checked by a native speaker.
