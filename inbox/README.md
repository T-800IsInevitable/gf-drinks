# Inbox

Menus uploaded from the app's **Add menu** button land here, one folder per upload:

```
inbox/2026-11-03T1012-cafe-name/
  upload.json      restaurant name, area, notes, who uploaded and when
  menu.pdf         (or photos: page-1.jpg, page-2.jpg, …)
```

Each day a scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md`: it reads each upload, works out the gluten free options, translates them if needed, and opens a **pull request** for you to check. Nothing goes live until you merge it.

You can also drop files here yourself from the GitHub app or website. Add an `upload.json` or name the folder after the restaurant.
