# Twoo's Treat Temple

An iPhone home-screen app that lists the food and drinks with no gluten ingredients at restaurants and coffee shops, built from each restaurant's own allergen guide, and shows how to order each one.

Live at **https://t-800isinevitable.github.io/gf-drinks/**

## Using the app

- **Pick a restaurant** by tapping its name at the top, or choose **All restaurants** to browse and search everything at once. The chooser lists the restaurant you used last first, then those with favourites, then the rest A to Z. The very first time, it opens with three lines on what the app lists, what green, amber and red mean, and that nothing in it is certified gluten free, with Berlin beside All restaurants so it needs no scrolling.
- **Each item's tag sits under its name** (so "Any milk except oat, almond, coconut" never wraps in a narrow pill). "No gluten ingredients" is solid green; "Any milk" and "Any milk except…" are the lighter green. Amber is only for items that need a change (Swap, Ask) and Berlin places the app has a caution about; notes and banners are neutral with a small ⓘ.
- **Filter** with the chips under the search box: menu sections for one restaurant, or restaurants when viewing all.
- **Show or hide by status:** everything shows until you choose. Tap any of the three buttons under the filters to show only those: **No gluten ingredients** (as served, or with any milk except those named), **Needs a change** (ask for a swap or change) and **Avoid** (they contain gluten, or the restaurant says they aren't suitable because of how they're prepared). The three buttons are one even row, the count above the label. The Avoid list under the menu is folded, with its count in the heading; it opens by itself while you search or when you choose Avoid, and repeated names say which section they're in.
- **Tips and warnings:** the first time you open a restaurant, its ordering tips and a note on what "no gluten ingredients" means show in full above the menu. After that they fold into one line (its most important tip, and whether it's certified), so the menu starts near the top of the screen. Tap that line for the tips, then each restaurant's own allergen warnings, word for word with page numbers (cross-contact, allergen updates, recipe changes, delivery, nutrition), and what its guide doesn't tell you.
- **How an item was decided:** where a guide wasn't plain (a blank allergen column, two sources disagreeing, one drink under two names), the item itself says how the app decided, and the warnings list them too.
- **Wording:** the app says "no gluten ingredients", not "gluten free". In UK law "gluten free" means tested below 20 parts per million. Apart from Pho, which is accredited by Coeliac UK, these restaurants make no such claim, and even for Pho the app lists items by their ingredients and quotes Pho's own words.
- **Help (ⓘ)** opens with Warnings, Add a menu and the tag key; everything else folds under its heading, and the install steps go once the app is on the Home Screen.
- **Themes:** ⓘ → Appearance: Match phone, Light, Dark, Pink light, Pink dark.
- **Favourites:** open any item and tap **☆ Save**. The **★ Favourites** chip shows them. **Share my favourites** (on the ★ Favourites list, Berlin's ★ Saved, or in Help) makes a link holding them all, as a backup or to add them on another phone: opening it lists what will be added, what's already saved, and anything left out because it's now on the Avoid list or gone. They also sit first as **Your usuals** above the menu (grouped by restaurant on All), except while searching or on a section chip. They're stored on your phone only. If a new guide puts a favourite on the Avoid list, or drops it, a warning stays at the top until you remove it, in full on that restaurant's own page and on All; on any other restaurant's page it's a short line that takes you there.
- **Share this item** (in any opened item) makes a link such as `…/gf-drinks/#starbucks-uk/caffe-latte` that opens the restaurant, scrolls to the item and opens it. A name used more than once gets its section added. A link to an item that has since changed opens the restaurant with the closest matches. **Something wrong?** (on any item or Berlin place) opens a ready message with the restaurant, item, what the app shows and the guide page, to send through the share sheet; whoever holds the upload key also gets an **Open a GitHub issue** button.
- **Empty searches** offer matches elsewhere ("3 matches at other restaurants ›", places in Berlin, or the UK menus from Berlin), and **A place not here? Send its menu** (also in the chooser).
- **Berlin time:** when the phone's time zone is Berlin's, the app offers the Berlin places once, and offers the UK menus again on the way home. It uses the time zone only, never the location. **Open near me** shows what's still open today, nearest first, in one tap.
- **A look around when the app opens:** with **Keep checking** on (offered once when Near me first answers, or in Help), the **Near me** chip under the search box names the nearest of the app's chains as the app opens ("Pret A Manger 300 m · open until 19:00", with hours where OpenStreetMap has them in a plain form), on All restaurants and on every restaurant's page, and the chooser gets a **Near you** group. The position is read at most every ten minutes and is matched against the app's own branch list on the phone, so it goes nowhere; nothing is kept beyond the last answer on the phone; the phone's location is never asked for unasked. Abroad, the chip names the nearest listed place still open today, from the list itself. Near me says when you're outside the UK, since the menus cover UK branches.
- **Map:** the **globe** by the title opens a full-height map with your position, which follows you as you move, the branches of the app's chains on screen once it's zoomed in to a town (from the branch list, as Near me), and every place on the Abroad lists, coloured as on their lists. A pin opens the chain's menu or the place's row, with the distance, today's hours and directions. Drag it anywhere in the UK; the round button brings it back to you. The position is watched only while the map is open and the app is in front, and never leaves the phone.
- **The branch list:** `site/data/branches.json` holds every UK branch of the app's chains (about 5,600), from OpenStreetMap: `tools/fetch_branches.py` asks for them in the publish job's Monday run (other publishes send the live list again while it's under a week old), so the list is at most a week old. OpenStreetMap's free query service is often too busy to answer a phone quickly, so the phone never asks it: the map and Near me work at once, offline, and without sending the position anywhere. If the service doesn't answer within eight minutes (it waits and retries, and tries a second public server), or the new list has lost a fifth of the branches or a whole chain, the publish keeps the list that's live. The data is © OpenStreetMap contributors (ODbL), credited on the map. A restaurant's `osm` names in `restaurant.json` are what the fetch matches, whole and ignoring case, against each place's brand or name.
- **New here:** a restaurant added since the phone last looked gets a note on All and a **New** tag in the chooser until it's opened or dismissed; the new-guide note says whether your favourites there are unchanged.
- **Show staff:** open any item and tap **Show staff** for a large-print card with the item, how to order it and that you have coeliac disease. The screen stays lit while it (or the coeliac card) is open, and comes back on if the phone let go of it. Parts of dishes (marked **Part of a dish**, such as Five Guys' toppings) and ingredients the guide lists on their own (tagged **Ingredient**, such as Blank Street's milks) have no card, because they aren't things to order as they are.
- **What changed:** when a restaurant's guide is updated, a note lists what's new, what's gone, what's ordered differently and anything that now contains gluten. Changed items are marked in the list until the next guide. Once you dismiss the note, a **What changed** link stays in Warnings and in Help so you can reopen it. The phone also keeps each menu as it was when you last dismissed that note, and compares the newest with it, so if a chain brings out two guides between your visits, nothing from the first is lost: the note then says **has new guides** and **since the guide you last looked at**, What changed shows both that list and the guide's own, and items are marked from both.
- **Out-of-date warning:** if a restaurant's guide has passed its end date, a banner says so. In All restaurants it is one line per guide ("Knoops guide may be out of date ›") that takes you to the restaurant, where the banner is in full.
- **Share** (at the bottom of the chooser) sends a link to the restaurant you're viewing (for example `…/gf-drinks/#starbucks-uk`). **Check for new menus**, with when it last worked, is in ⓘ → Staying up to date; the app also checks each time it opens with signal. The UK / Berlin switch sits in the title row, so the search box has the full width.
- **Search** hides the tips and notes while you type, so results sit just under the box. Searching for a milk that's ruled out ("oat milk latte") explains why and lists the drinks that are fine with another milk. In All restaurants, starting with a restaurant's name narrows to it ("pret latte" means lattes at Pret), and everyday words work too ("chips" finds fries).
- **Menus in other languages** show each item in English with the original name underneath, so you can point to it when ordering. Searching works in either language.
- **Coeliac card:** a set of phrases to show staff (currently German), with a list of words to look for on menus. Works offline.
- **Build an order:** on a restaurant's page, **Build an order** (or **Add to order** in any opened item) ticks several things, such as a burger's patty and toppings at Five Guys, or a dish and its sauce at Pho, for one staff card listing them all, how to order each, and the restaurant's own cross-contact warning. Only items with no gluten ingredients can be ticked; the Avoid list is shown but can't be added, and an item a new guide moves to the Avoid list is taken out of a saved order, with a note saying so. Orders stay on the phone. `order` in `restaurant.json` gives the builder its words (`intro`), the sections to show first (`first`, the parts of dishes) and the card's own request (`cardLine`, such as "Only what's listed here, with no bun, please."). `tests/snapshots/order-<id>.txt` records what the builder offers and blocks for each such restaurant.
- **Logos:** the chooser and the title show each chain's own mark, the icon its site publishes for bookmarks (`restaurants/<id>/logo.png`, fetched by hand with `python tools/fetch_logos.py`; a `logoUrl` in `restaurant.json` names a better image on the chain's site). A chain without one gets a lettered badge. They're the chains' own marks, used only to say which menu is which.
- **International:** the chooser lists the other countries under **International**, in the same form as the restaurants (the country, with its city and what the list holds underneath), and **International** beside the search box goes straight to the city you last looked at.
- **Berlin:** choose **Germany** from the title (or tap **International**) to switch from the UK menus to places in Berlin that are all gluten free, by their own word or the Berlin coeliac support groups' (plus one pizzeria with a separate gluten free kitchen). Each place's tag says who makes the claim, and its row shows any warning, such as oats. Each place shows its own words with an English translation, the Berlin coeliac support groups' description, the app's notes (for example where oats are used), its addresses with a map link, and its opening hours. Rows say whether each place is open now, opens later or is closed (Berlin time). **Still open today** shows places open now or opening later today, **Near me** sorts by distance from your phone, and **☆ Save** keeps places under **★ Saved**. Tap **UK** to go back. Links work too: `…/gf-drinks/#berlin`. Each city in `cities.json` names its `country` (and a `flag`) for the chooser.
- **Amsterdam:** the same for Amsterdam, from the Dutch Coeliac Society's list of places with its Zorgeloos Glutenvrij mark and the city's official guide, each checked against the place's own website, with a Dutch coeliac card. Places with the society's mark that serve only some gluten free dishes (Hans im Glück, some McDonald's) are left out, and named on the page. Links: `…/gf-drinks/#amsterdam`.
- **Updates:** when the app comes back to the screen it checks for a new release as well as new menus. If nothing is open it reloads itself (back where you were); if you're reading an item or a sheet, it shows **Updated. Tap to reload**. Help shows the app version, and **Copy details for the owner** copies it with the menu date, the phone's browser and the last 20 errors the app noticed. They're kept on the phone only, with no tracking and no outside service, and go nowhere unless you paste them into a message.
- **Install:** in Safari, tap **•••** (or **Share** on older iPhones), then **Add to Home Screen**, and keep **Open as Web App** switched on (otherwise you get a bookmark). It works without signal using the last menus it downloaded. It opens at once even on a weak signal: the app and the menus saved on the phone show straight away, and newer menus replace them when they arrive (**Menus updated**). Menus that haven't changed aren't downloaded again.

## Updating a restaurant's menu

`main` is protected: every change to it goes through a pull request whose checks have passed, including yours. When you upload a guide on GitHub (open the folder, then **Add file → Upload files**), choose **Create a new branch for this commit and start a pull request**, then **Propose changes** and **Create pull request**. When the check turns green (about three minutes), tap **Merge**. The app updates about a minute after that. If the check fails, nothing is published; its log says why.

**Five Guys:** upload the new UK allergen, ingredient and nutrition guide PDF to `restaurants/five-guys-uk/guides/`. The newest date in the guide (FGUK_YYYYMMDD) is used. Anything with a gluten dot **or a "1"** (Five Guys' mark for "not suitable … due to manufacturing and preparation methods") goes in the Avoid list; a "2" (not suitable at breakfast time) shows as needing a change.

**Pret:** upload the new GB allergen guide PDF to `restaurants/pret-uk/guides/`. Pret's guides have no end date, so the app asks for a re-check 91 days after the "valid from" date (change `recheckDays` in `restaurant.json`).

**Starbucks:** upload the new Beverage Allergen Guide and Food Allergen Guide PDFs to `restaurants/starbucks-uk/guides/` (through a pull request, as above). Each reader takes the newest of its own kind (the food guide's cover says Food), so old guides can stay.

**Pho:** upload the new allergen guide PDF (linked as "Allergens" at the foot of phocafe.co.uk) to `restaurants/pho-uk/guides/`. Its "accurate as of" month is the version; the app asks for a re-check 183 days later.

**Blank Street:** upload the new UK allergen guide PDF (linked from blankstreet.com) to `restaurants/blank-street-uk/guides/`. The guide has no date in it, so keep the season in the file name (for example `...Autumn26.pdf`); the PDF's creation date is used as the version.

**Parts of dishes, ingredients and names that could be mixed up:** some guides list parts of dishes (Five Guys' meat and toppings) or ingredients on their own (Blank Street's milks and syrups). In `restaurant.json`, `roles` marks them as `part` or `ingredient`, by section or by `"Section|Name"` for one row. Neither gets a staff card; parts say **Part of a dish**, and ingredients get a grey **Ingredient** tag and aren't counted under the status buttons. `rename` gives a row a clearer name, such as `"Meat|Hot Dog": "Hot dog sausage"`, so a part can't be taken for the dish of the same name. The build stops if either matches nothing in a new guide, and the checks stop it if one name is on both the list and the Avoid list.

**Greggs:** upload the new allergen guide PDF (linked as the allergen guide on greggs.com/nutrition) to `restaurants/greggs-uk/guides/`. Its version date on the cover is used; the app asks for a re-check 61 days later. The guide watch finds new ones by itself.

**Caffè Nero:** upload the new GB "Allergen, Nutritional & Ingredient Guide" PDF (linked from the menu pages on caffenero.com) to `restaurants/caffe-nero-uk/guides/`. The "Issued" date is used.

**PizzaExpress:** upload the new "Allergen Information, England, Scotland, Wales and Jersey" PDF (pizzaexpress.com/allergens-and-nutritionals) to `restaurants/pizza-express-uk/guides/`. The month and version on its cover are used. The ingredients list and the other regions' guides are ignored if they land there too.

**Nando's:** Nando's has no guide file, only a page per dish. Run `python tools/fetch_nandos.py` (about four minutes; it reads the dishes in Nando's sitemap one at a time) and open a pull request with the new `restaurants/nandos-uk/guides/nandos-allergens-<date>.json`. The app asks for a new one 61 days after the last.

**Restaurants kept by hand (Knoops):** edit that restaurant's `menu.csv` and update the dates in its `restaurant.json`. When you look for a newer guide and there isn't one, record it in `latestGuide` (`checked` date and a `note`); the out-of-date banner shows it. Knoops' newest guide is from March 2024, so the app shows it as possibly out of date until a newer one appears.

**Berlin:** the list is kept by hand in `site/cities.json`, from the [Berlin glutenfrei](https://www.berlin-glutenfrei.de/glutenfrei-berlin-restaurants) list (run by the Berlin contacts of the German Coeliac Society) checked against each place's own website. Only places that say everything is gluten free, or that make gluten free food in a separate kitchen, are included. Set `claim` to who says it's gluten free: `place-all` (its own words), `list-all` (only the list says so), `place-part` (with a `claimLabel` such as "Says its cakes are gluten free") or `separate` (a separate gluten free kitchen). Quote each place's words exactly and add an English translation. Mark a place `"status": "unconfirmed"` with a `statusNote` if its opening can't be confirmed, and put anything to watch for (such as oats) in `caution`, with a short `flag` for the row (such as "Has oats: ask"). Each location needs `lat` and `lon` (for Near me; OpenStreetMap's Nominatim gives them from the address) and, where the place's website gives them, `hours`: seven entries from Monday to Sunday, each `"HH:MM–HH:MM"`, `""` for closed or `null` when the website doesn't say, plus an optional `hoursNote` and `kitchenCloses` (`"21:00"`: the app treats the place as closed after that). Leave `hours` out when they aren't known at all. Update `checked` after each review. The app warns once `recheckDays` (90) have passed.

**New guides found for you:** each Monday `.github/workflows/guide-watch.yml` (`tools/watch_guides.py`) opens each restaurant's own guide page (`watch` in its `restaurant.json`: the page, and a pattern its guide's link matches), downloads the guides it links and compares them with the ones here. A new one becomes a pull request with the PDF in `guides/`, the guide it replaces moved to `guides/archive/`, and what changed according to the build. Read it and merge it as above; nothing merges by itself. Older editions a page still links are left alone. If a page can't be checked (blocked, moved, no guide link), or Knoops (kept by hand) links a new guide, it opens an issue instead. To try it without opening anything: `python tools/watch_guides.py`.

**Uploads from the app:** every 15 minutes `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`) opens an issue, "Upload waiting: <folder>", for each menu sent from the app, and "Place requested: <name> (<area>)" for each place asked for by name (`inbox/requests/` on the `uploads` branch). The scan routine can start on that issue, so a menu is scanned within minutes; the routine's weekly schedule is the fallback. The scan closes the issue once its pull request is open. For a place asked for by name it looks for the place's own published allergen information (the "Places asked for by name" section of `tools/SCAN_INSTRUCTIONS.md`); if there is none, it says so on the issue and leaves it open for you.

**Notifications:** after a publish that brought a new guide, the `notify` job in `publish.yml` runs `tools/push.py`, which sends one push notification (what changed, and a warning on the phone if a favourite now contains gluten) and sets the app's icon badge. There is no server, so the setup is by hand, once: the private half of the push key pair is the repository secret `VAPID_PRIVATE_KEY`, as the PEM text or the raw base64url value (its public half is `PUSH_KEY` in `site/app.js`; `tools/push.py` says how to make a new pair if it's lost), and each phone's notification address goes in the secret `PUSH_SUBSCRIPTIONS`, one JSON line per phone. A phone gets its address from **Help, Tell me about new menus** in the Home Screen app, then sends it to you. With no phones saved, the job says so and sends nothing. If a phone's address expires, the job's summary says which one; switch notifications on again on that phone and replace its line.

**Reminders:** each morning `.github/workflows/guide-reminders.yml` opens an issue for any guide that has ended or ends within three weeks, and for a city list due a re-check. Close the issue if there's no newer guide yet; you won't be reminded again until the end date changes.

## Adding a menu from the app

Anyone can open **ⓘ → Add a menu**, pick photos or a PDF of a restaurant's allergen menu and tap **Send…** to send them to the app's owner through the iPhone share sheet (Messages, WhatsApp, Mail). The owner can upload them straight to the app:

1. Open **ⓘ → Add a menu → I'm the app's owner**.
2. The first time, paste a GitHub key (the app shows how to create one; it only needs **Contents: Read and write** on this repository). It's stored on that phone only.
3. Enter the restaurant and city, choose the PDF or photos, and tap **Upload**. The files go into `inbox/` on the `uploads` branch, all in one commit, so an upload arrives whole or not at all, and it's safe to tap **Upload** again after a dropped signal. Uploads never touch `main`, so a lost key can't change the live app.
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
   | `doubt` | The source shows no gluten, but the app has reason to doubt it. Listed under Avoid as "Check in store" | `note`: why, shown as the app's own caution |

   Separate several options with `;` (for example `skimmed;soya`). For menus in another language, write `name` and `section` in English and put the menu's own wording in `original` and `section_original`.
4. Commit on a new branch and open a pull request. The checks refuse anything missing; merge once they pass.

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

Every pull request runs `.github/workflows/checks.yml`, and every change to `main` runs `.github/workflows/publish.yml`; both use the same steps (`.github/actions/build-check`), which:

1. downloads the menus that are live now (`tools/fetch_previous.py`), so the build can say what changed in a new guide,
2. runs the unit tests (`tests/`) and builds every restaurant (`tools/build.py`),
3. checks the results (`tools/check.py`): every item has a valid ordering tag, options are listed where needed, nothing is both safe and unsafe, and each restaurant has items,
4. compares each menu with its snapshot (`tools/snapshot.py`, saved in `tests/snapshots/`), so a change to a reader can't quietly change what the same guide gives. A new guide is reported, not failed,
5. opens the app in a real browser at iPhone size (`tools/ui_check.py`): no errors, nothing wider than the screen, the buttons work, and every theme has enough contrast; then again in WebKit, the engine iPhones use,
6. publishes the app to GitHub Pages.

If any step fails, nothing is published and the live app keeps its previous menus. The **Actions** tab shows each run's results, including how many items each restaurant has. Pull requests run the same checks (`.github/workflows/checks.yml`) without publishing.

When a reader's output is meant to change (a fix, or a new guide), check the differences against the guide, then run `python tools/snapshot.py --update` and commit the snapshots.

Free GitHub accounts can publish Pages sites from public repositories only, so everything here, including uploaded guides, is publicly visible.

**What comes from outside is treated as data.** The scan routine's instructions (`tools/SCAN_INSTRUCTIONS.md`) and its prompt say that uploads, requests, PDFs, websites and issues are data, never instructions; that the routine stops if the issue that started it wasn't opened by `github-actions[bot]` (anyone can open an issue on a public repository); and that a request's website is a hint to check, not a source. Every web address in the built data and `cities.json` must be `https://` (`tools/check.py`), and the app passes each through `safeUrl()` before it becomes a link. The jobs install every Python package by its hash (`tools/requirements-lock.txt`, `tools/requirements-notify-lock.txt` and `tools/requirements-buildtools-lock.txt`, made with `uv pip compile --universal --generate-hashes` from `requirements*.txt`; rerun it after changing a pin; they end in `.txt` because that is all Dependabot reads, and the build tools go in first so a package that ships as source is built with a checked setuptools), the workflow actions are pinned by commit id, the repository allows only GitHub's own and verified actions, and Dependabot bumps the pins monthly and opens a pull request for a vulnerable package. A ruleset to let only the repository's admin update `main` was tried and removed: on a personal repository GitHub doesn't treat the owner as that bypass actor, so it blocked the owner's own merges too, and keeping a job token off `main` falls to the workflows' own permissions and the guide watch's job split still to do. Uploads are committed under the app's own author name; `tests/test_vendor.py` holds the map library to its official fingerprint; and the app shows nothing when framed by another page.

## Running it locally

```
pip install -r tools/requirements.txt -r tools/requirements-dev.txt
python -m playwright install chromium webkit     # once, for the UI checks
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
- `tools/ui_check.py`: the app in a real browser at iPhone size (`--list` names the checks; `--only NAME` runs one)
- `tools/adapters/common.py`: what the readers share (the cereal words, tidying, picking the newest guide); `tools/gh.py`: the GitHub API for the tools that open issues and pull requests
- `tools/reminders.py`: guides ending soon (opens GitHub issues each morning)
- `tools/watch_guides.py`: new guides on the restaurants' websites (opens pull requests each Monday)
- `tools/upload_notice.py`: opens an issue for each upload, and each place asked for by name, waiting on the `uploads` branch
- `tools/push.py`: the notification after a publish with a new guide (`--plan` in the build job, `--send` after the deploy)
- `tools/requirements.txt`, `requirements-dev.txt`, `requirements-notify.txt`, `requirements-buildtools.txt`: the Python packages, as people install them; `tools/*-lock.txt`: the same with every package's hash, as the jobs install them; `.github/dependabot.yml`: keeps the pinned actions current and flags a vulnerable package
- `site/vendor/leaflet/`: the map library (Leaflet 1.9.4, BSD licence), a copy because the app's security policy allows scripts from its own files only; the map's tiles come from OpenStreetMap while the map is open and are never kept
- `site/guides/` (generated): each restaurant's current guide, published so "Guide page 7" can open it
- `tools/adapters/`: readers for each kind of allergen guide
- `tools/SCAN_INSTRUCTIONS.md`: what the daily scan does with uploads
- `inbox/` on the `uploads` branch: uploads waiting to be scanned
- `.github/workflows/keep-alive.yml`: keeps the scheduled workflows switched on
- `site/phrases.json`: gluten free card phrases (add a language here)
- `site/cities.json`: hand-checked places in other cities (Berlin, Amsterdam)
- `tools/fetch_nandos.py`: saves Nando's allergen pages as a snapshot for its reader
- `site/`: the app (HTML, CSS, JavaScript, offline support, icons)

Unofficial. Not affiliated with any restaurant.
