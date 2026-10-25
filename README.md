# GF Menus

An iPhone home-screen app that lists the gluten free options at restaurants and coffee shops, built from each restaurant's own allergen guide, and shows how to order each one.

Live at **https://t-800isinevitable.github.io/gf-drinks/**

## Using the app

- **Pick a restaurant** by tapping its name at the top, or choose **All restaurants** to browse and search everything at once.
- **Filter** with the chips under the search box: menu sections for one restaurant, or restaurants when viewing all.
- **Favourites:** open any item and tap **☆ Save**. The **★ Favourites** chip shows them. They're stored on your phone only.
- **Out-of-date warning:** if a restaurant's guide has passed its end date, a banner says so.
- **Share** sends a link to the restaurant you're viewing (for example `…/gf-drinks/#starbucks-uk`).
- **Install:** open the link in Safari, tap **Share**, then **Add to Home Screen**. It works without signal using the last menus it downloaded.

## Updating a restaurant's menu

**Starbucks:** upload the new Beverage Allergen Guide PDF to `restaurants/starbucks-uk/guides/` (on GitHub: open the folder, then **Add file → Upload files → Commit changes**). The newest version date is used, so old guides can stay. About a minute later the app updates for everyone.

**Restaurants kept by hand:** edit that restaurant's `menu.csv` and update the dates in its `restaurant.json`.

## Adding a restaurant

Each restaurant is a folder in `restaurants/`. The folder name becomes its id in the app (lower case with hyphens, such as `pret-uk`).

**Option 1: fill in a spreadsheet (works for any restaurant)**

1. Copy `restaurants/_template` to a new folder, for example `restaurants/pret-uk`.
2. Edit `restaurant.json`: name, type, what it covers, the official allergen page, and under `guide` the source you checked, its date (`version`) and when to re-check it (`validUntil`).
3. Fill in `menu.csv`, one row per item. The `order` column says how to order it:

   | order | Meaning | Also fill in |
   | --- | --- | --- |
   | `asis` | Gluten free as listed | |
   | `any` | Gluten free with any of the options | `ok` |
   | `except` | Gluten free except with some options | `ok`, `not` |
   | `swap` | Normally comes with an option containing gluten | `ok`, `not`, `standard` |
   | `modify` | Gluten free only with a change | `note`, e.g. "No croutons" |
   | `avoid` | Contains gluten whatever you order | `contains`, e.g. "wheat" |

   Separate several options with `;` (for example `skimmed;soya`).
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
- `site/`: the app (HTML, CSS, JavaScript, offline support, icons)

Unofficial. Not affiliated with any restaurant.
