# Restaurants

One folder per restaurant. The folder name becomes the restaurant's id in the app (lower case, hyphens, e.g. `starbucks-uk`).

Each folder needs a `restaurant.json` saying which **reader** understands that restaurant's allergen information:

- `starbucks_uk_pdf`: put the Starbucks UK beverage allergen guide PDF in `guides/`. The newest version is used.
- `manual_csv`: fill in `menu.csv` by hand. Copy `_template` to start.

Folders starting with `_` are ignored, so `_template` never appears in the app.

See the main README for step-by-step instructions.
