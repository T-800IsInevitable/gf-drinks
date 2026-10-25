# Twoo's Treat Temple (repo: gf-drinks)

An iPhone home-screen web app (PWA) listing food and drinks with **no gluten ingredients** at UK restaurants and coffee shops, built from each restaurant's published allergen guide. Used by someone with coeliac disease, so accuracy beats completeness. Live at https://t-800isinevitable.github.io/gf-drinks/

## How it fits together

- `restaurants/<id>/restaurant.json` names a **reader** (`tools/adapters/<reader>.py`), or several as `"readers": [...]` merged into one menu (Starbucks drinks + food), plus display details, `tips`, `gaps` (what the guide doesn't tell a coeliac) and `recheckDays`.
- Readers: `starbucks_uk_pdf`, `starbucks_uk_food_pdf`, `pret_uk_pdf`, `five_guys_uk_pdf`, `pho_uk_pdf`, `blank_street_uk_pdf` (automatic, from PDFs in `guides/`; newest edition wins) and `manual_csv` (hand-kept `menu.csv`, see `restaurants/_template/`; used for Knoops).
- `tools/adapters/notices.py` extracts each guide's own warnings word for word for the Warnings page, including an "accreditation" kind for a guide's own gluten free claim.
- `tools/build.py` builds `site/data/restaurants.json` and `site/data/r/<id>.json`; `tools/check.py` validates. `site/data/` is generated, not committed.
- `tools/fetch_previous.py` downloads the live menus into `.previous/`; `tools/changes.py` then records what changed in each new guide ("changes"), carried forward until the next guide. The app shows it, and warns about favourites that are now to avoid or gone.
- `tools/snapshot.py` compares each menu with `tests/snapshots/<id>.txt` (same guide only); `tools/ui_check.py` drives the app in Playwright at iPhone size, light and dark; `tests/` has unit tests. `.github/workflows/checks.yml` runs all of it on pull requests; `guide-reminders.yml` opens an issue for guides ending within three weeks.
- `site/` is the app: `index.html`, `app.js`, `styles.css`, `sw.js` (offline, network-first; bump `CACHE` when shell files change), `manifest.webmanifest`, `phrases.json` (coeliac card), `cities.json` (hand-checked places in other cities, shown when the header switch is on that city instead of UK; validated by `check.py`, re-check reminders from `reminders.py`).
- Berlin places come from the berlin-glutenfrei.de list (Berlin contacts of the German Coeliac Society), each checked against the place's own website. Include only places that say everything is gluten free, or that have a separate gluten free kitchen. Their claims are quoted (with the app's translation), never adopted. Tag each place by who makes the claim (`claim`: place-all, list-all, place-part, separate). Put oats or wheat starch in `caution` with a row `flag`, and mark anything not confirmed open as `unconfirmed`. A green tag only for a place's own all-gluten-free claim with no caution. Opening `hours` (Mon to Sun) only from the place's own website; leave them out rather than guess. Search covers name, type, description and area, not street names.
- `.github/workflows/publish.yml` builds, checks and deploys to GitHub Pages on every push to `main` (pushes touching only `inbox/` are ignored).
- `inbox/` receives uploads from the app's Add menu button. A daily scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md` and opens a pull request per upload for the owner to approve.

## Gluten rules (don't loosen these)

- Gluten = wheat, rye, barley, **oats**, spelt, kamut, or "gluten"/malt, as the guide marks them. Oats count because the guides list them as gluten cereals.
- When two sources in a guide disagree (e.g. allergen column vs ingredients), treat the item as containing gluten and record a warning.
- Five Guys "1" (not suitable due to preparation) in the gluten column = Avoid, with the reason shown.
- "May contain" gluten or oats (Blank Street's "May Contain" lines, Knoops' "MCT") = Avoid, with the reason shown. Gluten free oats still count as oats.
- Never call anything "gluten free". Say "no gluten ingredients". Pho is the exception that makes a claim (Coeliac UK accredited): quote its words, don't adopt them. The other guides make no gluten free claim.
- Where the app adds its own caution to a restaurant's data (for example Knoops' cannoli), label it as the app's, not the restaurant's.
- Readers must fail the build (`SystemExit`) rather than publish if the layout looks different (missing headings, unmatched marks, too few rows). A failed build keeps the previous live menus.
- Quote restaurant warnings word for word; don't paraphrase them as if they were the restaurant's words.

## Working conventions

- **British English, no em-dashes**, plain warm wording in anything user-facing (app text, README, PR descriptions).
- Changes go through a branch and pull request, then merge; the publish workflow deploys from `main`.
- Before publishing: `pip install -r tools/requirements.txt -r tools/requirements-dev.txt`, then `python tools/build.py && python tools/check.py && python tools/snapshot.py && python tools/ui_check.py` (the last needs `python -m playwright install chromium` once). `ui_check.py --shots DIR` saves screenshots to look at.
- When a reader's output changes on purpose, check the snapshot diff against the guide, then `python tools/snapshot.py --update`. Never update snapshots just to make the check pass.
- When adding a restaurant from a new PDF layout, write a reader, compare its output row by row against the rendered pages, and add a cross-check between the guide's own sources where possible. Make the reader stop the build on anything it can't place (stray marks, two drinks run together).
- Verify facts before stating them; label educated guesses as guesses.

## Known gaps

- Hotel Chocolat publishes no café allergen guide online; add it from photos of the in-café information via the app's Add menu.
- Knoops' newest guide is from March 2024, so it shows as possibly out of date.
- Not yet tested on a real device: installing, in-app upload with a real GitHub key, the first daily scan of a real menu, the reminder workflow's first issue. The German coeliac card hasn't been checked by a native speaker.
