# Restaurants

One folder per restaurant. The folder name becomes the restaurant's id in the app (lower case, hyphens, e.g. `starbucks-uk`).

Each folder needs a `restaurant.json` saying which **reader** understands that restaurant's allergen information:

- `starbucks_uk_pdf` and `starbucks_uk_food_pdf`: put the Starbucks UK beverage and food allergen guide PDFs in `guides/`. Each takes the newest guide of its kind.
- `pret_uk_pdf`, `five_guys_uk_pdf`, `pho_uk_pdf`, `blank_street_uk_pdf`: put that restaurant's allergen guide PDF in `guides/`. The newest version is used.
- `manual_csv`: fill in `menu.csv` by hand. Copy `_template` to start.

A restaurant with more than one guide lists its readers as `"readers": ["…", "…"]`; they're merged into one menu.

Folders starting with `_` are ignored, so `_template` never appears in the app.

See the main README for step-by-step instructions.
