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
- **Favourites:** open any item and tap **☆ Save**. The **★ Favourites** chip shows them. **Share my favourites** (on a ★ Favourites list, or in Help) makes a link holding them all, as a backup or to add them on another phone: opening it lists what will be added, what's already saved, and anything left out because it's now on the Avoid list or gone. They also sit first as **Your usuals** above the menu (grouped by restaurant on All), except while searching or on a section chip. They're stored on your phone only. If a new guide puts a favourite on the Avoid list, or drops it, a warning stays at the top until you remove it, in full on that restaurant's own page and on All; on any other restaurant's page it's a short line that takes you there.
- **Share this item** (in any opened item) makes a link such as `…/gf-drinks/#starbucks-uk/caffe-latte` that opens the restaurant, scrolls to the item and opens it. A name used more than once gets its section added. A link to an item that has since changed opens the restaurant with the closest matches. **Something wrong?** (on any item or Berlin place) opens a ready message with the restaurant, item, what the app shows and the guide page, to send through the share sheet; whoever holds the upload key also gets an **Open a GitHub issue** button.
- **Empty searches** offer matches elsewhere ("3 matches at other restaurants ›", places in Berlin, or the UK menus from Berlin), and **A place not here? Send its menu** (also in the chooser).
- **Berlin time:** when the phone's time zone is Berlin's, the app offers the Berlin places once, and offers the UK menus again on the way home. It uses the time zone only, never the location. **Open near me** shows what's still open today, nearest first, in one tap.
- **A look around when the app opens:** with **Keep checking** on (offered once when Near me first answers, or in Help), the **Near me** chip under the search box names the nearest of the app's chains as the app opens ("Pret A Manger 300 m · open until 19:00", with hours where OpenStreetMap has them in a plain form), on All restaurants and on every restaurant's page, and the chooser gets a **Near you** group. The position is read at most every ten minutes and is matched against the app's own branch list on the phone, so it goes nowhere; nothing is kept beyond the last answer on the phone; the phone's location is never asked for unasked. On a city's page, the chip names the nearest listed place still open today, from the list itself. Near me says when you're outside the UK, since the menus cover UK branches.
- **Map:** the **globe** by the title opens a full-height map with your position, which follows you as you move, the branches of the app's chains on screen once it's zoomed in to a town (from the branch list, as Near me), and every place on the city lists, in the UK and abroad, coloured as on their lists. A pin opens the chain's menu or the place's row, with the distance, today's hours and directions. Drag it anywhere in the UK; the round button brings it back to you. The position is watched only while the map is open and the app is in front, and never leaves the phone.
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
- **Sections:** the switch at the top has **Chains** (the chains' menus), **UK cities** and **Abroad**. The title under it chooses within the section: a restaurant or All restaurants, or a city. Each city section goes back to the city you last looked at in it.
- **UK cities:** the UK cities in `site/cities.json` (the app's Help names them), with places that are all gluten free by their own word or a listing (and one, Indigo, that says its lunch and dinner are), found through Coeliac Sanctuary and coeliac guides and checked against each place's own website where it has one. Each UK city also lists the app's chains with branches in and around it, with their menus a tap away. Links: `…/gf-drinks/#london`.
- **Berlin:** tap **Abroad** and choose **Germany** from the title to switch from the UK menus to places in Berlin that are all gluten free, by their own word or the Berlin coeliac support groups' (plus one pizzeria with a separate gluten free kitchen). Each place's tag says who makes the claim, and its row shows any warning, such as oats. Each place shows its own words with an English translation, the Berlin coeliac support groups' description, the app's notes (for example where oats are used), its addresses with a map link, and its opening hours. Rows say whether each place is open now, opens later or is closed (Berlin time). **Open near me** shows places open now or opening later today, nearest first (what's open today, without a location), and **☆ Save** keeps places under **★ Favourites**. The language card is the first chip; a city with fewer than four places has no filters. Tap **Chains** to go back. Links work too: `…/gf-drinks/#berlin`. Each city in `cities.json` names its `country` (and a `flag`) for the chooser.
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

**Berlin:** the list is kept by hand in `site/cities.json`, from the [Berlin glutenfrei](https://www.berlin-glutenfrei.de/glutenfrei-berlin-restaurants) list (run by the Berlin contacts of the German Coeliac Society) checked against each place's own website. Only places that say everything is gluten free, or that make gluten free food in a separate kitchen, are included. Set `claim` to who says it's gluten free: `place-all` (its own words), `list-all` (only the list says so), `place-part` (with a `claimLabel` such as "Says its cakes are gluten free") or `separate` (a separate gluten free kitchen). Quote each place's words exactly and add an English translation. Mark a place `"status": "unconfirmed"` with a `statusNote` if its opening can't be confirmed, and put anything to watch for (such as oats) in `caution`, with a short `flag` for the row (such as "Has oats: ask"). Each location needs `lat` and `lon` (for Near me; OpenStreetMap's Nominatim gives them from the address) and, where the place's website gives them, `hours`: seven entries from Monday to Sunday, each `"HH:MM–HH:MM"` (or `"12:00–14:30, 17:00–21:30"` for a day with a break), `""` for closed or `null` when the website doesn't say, plus an optional `hoursNote` and `kitchenCloses` (`"21:00"`: the app treats the place as closed after that). Leave `hours` out when they aren't known at all. Update `checked` after each review. The app warns once `recheckDays` (90) have passed.

**New guides found for you:** each Monday `.github/workflows/guide-watch.yml` (`tools/watch_guides.py`) opens each restaurant's own guide page (`watch` in its `restaurant.json`: the page, and a pattern its guide's link matches), downloads the guides it links and compares them with the ones here. A new one becomes a pull request with the PDF in `guides/`, the guide it replaces moved to `guides/archive/`, and what changed according to the build. Read it and merge it as above; nothing merges by itself. Older editions a page still links are left alone. If a page can't be checked (blocked, moved, no guide link), or Knoops (kept by hand) links a new guide, it opens an issue instead. To try it without opening anything: `python tools/watch_guides.py`.

**Uploads from the app:** every 15 minutes `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`) opens an issue, "Upload waiting: <folder>", for each menu sent from the app, and "Place requested: <name> (<area>)" for each place asked for by name (`inbox/requests/` on the `uploads` branch). The scan routine runs at 07:15 and 19:15 and works through what's waiting (issues opened by the workflow don't start it, and GitHub runs the 15-minute schedule only every few hours, so allow up to half a day). The scan closes the issue once its pull request is open. For a place asked for by name it looks for the place's own published allergen information (the "Places asked for by name" section of `tools/SCAN_INSTRUCTIONS.md`); if there is none, it says so on the issue and leaves it open for you. A city asked for (the "Ask for a city" form, at the bottom of the UK cities and Abroad lists) opens "City requested: <city> (<country>)": the scan finds the places there that say everything they serve is gluten free, checks each against its own website, and opens a pull request adding the city ("Cities asked for" in the same file). Merging it publishes the city and tells the phones.

**Notifications:** after a publish that brought a new guide, the `notify` job in `publish.yml` runs `tools/push.py`, which sends one push notification (what changed, and a warning on the phone if a favourite now contains gluten) and sets the app's icon badge. A publish that raises the release number (`APP_VERSION`) past the live one sends **Update N is live!** too, when `site/whatsnew.json` has notes for that release: tapping it opens the app's **What's new** (`?whatsnew`, also in Help). To announce a release, add its notes at the top of `whatsnew.json` (version, date, a title that finishes "Tap to see the new features: …", and a few items); a release without notes goes out quietly. `check.py` holds the file to that form. There is no server, so the setup is by hand, once: the private half of the push key pair is the repository secret `VAPID_PRIVATE_KEY`, as the PEM text or the raw base64url value (its public half is `PUSH_KEY` in `site/app.js`; `tools/push.py` says how to make a new pair if it's lost), and each phone's notification address goes in the secret `PUSH_SUBSCRIPTIONS`, one JSON line per phone. A phone gets its address from **Help, Tell me about new menus** in the Home Screen app, then sends it to you. With no phones saved, the job says so and sends nothing. If a phone's address expires, the job's summary says which one; switch notifications on again on that phone and replace its line. To check notifications without a release, run **Test notification** under the repository's Actions (Run workflow; the website works on a phone): it sends one test notification to every saved phone, and its summary lists each phone with a check code. The app shows its own phone's code under Help, Tell me about new menus; if that code isn't in the list, the secret holds an old address for that phone, so send the one shown and replace its line.

**Reminders:** each morning `.github/workflows/guide-reminders.yml` opens an issue for any guide that has ended or ends within three weeks. Close the issue if there's no newer guide yet; you won't be reminded again until the end date changes. It also opens "Places check: <city> places" a month after a city's last check, one city a morning. That issue starts the scan, which re-checks every place in the city against its own website and opens a pull request with what changed and a new `checked` date ("Re-checking a city" in `tools/SCAN_INSTRUCTIONS.md`). Merge it, even when nothing changed, to renew the date. If no re-check has been merged three weeks before the list would show as out of date, you get "Places list ends: <city> places" instead.

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

## Developer reference

Detail that only one kind of task needs. `CLAUDE.md` holds the rules and points here.

### Restaurant config and readers

- `restaurants/<id>/restaurant.json` names a **reader** (`tools/adapters/<reader>.py`), or several as `"readers": [...]` merged into one menu (Starbucks drinks and food).
- It also holds display details, `tips`, `headline`, `gaps` (what the guide doesn't tell a coeliac) and `recheckDays`.
- `headline` is the one tip on the folded line above the menu. Every page shows its tips that way, except the first menu page ever opened (`MENUS`), where the card shows in full once.
- `headline` is required when there are tips, under 60 characters, and taken from the tips, never new advice.
- When a reader decides an item itself because the guide wasn't plain (blank allergen column, sources disagreeing, versions under different names), it also sets the item's `decided`.
- `decided` is one plain-English sentence the app shows on the item ("How the app decided") and in the Warnings sheet. The raw `warnings` strings are for the build log only.
- Readers, automatic from PDFs in `guides/` (newest edition wins): `starbucks_uk_pdf`, `starbucks_uk_food_pdf`, `pret_uk_pdf`, `five_guys_uk_pdf`, `pho_uk_pdf`, `blank_street_uk_pdf`, `greggs_uk_pdf`, `caffe_nero_uk_pdf`, `pizza_express_uk_pdf`.
- `nandos_uk_json` reads the snapshot `tools/fetch_nandos.py` saves, since Nando's publishes its allergens only as a page per dish.
- `manual_csv` reads a hand-kept `menu.csv` (see `restaurants/_template/`; used for Knoops).
- Every PDF reader needs a `newest_pdf(guides_folder)`.
- The readers share `tools/adapters/common.py`: `clean`, the cereal pattern (`CEREAL`, `CEREAL_CAPS`: the union of every reader's list, never narrower), `cereal_code`, `newest_by` and `result`. `build.py` works out `validUntil` for all of them.
- `tools/adapters/notices.py` extracts each guide's own warnings word for word for the Warnings page, including an "accreditation" kind for a guide's own gluten free claim.

### Cross-checks between a guide's sources

- Caffè Nero's allergen table is checked against its ingredient lists (names matched loosely, an exact name always winning).
- Nando's table is checked against the line above it.
- A disagreement counts as gluten.
- PizzaExpress lists a dish with a gluten mark only with the change its Please note column says makes it suitable for coeliacs ("With the GF base, please").
- PizzaExpress puts an item with no gluten mark but no Coeliacs tick on the Avoid list.
- Anything named with oat (oat drink) is on the Avoid list whatever a guide's ticks say.

### Roles, renames and the order builder

- A row that isn't a dish to order gets a `roles` entry (see `CLAUDE.md`). Examples: Five Guys' meat and toppings, Blank Street's milks.
- `rename` fixes a clash: Five Guys' sausage is "Hot dog sausage", because its menu Hot Dog comes in a wheat bun.
- `order` in `restaurant.json` sets up the order builder (several items on one staff card). It has three parts:
  - `intro`: its words, each fact checkable against the guide or the tips.
  - `first`: the sections shown first (the parts of dishes). One the guide no longer has stops the build.
  - `cardLine`: the card's request, ending "please."
- The builder is on every restaurant's page.
- What's in an order is only ever a key into `r.items` (never the Avoid list; ingredients listed on their own are left out).
- A key that no longer resolves is dropped and named.
- `tests/snapshots/order-<id>.txt` records what the builder offers and blocks.
- `restaurants/<id>/logo.png` (`tools/fetch_logos.py`, honest UA, run by hand) is the chain's own site icon for the chooser. `logoUrl` names a better image on its site.

### Build, generated data and previous menus

- `tools/build.py` builds `site/data/restaurants.json`: the build time, and each restaurant's name, file, guide, stats, logo and a fingerprint of its menu.
- It also builds `site/data/r/<id>.json`: the menu and settings, with no build time in it, so an unchanged menu stays byte for byte the same and phones get "not modified".
- `tools/check.py` validates. `site/data/` is generated, not committed.
- `check.py` also fails anything listed with no gluten ingredients, or any option called fine, that names a gluten cereal, whatever reader or hand-kept `menu.csv` produced it. The one exception is the oat swap in `CLAUDE.md`.
- `build.py` stops when rows that were on the live Avoid list turn up listed with no gluten ingredients (`avoid_drop`): more than a third of the Avoid rows still on the menu, in the whole menu or in one guide of a merged one. That is what a reader that misses the guide's gluten marks looks like. Avoid rows that leave the menu altogether (a season's drinks) don't count, unless more than two thirds of them go and the Avoid share falls by a third as well.
- A part is judged when it has five live Avoid rows or more, or when they are a tenth of it. A single row moving is a recipe change unless the part is one of those.
- If the change is real, set `"avoidDropOk"` in that restaurant's `restaurant.json` to the new guide's source name, exactly as the error prints it. It applies to that guide only.
- The Pret reader stops on any mark in a product row's allergen columns that isn't the guide's own tick (`odd_mark`).
- `build.py` tidies item names by case only (`CAPS_WORDS` lists the real capitals), so a saved favourite still matches.
- `build.py` publishes each restaurant's current guide PDF under `site/guides/<id>/` (generated, ignored by git) and records `guideFiles` and, for a merged restaurant, each row's `src`, so "Guide page 7" links to the right guide.
- `tools/fetch_previous.py` downloads the live menus into `.previous/`. `tools/changes.py` then records what changed in each new guide ("changes"), carried forward until the next guide.
- The app shows it as a dismissable "what's new" banner, plus a lasting "What changed" link in Warnings and Help.
- The app warns about favourites that are now to avoid or gone: in full on that restaurant's own page and on All, and as a short line elsewhere.
- A download failure in `fetch_previous.py` stops the build (`SystemExit`) rather than publishing with every restaurant's changes silently dropped. A 404 (nothing published yet) is treated as the first deploy, not a failure.
- `site/compare.js` is a line-for-line port of `compare()` in `tools/changes.py`. `tests/test_changes_js.py` runs both side by side (Node) on the real Starbucks summer and autumn drinks guides and on made-up older versions of every menu (`tests/fixtures/changes/`). Refresh the `menu-*.json` fixtures when a reader changes a lot.

### Checks and workflows

- `tools/snapshot.py` compares each menu with `tests/snapshots/<id>.txt` (same guide only).
- `tools/ui_check.py` drives the app in Playwright at iPhone size, light and dark. `tests/` has unit tests.
- `.github/workflows/checks.yml` runs all of it on pull requests. It has no `paths-ignore`, because a required check that's skipped blocks merging.
- `.github/workflows/publish.yml` builds, checks and deploys to GitHub Pages on every push to `main` (pushes touching only `inbox/` are ignored).
- `publish.yml` and `checks.yml` share the steps in `.github/actions/build-check` (a composite action, so the job names the branch protection needs don't change). The test browsers are cached by Playwright version.
- `guide-reminders.yml` opens an issue for guides ending within three weeks.
- `guide-watch.yml` runs weekly (`tools/watch_guides.py`):
  - it checks each restaurant's `watch` page for a guide PDF it hasn't seen (by sha256, `guides/archive/` included);
  - it asks the reader's `newest_pdf()` whether it would use it;
  - if so it opens a pull request (old guide moved to `guides/archive/`), then dispatches `checks.yml` on it, since a pull request opened with `GITHUB_TOKEN` doesn't trigger workflows;
  - blocked or changed pages, and new guides for `manual_csv` restaurants, open issues;
  - it identifies itself honestly and never tries to get round a site's blocking.
- `keep-alive.yml` re-enables the scheduled workflows monthly through the API (GitHub switches them off after 60 days with no activity). It commits nothing, so it works with `main` protected. The daily scan also checks their state (step 0 of `SCAN_INSTRUCTIONS.md`).
- The tools that open issues and pull requests share `tools/gh.py`.

### `ui_check.py` conventions

- One function per check, registered in `CHECKS` (`--list`; `--only NAME` runs one).
- What a check expects comes from the built menus and `cities.json` where it can (`expected_today` reads a place's hours the way the app does), so upkeep of a menu or a city doesn't break an unrelated check. Don't write a place, an item or a season into a check by name.
- It runs everything in Chromium, then loads every page and uploads again in WebKit (the iPhone's engine).
- Upload checks run against `FakeGitHub`, an in-memory Git Data API, with the service worker blocked (in WebKit, requests from a page it controls get past `page.route`).
- Playwright's `wait_for_function` uses `eval`, which the content security policy blocks. Use `wait_for_selector`.
- A test style goes in through the CSSOM (`add_css`), which the policy doesn't govern.
- `--shots DIR` saves screenshots.
- It measures that item tags don't wrap and the status buttons stay one even row, in the phone's font and a wide one.
- It holds first-screen height to the top half with four items showing (an order pill broke it).
- It enforces the accessibility rules in `CLAUDE.md`.
- `check_e_review` and the look-around part of `check_f8_near_me` hold the look-around. `check_f16_live_map` holds the map page, including that nothing but map tiles leaves the phone.

### The app's files (`site/`)

- `index.html`, `app.js`, `styles.css`, `sw.js`, `manifest.webmanifest`, `phrases.json` (coeliac card), `cities.json`.
- `sw.js` serves the app's own files cache-first from the release's cache, precached past the browser's and server's caches. `.json` is network-first with a 4 second fallback to the saved copy, revalidated with `cache: "no-cache"`. Bump `CACHE` when shell files change.
- Why a release raises `CACHE` and `APP_VERSION`: the change of service worker is what makes phones reload into the new code. Phones serve the app's own files from the release's saved copy, so code changed without a raise would never reach them. `check.py` holds the two equal and `tools/check_release.py` (in the pull request check) fails if code changed without a raise. It counts `site/vendor` as app code.
- Colour: amber (`--swap`) means "this item needs a change": the Swap and Ask tags, and a Berlin place with a caution. Banners and notes are neutral (surface colour, a small ⓘ). Item tags sit under the name.
- First-screen height: anything new above the menu on a restaurant page costs it. Put page actions in the chip row under the search box, where they cost none.

### Cities (`site/cities.json`)

- Hand-checked places in cities, each with its `country` and `flag`.
- `"group": "uk"` puts a city under UK cities. Any other is Abroad.
- The header's sections (`#region` above the title: Chains, UK cities, Abroad; `SECTIONS`, `sectionOf()`) each go back to the city last looked at in them (`gf-last-uk-city`, `gf-last-city`). The chooser lists only the current section's restaurants or cities.
- A UK city also lists the app's chains with branches inside its `bounds` (`chainsHere()`, from the branch list), each row opening the chain's menu. It needs no coeliac card.
- A day's `hours` can hold a break (`"12:00–14:30, 17:00–21:30"`, read by `spans()`).
- `check.py` validates it. Re-check reminders come from `reminders.py`.
- A city's introduction folds after its first visit like the UK strip (`introFull(region)`, `#cityStrip`).
- Each city is re-checked monthly: `reminders.py` opens "Places check: …" a month after its `checked` date (one city a morning). That starts the routine's "Re-checking a city", ending in a pull request that renews `checked`.
- Search covers name, type, description and area, not street names.

#### Where the places came from

- Berlin: the berlin-glutenfrei.de list (Berlin contacts of the German Coeliac Society).
- Amsterdam: the Dutch Coeliac Society's Zorgeloos Glutenvrij list (glutenvrij.nl) plus the city's official guide.
- Each checked against the place's own website.
- The UK cities' places (Leaky Teacup, in Retford, is under Worksop) were found through Coeliac Sanctuary's listings and coeliac guides, since Coeliac UK's venue guide is for members only.
- A place with no website of its own is kept only when Coeliac Sanctuary or its market lists it as all gluten free, as `list-all` with `listed` and `listedBy`, and `unconfirmed`.
- A city can name more than one source (`list`, `also`) and its own footer lines (`footNotes`).

### Uploads and the scan routine

- The app's Add menu button uploads to `inbox/` on the **`uploads` branch**, never `main`.
- All of an upload's files go in one commit through GitHub's Git Data API (blobs, tree, commit, then moving the branch), so an upload arrives whole or not at all.
- A retry reuses the same folder and files, so a retry after a lost answer adds nothing.
- A scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md` and opens a pull request to `main` per upload for the owner to approve.
- GitHub triggers on routines support only pull request, release and issue events (no push, no branch filter). So `upload-notice.yml` (every 15 minutes, on `main`, because a push workflow would use the stale copy on `uploads`) opens an "Upload waiting: <folder>" issue per upload.
- Issues opened by `github-actions[bot]` don't fire a routine's GitHub trigger, so the routine has none and runs on its schedule, 07:15 and 19:15 London time. GitHub also runs the 15-minute cron only every few hours.
- Only issues opened by the bot count as already opened (`gh.issue_titles`).
- The issue holds the folder name and restaurant and area only, never the uploader's notes.
- A place asked for by name is `inbox/requests/<when>-<name>-<area>.json` on `uploads`. The phone files it with the key, or is passed it as a `#request=` link that only fills the form in. `upload_notice.py` notices it, and the "Places asked for by name" section of `SCAN_INSTRUCTIONS.md` handles it.
- A whole city asked for is the same file with `"kind": "city"` (area = its country). The "Ask for a city" form is in the same sheet, linked from the bottom of the UK cities and Abroad lists (`askFor()`/`ASK` in `app.js`). It opens "City requested: …" and is handled by "Cities asked for": the routine researches the city by the venue rules in `CLAUDE.md` and opens a pull request adding one `cities.json` entry.
- An upload's GitHub key (`app.js`, `KEY_KEY`) is removed from the phone, with a clear message (`keyTrouble()`), on a 401 (expired or deleted) or a 403 that isn't GitHub's rate limit (wrong repository, or Contents read-only). That means the key no longer works, not that the connection failed.
- Saving a key checks it can write by creating one loose blob, because the repository's `permissions.push` reflects the account, not a fine-grained key.

### Security measures

- The routine works under the owner's GitHub account, so its safeguards are:
  - no MCP connectors and no PR-comment watching in its settings;
  - `guard.yml` (required, `pull_request_target`, so main's copy judges every pull request): a `scan/`, `city/`, `recheck/` or `guide-watch/` branch may change only its own files (`tools/guard.py`; a `guide-watch/` branch only `restaurants/<id>/guides/`, so a reader fix, a snapshot or `avoidDropOk` for a new guide goes in a pull request of your own, merged first), a pull request carrying a commit made by the routine (author Claude) or a workflow (`github-actions[bot]`) must be on one of those branches whatever it is named, and every pull request's `restaurants/` and `site/cities.json` are built and checked with main's tools;
  - the push secrets in the `notify` environment, which only `main` may use.
- What comes from outside is data, never instructions: `tools/SCAN_INSTRUCTIONS.md` ("What counts as instructions") and the routine's prompt say so, and the routine stops on an issue not opened by `github-actions[bot]`.
- Every web address in the built data and `cities.json` must be `https://` (`check.py`, `check_urls`). `app.js` passes each through `safeUrl()` before it becomes a link.
- Text quoted from a site or a reader into a pull request or issue goes through `quoted()` and `link()` in `watch_guides.py`, and `clean_name()` in `upload_notice.py`.
- The jobs install Python packages by hash from `tools/*-lock.txt` (`uv pip compile --universal --generate-hashes`, build tools first and then `--no-build-isolation`). `tests/test_requirements.py` holds the locks to the plain `requirements*.txt` pins, so rerun it after changing one.
- Actions are pinned by commit id and bumped by Dependabot. A ruleset restricting updates to `main` was tried and removed: on a personal repository it blocks the owner's own merges.
- `tests/test_vendor.py` holds the Leaflet copy to its official fingerprint.
- The app shows nothing when framed by another page.

### Content security policy and the map library

- `index.html` has a Content Security Policy `<meta>` tag allowing scripts and styles only from the app's own files: no inline script or style anywhere (the saved theme is applied by `theme.js`; the theme swatches are classes).
- Anything new that loads a `blob:`, `data:` or outside URL needs the policy updated too. Photos for upload are read through `blob:` URLs. The map's tiles come from `tile.openstreetmap.org` (img-src).
- Nothing in the app talks to OpenStreetMap's query service: the publish job does, for the branch list.
- The map library is a copy in `site/vendor/leaflet/`, loaded only when a map opens. Pins are `circleMarker`s, so none of Leaflet's images are needed.

### Branch list, Near me and the look-around

- `restaurant.json` `osm` lists what OpenStreetMap calls a chain's branches. `tools/fetch_branches.py` matches them in the publish job (also every Monday) into `site/data/branches.json`: `{fetched, chains: [id], b: [[chain number, lat, lon, street, opening_hours]]}`, about 5,600 rows.
- Near me and the map read it on the phone (`loadBranches()`, `branchOf()`, `nearRows()`; last Near me answer kept in `gf-near`).
- The phone never queries Overpass, because the public servers are often too busy to answer a phone in time.
- Only the Monday run (and a run by hand) asks Overpass. A push publishes the live list again while it's under a week old (`--reuse-days 7`).
- A busy week, a list that lost a fifth of its rows or every branch of a chain, or any error keeps the live list (`from_live`, `broken()`), inside a fixed time budget. The step can't fail the publish (`continue-on-error`).
- The app loads the list quietly at startup. The list is optional at service worker install (`EXTRA` in `sw.js`, carried over from the last release's cache when the site has none), and `newest()` answers a 404 or 5xx with the saved copy, so one bad publish never takes the pins off a phone.
- The pull request check has no list: `ui_check.py` serves its own through `with_branches()`, with the service worker blocked so the route applies.
- The look around when the app opens (`gf-near-auto`; `autoNear()`, offered once in the Near me sheet and switchable in Help):
  - reads the position at most every ten minutes and matches it against the branch list (`lookNear()`);
  - runs only when the phone already reports the permission as granted (`locationGranted()`), so no prompt appears unasked;
  - `osmToday()` and `openText()` read OpenStreetMap's `opening_hours` in its plain shapes only and show nothing otherwise;
  - `nearChipText()` puts the answer on the Near me chip (every UK page) and `renderPicker()` in a Near you group;
  - outside the UK (`inUK`) no chain is named, and a city page's chip names the nearest listed place still open.
- A restaurant the phone hasn't seen is in `gf-known-restaurants` and New (a note on All, a tag in the chooser) until opened or dismissed (`noteNewRestaurants`, `isNew`, `sawRestaurant`).
- `favLine()` says in the new-guide note whether the favourites there survived, judging "gone" from the menu itself, so a long-gone favourite is never called unchanged.

### The map page

- `#mapPage`, opened by the globe `#mapBtn` by the title (`openLiveMap()` and the `live` state in `app.js`).
- It uses `watchPosition` only while it's open and the app is visible.
- It draws the branch list's pins for the part of the map on screen, at zoom 13 or closer (at most 300, nearest the middle first).
- A redraw adds and removes only the difference and keeps the pin whose popup is open, because opening one pans the map.
- The list loads after the map, so a weak signal doesn't hold it up.
- Zoomed out over the UK, `#mapHint` says to zoom in.
- Every city list's places, in the UK and abroad, are pinned from `cities.json`.

### Push notifications

- `tools/push.py`: plan in the build job, send in the `notify` job after the deploy.
- `push-message.json` holds `{"messages": [...]}`: the new guides, then "<City> is in the app" for a city the live `cities.json` (`.previous/cities.json`) lacks, then "Update N is live!" when `APP_VERSION` passed the live one.
- `fetch_previous.py` saves the live version as `.previous/app-version`, and `site/whatsnew.json` has notes for it.
- The notification opens `?whatsnew`, a query because the release before reads a `#` as a page name. To announce a release, put its notes at the top of `whatsnew.json`.
- The key pair is split between `PUSH_KEY` in `app.js` and the `VAPID_PRIVATE_KEY` secret. A phone records the key it subscribed with in `gf-push-key`. After a new pair, `pushState()` lets an old-key subscription go and asks for a tap, since an iPhone subscribes only from a tap.
- Phones' subscriptions are saved by hand in `PUSH_SUBSCRIPTIONS`.
- `test-notification.yml` (run by hand) sends `push.py --test` to every phone. It lists each with a check code (the first 8 hex of the SHA-256 of its endpoint) that the app shows too (`pushCode()`), so a stale line in the secret shows up without the address going in the public log.
- `sw.js` reads the favourites from IndexedDB (`gf`/`kv`/`favs`, mirrored by `saveFavs()`) to say when one now contains gluten, giving up after 1.5 seconds so a notification always shows.

### Notes and speech

- Personal notes are `gf-notes` (keyed like favourites) and travel in the favourites link (`v: 2`, `n`).
- The coeliac card's Say it uses the phone's own speech (`SPEECH_LANG` maps a card's language to a voice locale).

### Adding a restaurant from a new PDF layout

- Write a reader, compare its output row by row against the rendered pages, and add a cross-check between the guide's own sources where possible.
- Make the reader stop the build on anything it can't place (stray marks, two drinks run together).

### Known gaps

- Hotel Chocolat publishes no café allergen guide online. Add it from photos of the in-café information via the app's Add menu.
- Knoops' newest guide is from March 2024, so it shows as possibly out of date.
- Not yet tested on a real device: installing, in-app upload with a real GitHub key, the first daily scan of a real menu, the reminder workflow's first issue. The German coeliac card hasn't been checked by a native speaker.

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
- `tools/upload_notice.py`: opens an issue for each upload, and each place or city asked for by name, waiting on the `uploads` branch
- `tools/push.py`: the notifications after a publish with a new guide or an announced release (`--plan` in the build job, `--send` after the deploy), and a test notification by hand (`--test`, from `test-notification.yml`)
- `site/whatsnew.json`: each announced release's notes, for What's new and the release notification
- `tools/requirements.txt`, `requirements-dev.txt`, `requirements-notify.txt`, `requirements-buildtools.txt`: the Python packages, as people install them; `tools/*-lock.txt`: the same with every package's hash, as the jobs install them; `.github/dependabot.yml`: keeps the pinned actions current and flags a vulnerable package
- `site/vendor/leaflet/`: the map library (Leaflet 1.9.4, BSD licence), a copy because the app's security policy allows scripts from its own files only; the map's tiles come from OpenStreetMap while the map is open and are never kept
- `site/guides/` (generated): each restaurant's current guide, published so "Guide page 7" can open it
- `tools/adapters/`: readers for each kind of allergen guide
- `tools/SCAN_INSTRUCTIONS.md`: what the daily scan does with uploads
- `inbox/` on the `uploads` branch: uploads waiting to be scanned
- `.github/workflows/keep-alive.yml`: keeps the scheduled workflows switched on
- `site/phrases.json`: gluten free card phrases (add a language here)
- `site/cities.json`: hand-checked places in cities (`"group": "uk"` for a UK city, anything else for Abroad)
- `tools/fetch_nandos.py`: saves Nando's allergen pages as a snapshot for its reader
- `site/`: the app (HTML, CSS, JavaScript, offline support, icons)

Unofficial. Not affiliated with any restaurant.
