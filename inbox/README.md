# Inbox

Menus uploaded from the app's **Add menu** button land in `inbox/` on the **`uploads` branch**, not here on `main`, one folder per upload, all of its files in one commit:

```
inbox/2026-11-03T1012-cafe-name-berlin/
  upload.json      restaurant name, area, notes, who uploaded and when
  menu.pdf         (or photos: page-1.jpg, page-2.jpg, …)
```

Uploads never touch `main`, which is protected: changes to it need a pull request with passing checks. So a lost upload key can't change the live app.

Each day a scheduled Claude task follows `tools/SCAN_INSTRUCTIONS.md`: it reads each upload, works out the gluten free options, translates them if needed, and opens a **pull request** for you to check. Nothing goes live until you merge it.

You can also add files yourself: on GitHub, switch to the `uploads` branch and upload into a new folder under `inbox/`, with an `upload.json` or a folder named after the restaurant.
