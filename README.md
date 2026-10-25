# Twoo's Treat Temple

An iPhone home-screen app that lists the food and drinks with no gluten ingredients at restaurants and coffee shops, built from each restaurant's own allergen guide, and shows how to order each one.

Live at **https://t-800isinevitable.github.io/gf-drinks/**

## Using the app

- **Pick a restaurant** by tapping its name at the top, or choose **All restaurants** to browse and search everything at once.
- **Filter** with the chips under the search box: menu sections for one restaurant, or restaurants when viewing all.
- **Show or hide by status:** everything shows until you choose. Tap any of the three buttons under the filters to show only those: **No gluten ingredients** (as served, or with any milk except those named), **Needs a change** (ask for a swap or change) and **Contains gluten** (whatever you order).
- **Warnings page:** each restaurant's own allergen warnings, word for word with page numbers (cross-contact, allergen updates, recipe changes, delivery, nutrition), plus what its guide doesn't tell you.
- **Wording:** the app says "no gluten ingredients", not "gluten free". In UK law "gluten free" means tested below 20 parts per million. Apart from Pho, which is accredited by Coeliac UK, these restaurants make no such claim, and even for Pho the app lists items by their ingredients and quotes Pho's own words.
- **Themes:** ⓘ → Appearance: Match phone, Light, Dark, Pink light, Pink dark.
- **Favourites:** open any item and tap **☆ Save**. The **★ Favourites** chip shows them. They're stored on your phone only. If a new guide puts a favourite on the Avoid list, or drops it, a warning stays at the top until you remove it.
- **Show staff:** open any item and tap **Show staff** for a large-print card with the item, how to order it and that you have coeliac disease.
- **What changed:** when a restaurant's guide is updated, a note lists what's new, what's gone, what's ordered differently and anything that now contains gluten. Changed items are marked in the list until the next guide.
- **Out-of-date warning:** if a restaurant's guide has passed its end date, a banner says so.
- **Share** sends a link to the restaurant you're viewing (for example `…/gf-drinks/#starbucks-uk`).
- **Search** hides the tips and notes while you type, so results sit just under the box. Searching for a milk that's ruled out ("oat milk latte") explains why and lists the drinks that are fine with another milk.
- **Menus in other languages** show each item in English with the original name underneath, so you can point to it when ordering. Searching works in either language.
- **Coeliac card:** a set of phrases to show staff (currently German), with a list of words to look for on menus. Works offline.
- **Berlin:** tap **Berlin** under the title to switch from the UK menus to places in Berlin that are all gluten free, by their own word or the Berlin coeliac support groups' (plus one pizzeria with a separate gluten free kitchen). Each place's tag says who makes the claim, and its row shows any warning, such as oats. Each place shows its own words with an English translation, the Berlin coeliac support groups' description, the app's notes (for example where oats are used), and its addresses with a map link. Tap **UK** to go back. Links work too: `…/gf-drinks/#berlin`.
- **Install:** in Safari, tap **•••** (or **Share** on older iPhones), then **Add to Home Screen**, and keep **Open as Web App** switched on (otherwise you get a bookmark). It works without signal using the last menus it downloaded.

## Updating a restaurant's menu

**Five Guys:** upload the new UK allergen, ingredient and nutrition guide PDF to `restaurants/five-guys-uk/guides/`. The newest date in the guide (FGUK_YYYYMMDD) is used. Anything with a gluten dot **or a "1"** (Five Guys' mark for "not suitable … due to manufacturing and preparation methods") goes in the Avoid list; a "2" (not suitable at breakfast time) shows as needing a change.

**Pret:** upload the new GB allergen guide PDF to `restaurants/pret-uk/guides/`. Pret's guides have no end date, so the app asks for a re-check 91 days after the "valid from" date (change `recheckDays` in `restaurant.json`).

**Starbucks:** upload the new Beverage Allergen Guide and Food Allergen Guide PDFs to `restaurants/starbucks-uk/guides/` (on GitHub: open the folder, then **Add file → Upload files → Commit changes**). Each reader takes the newest of its own kind (the food guide's cover says Food), so old guides can stay. About a minute later the app updates for everyone.

**Pho:** upload the new allergen guide PDF (linked as "Allergens" at the foot of phocafe.co.uk) to `restaurants/pho-uk/guides/`. Its "accurate as of" month is the version; the app asks for a re-check 183 days later.

**Blank Street:** upload the new UK allergen guide PDF (linked from blankstreet.com) to `restaurants/blank-street-uk/guides/`. The guide has no date in it, so keep the season in the file name (for example `...Autumn26.pdf`); the PDF's creation date is used as the version.

**Restaurants kept by hand (Knoops):** edit that restaurant's `menu.csv` and update the dates in its `restaurant.json`. Knoops' newest guide is from March 2024, so the app shows it as possibly out of date until a newer one appears.

**Berlin:** the list is kept by hand in `site/cities.json`, from the [Berlin glutenfrei](https://www.berlin-glutenfrei.de/glutenfrei-berlin-restaurants) list (run by the Berlin contacts of the German Coeliac Society) checked against each place's own website. Only places that say everything is gluten free, or that make gluten free food in a separate kitchen, are included. Set `claim` to who says it's gluten free: `place-all` (its own words), `list-all` (only the list says so), `place-part` (with a `claimLabel` such as "Says its cakes are gluten free") or `separate` (a separate gluten free kitchen). Quote each place's words exactly and add an English translation. Mark a place `"status": "unconfirmed"` with a `statusNote` if its opening can't be confirmed, and put anything to watch for (such as oats) in `caution`, with a short `flag` for the row (such as "Has oats: ask"). Update `checked` after each review. The app warns once `recheckDays` (90) have passed.

**Reminders:** each morning `.github/workflows/guide-reminders.yml` opens an issue for any guide that has ended or ends within three weeks, and for a city list due a re-check. Close the issue if there's no newer guide yet; you won't be reminded again until the end date changes.

## Adding a menu from the app

1. Open **ⓘ → Add a menu**.
2. The first time, paste a GitHub key (the app shows how to create one; it only needs **Contents: Read and write** on this repository). It's stored on that phone only.
3. Enter the restaurant and city, choose the PDF or photos, and tap **Upload**. Files go into `inbox/`.
4. Every day a scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md`: it reads each upload in any language, works out the gluten free options conservatively, translates them, and opens a **pull request**.
5. Check the pull request (it lists the items it's least sure about and anything left out) and tap **Merge** in the GitHub app to publish. Nothing goes live before that.

## Adding a restaurant by hand

Each restaurant is a folder in `restaurants/`. The folder name becomes its id in the app (lower case with hyphens, such as `pret-uk`).

**Option 1: fill in a spreadsheet (works for any restaurant)**

1. Copy `restaurants/_template` to a new folder, for example `restaurants/pret-uk`.
2. Edit `restaurant.json`: name, type, what it covers, `area` (city or country), `language` (two-letter code such as `de`), the official allergen page, and under `guide` the source you checked, its date (`version`) and when to re-check it (`validUntil`).
3. Fill in `menu.csv`, one row per item. The `order` column says how to order it:

   | order | Meaning | Also fill in |
   | --- | --- | --- |
   | `asis` | Gluten free as listed | |
   | `any` | Gluten free with any of the options | `ok` |
   | `except` | Gluten free except with some options | `ok`, `not` |
   | `swap` | Normally comes with an option containing gluten | `ok`, `not`, `standard` |
   | `modify` | Gluten free only with a change | `note`, e.g. "No croutons" |
   | `avoid` | Contains gluten whatever you order | `contains`, e.g. "wheat" |

   Separate several options with `;` (for example `skimmed;soya`). For menus in another language, write `name` and `section` in English and put the menu's own wording in `original` and `section_original`.
4. Commit. The build checks the file and refuses to publish if anything is missing.

**Option 2: an automatic reader**

If a restaurant publishes a regular PDF guide, a reader can be written for it (like `tools/adapters/starbucks_uk_pdf.py`) so new guides are picked up just by uploading the PDF. Send the guide to Claude and ask for a reader. Set `"reader"` in `restaurant.json` to the new reader's name.

## How "gluten free" is decided

- **Starbucks:** every row of the guide is read. An item or milk version counts as containing gluten if its **Allergens** column or its **ingredient list** names, in bold capitals, any of wheat, oats, barley, rye, spelt, kamut, gluten or malt. Oats are included because the guide lists them under "cereals containing gluten". If the two places disagree, the item is left out.
- **Starbucks food:** the same rule as the drinks, using each product's ingredients and its Allergens column.
- **Pho:** the guide's "Cereals containing gluten" column. A dot means avoid. A dot on a pink cell means the restaurant can remove the gluten on request, so the app says what to ask for. A cereal named without a dot (Daura Damm, a beer made from barley malt with the gluten removed) is treated as containing gluten. Pho is accredited by Coeliac UK, and its own words about that are on the Warnings page.
- **Blank Street:** each item's ingredients and its "May Contain" line. "May contain" oats or gluten counts as gluten, which puts every milk drink on the Avoid list: the dairy versions may contain oat, and the oat versions contain it.
- **Hand-kept restaurants (Knoops):** whatever is entered in `menu.csv`, checked against the restaurant's allergen information. For Knoops, oats (including gluten free oats) and "MCT" (may contain traces) count as gluten.

Restaurants prepare food in shared kitchens, so nothing is guaranteed gluten free. The app says this too.

## Publishing and safety checks

Every change to the repository runs `.github/workflows/publish.yml`, which:

1. downloads the menus that are live now (`tools/fetch_previous.py`), so the build can say what changed in a new guide,
2. runs the unit tests (`tests/`) and builds every restaurant (`tools/build.py`),
3. checks the results (`tools/check.py`): every item has a valid ordering tag, options are listed where needed, nothing is both safe and unsafe, and each restaurant has items,
4. compares each menu with its snapshot (`tools/snapshot.py`, saved in `tests/snapshots/`), so a change to a reader can't quietly change what the same guide gives. A new guide is reported, not failed,
5. opens the app in a real browser at iPhone size, in light and dark (`tools/ui_check.py`): no errors, nothing wider than the screen, and the buttons work,
6. publishes the app to GitHub Pages.

If any step fails, nothing is published and the live app keeps its previous menus. The **Actions** tab shows each run's results, including how many items each restaurant has. Pull requests run the same checks (`.github/workflows/checks.yml`) without publishing.

When a reader's output is meant to change (a fix, or a new guide), check the differences against the guide, then run `python tools/snapshot.py --update` and commit the snapshots.

Free GitHub accounts can publish Pages sites from public repositories only, so everything here, including uploaded guides, is publicly visible.

## Running it locally

```
pip install -r tools/requirements.txt -r tools/requirements-dev.txt
python -m playwright install chromium            # once, for the UI checks
python tools/fetch_previous.py                   # optional: the live menus, to see what changed
python tools/build.py && python tools/check.py   # writes site/data/
python tools/snapshot.py && python tools/ui_check.py
python -m http.server -d site 8000               # open http://localhost:8000
```

## Files

- `restaurants/<id>/`: one folder per restaurant (`restaurant.json`, plus guides or `menu.csv`)
- `restaurants/_template/`: copy this to add a restaurant by hand
- `tools/build.py`: builds every restaurant into `site/data/`
- `tools/check.py`: safety checks run before publishing
- `tools/changes.py`, `tools/fetch_previous.py`: what changed since the live menus
- `tools/snapshot.py`, `tests/snapshots/`: each reader's output, to catch unintended changes
- `tools/ui_check.py`: the app in a real browser at iPhone size
- `tools/reminders.py`: guides ending soon (opens GitHub issues each morning)
- `tools/adapters/`: readers for each kind of allergen guide
- `tools/SCAN_INSTRUCTIONS.md`: what the daily scan does with uploads
- `inbox/`: uploads waiting to be scanned
- `site/phrases.json`: gluten free card phrases (add a language here)
- `site/cities.json`: hand-checked places in other cities (Berlin)
- `site/`: the app (HTML, CSS, JavaScript, offline support, icons)

Unofficial. Not affiliated with any restaurant.
