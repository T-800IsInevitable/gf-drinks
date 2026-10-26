# Daily inbox scan: instructions for Claude

You are processing menus uploaded to `inbox/` in this repository (T-800IsInevitable/gf-drinks). The output is a **pull request** that the owner reviews and merges. Never push to `main`.

## 1. Check for work

- List `inbox/`. Ignore `README.md` and `.keep-alive` (a monthly marker file, not an upload). If there are no upload folders, stop: report "Inbox empty" and do nothing else.
- Process each upload folder separately, one branch and one pull request per restaurant.
- If a pull request for that upload is already open (search open PRs for the folder name), skip it.

## 2. Read the upload

- `upload.json` has `restaurant`, `area`, `notes`, `uploadedAt`. Missing fields: infer from the document and say so in the PR.
- Read every page of every file (PDF pages, photos). Use the PDF reading tools; render pages to images when tables don't extract cleanly.
- If it is a **Starbucks UK beverage allergen guide**, don't hand-build it: move the PDF to `restaurants/starbucks-uk/guides/` and let the existing reader handle it.

## 3. Decide what is gluten free: be conservative

The app is used by someone who must avoid gluten. A wrong "gluten free" is far worse than leaving an item out.

- Use the **original-language** allergen information to decide. Translate only for display.
- Contains gluten if the item lists any cereal containing gluten: wheat, rye, barley, oats, spelt, kamut, or their names in the menu's language. German: Weizen, Roggen, Gerste, Hafer, Dinkel, Kamut, Emmer, Einkorn, Grünkern, glutenhaltiges Getreide, Gluten, Malz, Paniermehl. French: blé, seigle, orge, avoine, épeautre. Spanish: trigo, centeno, cebada, avena, espelta. Italian: frumento/grano, segale, orzo, avena, farro.
- Many German menus mark allergens with letter codes. **Use the document's own legend.** Don't assume what a code means if the legend isn't included. In that case don't list anything as gluten free; explain in the PR.
- "May contain" / "kann Spuren enthalten" / traces: leave the item out of the gluten free list and mention it in the PR.
- Only mark an item gluten free when the document clearly shows no gluten cereal for it. If unclear, unreadable or missing, leave it out and list it in the PR under "Not listed (unclear)".
- Use `swap` / `except` / `any` only when the document shows the gluten free option explicitly (e.g. a gluten free bun). Use `modify` only when the document says the change makes it gluten free.
- Items that clearly contain gluten go in as `avoid` with `contains` filled in.

## 4. Build the restaurant

- Folder: `restaurants/<id>/` where `<id>` is lower case with hyphens, including the area for chains (e.g. `five-guys-berlin`). If the folder already exists, update it.
- Copy `restaurants/_template/`, then fill in:
  - `restaurant.json`: `name`, `type`, `covers`, `area`, `language` (two-letter code), `reader: "manual_csv"`, `optionLabel`, `officialUrl` if known (only real URLs you found in the document or by search; never guess), `guide.source` (the uploaded file name and document title), `guide.version` (the document's own date if shown, otherwise the upload date), `guide.validUntil` (the document's end date if shown, otherwise 3 months after `version`), and `tips` (1 to 3 short ordering tips taken from the document), `notices` (every warning printed in the document, **word for word**, each as `{"label": …, "text": …, "page": …}`; labels: Allergen updates, Cross-contact, Recipes and ingredients, What the guide covers, Delivery, Vegan and dietary labels, Nutrition), `gaps` (what the document doesn't tell a coeliac, e.g. no "may contain" information, or that it never claims "gluten free"), and `reviewed: {"by": "pending owner review", "date": <today>}`.
  - `menu.csv`: one row per item. `name` and `section` in **English**. `original` and `section_original` in the menu's language, exactly as printed. `page` = page number.
- Keep the uploaded files: move the upload folder to `restaurants/<id>/source/<upload folder name>/`. This empties it from `inbox/` in the same PR.
- Run `pip install -r tools/requirements.txt` if needed, then `python tools/build.py && python tools/check.py`. Fix any errors before opening the PR.

## 5. Open the pull request

- Branch: `scan/<id>-<YYYY-MM-DD>`. Commit message: `Add <name> (<area>) from uploaded menu`.
- PR title: `Add <name> (<area>): <n> gluten free, <m> to avoid`.
- PR body, in plain British English:
  - What was uploaded and what the document is (title, date, language).
  - Counts: gluten free / avoid / not listed.
  - **Please check:** the 5 items you're least sure about, with page numbers.
  - **Not listed (unclear):** every item left out and why.
  - Any assumptions (e.g. validUntil defaulted to 3 months).
  - Reminder: "Merge to publish. Nothing is live until then."
- Use the GitHub REST API (`gh api repos/T-800IsInevitable/gf-drinks/pulls -f title=… -f head=… -f base=main -f body=…`). GraphQL isn't available.

## 6. Report

Finish with a short summary: uploads processed, PR links, anything that needs the owner's attention.
