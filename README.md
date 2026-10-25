# GF Drinks

An iPhone home-screen app that lists every gluten free drink in the current Starbucks UK beverage allergen guide, and how to order each one.

The menu is built straight from Starbucks' allergen guide PDF. Add a new guide and the app updates itself for everyone who has it.

## Updating to a new menu

1. Download the new **Beverage Allergen Guide** PDF (Starbucks UK publishes one each season).
2. In this repository, open the **menus** folder, tap **Add file → Upload files**, choose the PDF and tap **Commit changes**. This works from Safari on an iPhone.
3. Wait about a minute. GitHub reads the PDF, rebuilds the menu and republishes the app. Everyone gets the new menu the next time they open the app with signal.

The app always uses the guide with the **newest version date** in `menus/`, so old guides can stay where they are (or move them to `menus/archive/`).

To check a build, open the **Actions** tab. Each run shows how many drinks it found and any notes. If a PDF can't be read, the run fails and the live app keeps its current menu.

## How "gluten free" is decided

`tools/build_menu.py` reads every row of the guide and checks two places: the **Allergens** column and the **ingredient list**. A drink or milk version is treated as containing gluten if either one names, in bold capitals, any of: wheat, oats, barley, rye, spelt, kamut, gluten or malt. Oats are included because the guides list them under "cereals containing gluten". If the two places disagree, the drink is left out and the build log says so.

Milk versions of the same drink are grouped together, and each drink gets one ordering tag:

| Tag | Meaning |
| --- | --- |
| As listed | Gluten free without changes |
| Any milk | Every milk option is gluten free |
| Any milk except oat | Choose any milk other than the ones named |
| Swap milk | Normally made with oat drink, so ask for another milk |

The guide itself warns that drinks are made on shared equipment, so nothing is guaranteed gluten free. The app says this too.

## One-time setup

1. Create a new **public** repository on GitHub (for example `gf-drinks`) and add these files to it.
2. Go to **Settings → Pages** and set **Source** to **GitHub Actions**.
3. Open the **Actions** tab and run **Build menu and publish app** (or push any change).
4. The app's address appears in the run and in Settings → Pages, for example `https://<your-username>.github.io/gf-drinks/`.

Free GitHub accounts can publish Pages sites from public repositories only, so the guide PDFs you upload will be publicly visible in the repository.

## Installing on iPhone

Open the app's address in **Safari**, tap **Share**, then **Add to Home Screen**. It opens full screen and works without signal using the last menu it downloaded. Share it with anyone by sending the same address.

## Running it locally

```
pip install -r tools/requirements.txt
python tools/build_menu.py           # writes site/data/menu.json
python -m http.server -d site 8000   # open http://localhost:8000
```

## Files

- `menus/`: allergen guide PDFs (the newest is used)
- `tools/build_menu.py`: reads a guide and writes `site/data/menu.json`
- `site/`: the app (HTML, CSS, JavaScript, offline service worker, icons)
- `.github/workflows/publish.yml`: rebuilds and publishes on every change

Unofficial. Not affiliated with Starbucks.
