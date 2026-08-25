#!/usr/bin/env python3
"""
Rebuild the setlist archive in index.html from the band's Google Sheet.

Spreadsheet convention
----------------------
ONE tab, one song per row, with these columns (order doesn't matter, the
header names are what count):

    Date        2025-11-22   — repeated on every row of that show
    Venue       Three Heads Brewing
    City        Rochester, NY   — optional
    Set         Set I | Set II | Set III | Encore
    Song        one song, in the order played

Segues: write them as you would by hand — put ">" or "->" at the end of the
song it flows out of ("Tweezer >"), or put both songs in one cell
("Lawn Boy > Hold Your Head Up"). Either way the site prints them in pink.

The sheet must stay published: File > Share > Publish to web.

Usage
-----
  python3 scripts/build_setlists.py                  # pull from the live sheet
  python3 scripts/build_setlists.py --local FILE.csv # parse a local export
  python3 scripts/build_setlists.py --debug          # verbose
"""

import argparse, csv, html, io, os, re, sys, urllib.request, urllib.error
from datetime import date, datetime

PUB_ID = ("2PACX-1vST7H40jW8Xxfr6AZueb6Sa_WayMFtmHGip1m6vQRytnw5RyH0"
          "Jh31ohnhe_xHH14InlPJXAvqYFTpE")
CSV_URL = ("https://docs.google.com/spreadsheets/d/e/%s/pub?output=csv" % PUB_ID)

START, END = "<!-- SETLISTS:START -->", "<!-- SETLISTS:END -->"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
DEBUG = False

# header name -> which field, tolerant of casing, spaces and simple synonyms
FIELDS = {
    "date": "date", "show date": "date",
    "venue": "venue", "location": "venue",
    "city": "city", "town": "city", "city, state": "city",
    "set": "set", "set name": "set", "setname": "set",
    "song": "song", "songs": "song", "title": "song", "track": "song",
}
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d",
                "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%m-%d-%Y", "%m-%d-%y"]


def log(*a):
    print(*a, flush=True)


def fetch_csv():
    req = urllib.request.Request(CSV_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; nasty-flyers-site/1.0)",
        "Accept": "text/csv,*/*",
    })
    log("  fetching %s" % CSV_URL)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8-sig", "replace")
            log("  got %d bytes (HTTP %s)" % (len(body), r.status))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        log("  !! HTTP %s — is the sheet still published to the web?" % e.code)
        log("     File > Share > Publish to web > Entire document > Publish")
        save_debug(body, "HTTP %s body" % e.code)
        sys.exit(1)
    except Exception as e:
        log("  !! %s: %s" % (type(e).__name__, e))
        sys.exit(1)

    if body.lstrip()[:1] == "<":
        log("  !! Got HTML back, not CSV — the publish link may have been revoked.")
        save_debug(body, "unexpected HTML response")
        sys.exit(1)
    save_debug(body, "for reference")
    return body


def save_debug(text, why):
    try:
        with open("debug-sheet.csv", "w", encoding="utf-8") as fh:
            fh.write(text)
        log("  wrote debug-sheet.csv (%d bytes) — %s" % (len(text), why))
    except Exception as e:
        log("  (could not write debug file: %s)" % e)


def map_columns(header):
    """Header row -> {field: column index}."""
    cols = {}
    for i, name in enumerate(header):
        key = re.sub(r'\s+', ' ', (name or "").strip().lower())
        if key in FIELDS and FIELDS[key] not in cols:
            cols[FIELDS[key]] = i
    return cols


def parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    m = re.match(r'^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$', raw)
    if m:
        mo, dy, yr = (int(x) for x in m.groups())
        yr += 2000 if yr < 100 else 0
        try:
            return date(yr, mo, dy)
        except ValueError:
            pass
    return None


def tidy_set(raw):
    s = re.sub(r'\s+', ' ', (raw or "").strip())
    if not s:
        return "Set I"
    m = re.match(r'^(encore|enc|e)\b\s*(.*)$', s, re.I)
    if m:
        return ("Encore %s" % m.group(2).strip()).strip()
    m = re.match(r'^set\s*([ivx]+|\d+)$', s, re.I)
    if m:
        tok = m.group(1)
        if tok.isdigit():
            n = int(tok)
            return "Set %s" % ("I" * n if n <= 3 else n)
        return "Set %s" % tok.upper()
    return s


def read_rows(text):
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        sys.exit("  !! The sheet is empty.")
    cols = map_columns(rows[0])
    if DEBUG:
        log("  header: %s" % rows[0])
        log("  columns matched: %s" % cols)
    missing = [f for f in ("date", "venue", "set", "song") if f not in cols]
    if missing:
        log("  !! Missing column(s): %s" % ", ".join(missing))
        log("     Found header: %s" % rows[0])
        log("     Expected: Date, Venue, City, Set, Song")
        sys.exit(1)

    def cell(row, field):
        i = cols.get(field, -1)
        return (row[i].strip() if 0 <= i < len(row) and row[i] else "")

    shows, order, skipped = {}, [], 0
    for row in rows[1:]:
        song = cell(row, "song")
        if not song:
            continue
        d = parse_date(cell(row, "date"))
        if d is None:
            skipped += 1
            if skipped <= 3:
                log("  !! skipping row with unreadable date: %r" % (row[:5],))
            continue
        key = (d, cell(row, "venue"), cell(row, "city"))
        if key not in shows:
            shows[key] = {}
            order.append(key)
        label = tidy_set(cell(row, "set"))
        shows[key].setdefault(label, []).append(song)
    if skipped:
        log("  !! %d row(s) skipped for an unreadable date" % skipped)

    out = []
    for key in order:
        d, venue, city = key
        sections = list(shows[key].items())
        out.append((d, venue, city, sections))
        log("  %s  %-22s %d set(s), %d song(s)"
            % (d, venue, len(sections), sum(len(s) for _, s in sections)))
    return out


# ----------------------------------------------------------------- rendering
def render_songs(songs):
    parts = []
    for i, song in enumerate(songs):
        s = song.strip()
        seg = ""
        m = re.search(r'\s*(->|>)\s*$', s)
        if m:
            seg = m.group(1)
            s = s[:m.start()].strip()
        # escape first, THEN find segues — otherwise ">" is already "&gt;"
        body = re.sub(r'\s*(-&gt;|&gt;)\s*',
                      lambda mm: ' <i class="sg">%s</i> ' % mm.group(1),
                      html.escape(s))
        if seg:
            parts.append(body + ' <i class="sg">%s</i> ' % html.escape(seg))
        else:
            parts.append(body + ("" if i == len(songs) - 1 else ", "))
    return "".join(parts).strip().rstrip(",")


def render_show(d, venue, city, sections, is_first):
    when = "%s %d, %d" % (MONTHS[d.month - 1], d.day, d.year)
    where = html.escape(venue) + (" &middot; " + html.escape(city) if city else "")
    sets = "\n".join(
        '        <div class="set"><span class="set-label">%s</span>'
        '<p class="songs">%s</p></div>' % (html.escape(label), render_songs(songs))
        for label, songs in sections)
    return ('      <details class="show"%s>\n'
            '        <summary>\n'
            '          <span class="show-when">%s</span>\n'
            '          <span class="show-where">%s</span>\n'
            '        </summary>\n%s\n      </details>'
            % (" open" if is_first else "", when, where, sets))


def build(shows):
    shows.sort(key=lambda s: s[0], reverse=True)
    if not shows:
        return '      <p class="dim">Setlists are on their way.</p>'
    out, year = [], object()
    for i, (d, venue, city, sections) in enumerate(shows):
        if d.year != year:
            year = d.year
            out.append('      <p class="setlist-year">%d</p>' % year)
        out.append(render_show(d, venue, city, sections, i == 0))
    return "\n".join(out)


def main():
    global DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="a .csv export to read instead of the live sheet")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    DEBUG = args.debug

    if args.local:
        text = open(args.local, encoding="utf-8-sig").read()
        log("  reading %s (%d bytes)" % (args.local, len(text)))
    else:
        text = fetch_csv()

    shows = read_rows(text)
    if not shows:
        log("")
        log("  !! No setlists parsed — leaving index.html untouched.")
        sys.exit(1)

    page = open(args.index, encoding="utf-8").read()
    if START not in page or END not in page:
        sys.exit("  !! Markers not found in %s" % args.index)
    a, b = page.index(START) + len(START), page.index(END)
    new = page[:a] + "\n" + build(shows) + "\n" + page[b:]
    if new == page:
        log("")
        log("No change.")
        return
    open(args.index, "w", encoding="utf-8").write(new)
    log("")
    log("Updated %s with %d show(s)." % (args.index, len(shows)))


if __name__ == "__main__":
    main()
