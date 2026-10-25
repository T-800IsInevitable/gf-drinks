# Twoo's Treat Temple

An iPhone home-screen app that lists the gluten free food and drinks at restaurants and coffee shops, built from each restaurant's own allergen guide, and shows how to order each one.

Live at **https://t-800isinevitable.github.io/gf-drinks/**

## Using the app

- **Pick a restaurant** by tapping its name at the top, or choose **All restaurants** to browse and search everything at once.
- **Filter** with the chips under the search box: menu sections for one restaurant, or restaurants when viewing all.
- **Show or hide by status:** the three buttons under the filters toggle **Straight up** (gluten free as served, or with any milk except those named), **Needs change** (ask for a swap or change) and **Gluten** (contains gluten whatever you order).
- **Themes:** ⓘ → Appearance: Match phone, Light, Dark, Pink light, Pink dark.
- **Favourites:** open any item and tap **☆ Save**. The **★ Favourites** chip shows them. They're stored on your phone only.
- **Out-of-date warning:** if a restaurant's guide has passed its end date, a banner says so.
- **Share** sends a link to the restaurant you're viewing (for example `…/gf-drinks/#starbucks-uk`).
- **Menus in other languages** show each item in English with the original name underneath, so you can point to it when ordering. Searching works in either language.
- **Gluten free card:** a set of phrases to show staff (currently German), with a list of words to look for on menus. Works offline.
- **Install:** in Safari, tap **•••** (or **Share** on older iPhones), then **Add to Home Screen**, and keep **Open as Web App** switched on (otherwise you get a bookmark). It works without signal using the last menus it downloaded.

## Updating a restaurant's menu

**Pret:** upload the new GB allergen guide PDF to `restaurants/pret-uk/guides/`. Pret's guides have no end date, so the app asks for a re-check 91 days after the "valid from" date (change `recheckDays` in `restaurant.json`).

**Starbucks:** upload the new Beverage Allergen Guide PDF to `restaurants/starbucks-uk/guides/` (on GitHub: open the folder, then **Add file → Upload files → Commit changes**). The newest version date is used, so old guides can stay. About a minute later the app updates for everyone.

**Restaurants kept by hand:** edit that restaurant's `menu.csv` and update the dates in its `restaurant.json`.

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
- **Hand-kept restaurants:** whatever is entered in `menu.csv`, checked against the restaurant's allergen information.

Restaurants prepare food in shared kitchens, so nothing is guaranteed gluten free. The app says this too.

## Publishing and safety checks

Every change to the repository runs `.github/workflows/publish.yml`, which:

1. builds every restaurant (`tools/build.py`),
2. checks the results (`tools/check.py`): every item has a valid ordering tag, options are listed where needed, nothing is both safe and unsafe, and each restaurant has items,
3. publishes the app to GitHub Pages.

If any step fails, nothing is published and the live app keeps its previous menus. The **Actions** tab shows each run's results, including how many items each restaurant has.

Free GitHub accounts can publish Pages sites from public repositories only, so everything here, including uploaded guides, is publicly visible.

## Running it locally

```
pip install -r tools/requirements.txt
python tools/build.py && python tools/check.py   # writes site/data/
python -m http.server -d site 8000               # open http://localhost:8000
```

## Files

- `restaurants/<id>/`: one folder per restaurant (`restaurant.json`, plus guides or `menu.csv`)
- `restaurants/_template/`: copy this to add a restaurant by hand
- `tools/build.py`: builds every restaurant into `site/data/`
- `tools/check.py`: safety checks run before publishing
- `tools/adapters/`: readers for each kind of allergen guide
- `tools/SCAN_INSTRUCTIONS.md`: what the daily scan does with uploads
- `inbox/`: uploads waiting to be scanned
- `site/phrases.json`: gluten free card phrases (add a language here)
- `site/`: the app (HTML, CSS, JavaScript, offline support, icons)

Unofficial. Not affiliated with any restaurant.
