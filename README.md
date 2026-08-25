# The Nasty Flyers — thenastyflyers.com

Single-page site for The Nasty Flyers, a Phish tribute band out of Rochester, NY.

## Deploying (GitHub Pages)

1. Push this folder to a repo (files at the **root**, not in a subfolder).
2. **Settings → Pages → Build and deployment → Deploy from a branch**
3. Branch `main`, folder `/ (root)`. Save.

Live in a minute or two at `https://USERNAME.github.io/REPO/`.
For a custom domain, add it under Settings → Pages and point a CNAME at it.

## Structure

```
index.html     the whole site — HTML, CSS and JS in one file
images/        web-optimised images the page displays (~1.7 MB total)
press/         print-quality downloads offered in the press kit (~8 MB)
.nojekyll      tells GitHub Pages to serve files as-is
```

## Editing

**Shows** — nothing to edit. Dates come live from Bandsintown, pulled by the
artist name in the `bit-widget-initializer` block. If the list is ever empty,
`data-artist-name` no longer matches the Bandsintown artist page exactly.

**Swapping a photo** — drop the replacement into `images/` using the same
filename. Nothing else changes. If you use a new filename, update the `<img
src>` (and, for gallery shots, the matching `.shN` rule in the CSS so the
lightbox shows the same picture).

**Press downloads** — add the file to `press/`, then copy one of the existing
`<a class="dl" …>` blocks in the `#downloads` section and edit the path, name
and size. Rebuild `nasty-flyers-press-kit.zip` if you want it in the bundle.

**Setlists** — don't edit these in HTML. They come from one tab of the
setlist spreadsheet, one song per row, with columns:

| Date | Venue | City | Set | Song |
|------|-------|------|-----|------|
| 2025-11-22 | Three Heads Brewing | Rochester, NY | Set I | Ocelot |

Repeat Date/Venue/City/Set down each set (select the four cells and drag the
fill handle), then type the songs. `Set` accepts `Set I`/`Set 1`/`Encore`.
Write segues as you would by hand — `Tweezer >` at the end of a row, or
`Lawn Boy > Hold Your Head Up` in one cell. Rows need not be in date order;
the site always sorts newest first.

Keep everything on the FIRST tab — the script reads that one via the
published CSV link. The sheet must stay published: File > Share > Publish
to web > Entire document.

A nightly GitHub Action rebuilds the archive. To publish immediately, open
the **Actions** tab, pick *Update setlists from Google Sheet*, and press
**Run workflow**. Every run saves what it fetched as a `sheet-debug`
artifact, which is the first thing to check if something looks wrong.

**Text** — bio, lineup and contact details are plain HTML in `index.html`.

## Notes

- Everything works without JavaScript: menu, photo lightbox and scroll reveals
  are CSS-only (`:target` and media queries). JS only adds conveniences —
  copy-to-clipboard, keyboard shortcuts, background scroll-lock. This matters
  because some email clients strip scripts when previewing an HTML attachment.
- Live photos by **Geoff Haller**. Credit him where you can.
- "Phish" is a trademark of the band; keep venue-facing copy in the
  "tribute to" framing rather than anything resembling official branding.
