#!/usr/bin/env python3
"""
Rebuild the setlist archive in index.html from the band's Google Sheet.

Spreadsheet convention
----------------------
  * One tab per show.
  * Tab name  = "<Venue> <M>/<D>/<YY>"   e.g. "Three Heads Brewing 11/22/25"
                or "<Venue>, <City> <M>/<D>/<YY>" to show a city.
  * Column A  = one song per row, in order.
  * A BLANK ROW starts a new set (two blanks is fine - a run counts as one).
  * Sets are labelled Set I, Set II, ...; a short final section becomes the
    Encore. Override by putting a row containing just "Set 1" / "Encore".
  * Segues: write ">" or "->" exactly as you would by hand.

Usage
-----
  python3 scripts/build_setlists.py              # pull from the live sheet
  python3 scripts/build_setlists.py --local DIR  # parse .csv files in DIR
  python3 scripts/build_setlists.py --debug      # verbose fetch diagnostics
"""

import argparse, csv, html, io, os, re, sys, urllib.request, urllib.error
from datetime import date

PUB_ID = ("2PACX-1vST7H40jW8Xxfr6AZueb6Sa_WayMFtmHGip1m6vQRytnw5RyH0"
          "Jh31ohnhe_xHH14InlPJXAvqYFTpE")
BASE = "https://docs.google.com/spreadsheets/d/e/%s" % PUB_ID
PUBHTML = BASE + "/pubhtml"
SHEETCSV = BASE + "/pub?gid=%s&single=true&output=csv"

START, END = "<!-- SETLISTS:START -->", "<!-- SETLISTS:END -->"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
LABEL_RE = re.compile(r'^(set\s*[ivx0-9]+|encore\s*\d*|e\d?)$', re.I)
DATE_RE  = re.compile(r'^(?P<venue>.*?)[\s_-]*'
                      r'(?P<m>\d{1,2})[/_\s.-](?P<d>\d{1,2})[/_\s.-](?P<y>\d{2,4})\s*$')
DEBUG = False


def log(*a):
    print(*a, flush=True)


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; nasty-flyers-site/1.0)",
        "Accept": "text/html,text/csv,*/*",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "replace")
    if DEBUG:
        log("      fetched %d bytes" % len(body))
    return body


def strip_tags(s):
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', '', s)).replace('\xa0', ' ').strip()


# ---------------------------------------------------------------- discovery
def find_tab_names(page):
    """[(gid, name)] from the sheet-tab menu, trying a few known markups."""
    pats = [
        r'<li[^>]*\bid="sheet-button-(\d+)"[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+?)\s*<',
        r'id="sheet-button-(\d+)"[^>]*>(?:(?!</li>).)*?>([^<]+?)<',
        r'href="[^"]*#gid=(\d+)"[^>]*>\s*([^<]+?)\s*<',
    ]
    for i, p in enumerate(pats):
        found = re.findall(p, page, re.S)
        if found:
            if DEBUG:
                log("      tab names via pattern %d: %d found" % (i + 1, len(found)))
            out, seen = [], set()
            for gid, name in found:
                name = html.unescape(name).strip()
                if gid not in seen and name:
                    seen.add(gid)
                    out.append((gid, name))
            return out
    return []


def tables_from_pubhtml(page):
    """{gid: [rows]} parsed straight out of the published page."""
    out = {}
    blocks = re.split(r'<div[^>]*\bid="(\d+)"', page)
    for i in range(1, len(blocks), 2):
        gid, chunk = blocks[i], blocks[i + 1]
        m = re.search(r'<table.*?</table>', chunk, re.S)
        if not m:
            continue
        rows = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(0), re.S):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            rows.append([strip_tags(cells[0])] if cells else [""])
        if rows:
            out[gid] = rows
    return out


def load_from_sheet():
    log("  fetching %s" % PUBHTML)
    page = get(PUBHTML)
    log("  published page: %d bytes" % len(page))

    tabs = find_tab_names(page)
    log("  tabs found: %d" % len(tabs))
    if not tabs:
        log("")
        log("  !! Could not read the tab list.")
        log("     Check: File > Share > Publish to web > Entire document > Publish.")
        log("")
        log("----- first 1500 chars of what came back -----")
        log(page[:1500])
        sys.exit(1)

    embedded = tables_from_pubhtml(page)
    if DEBUG:
        log("      tables embedded in the page: %d" % len(embedded))

    shows = []
    for gid, name in tabs:
        rows = embedded.get(gid)
        source = "page"
        if not rows:
            try:
                rows = list(csv.reader(io.StringIO(get(SHEETCSV % gid))))
                source = "csv"
            except urllib.error.HTTPError as e:
                log("  !! %-38s skipped (HTTP %s)" % (name, e.code))
                continue
        d, venue, city = parse_title(name)
        sections = parse_rows(rows)
        songs = sum(len(s[1]) for s in sections)
        log("  parsed %-38s %-11s %d sets, %d songs (%s)"
            % (name, str(d) if d else "no date", len(sections), songs, source))
        if songs:
            shows.append((d, venue, city, sections))
    return shows


# ------------------------------------------------------------------ parsing
def parse_rows(rows):
    sections, cur, explicit = [], [], {}
    for raw in rows:
        cell = (raw[0].strip() if raw and raw[0] else "")
        if not cell:
            if cur:
                sections.append(cur)
                cur = []
            continue
        if LABEL_RE.match(cell):
            if cur:
                sections.append(cur)
                cur = []
            explicit[len(sections)] = cell
            continue
        cur.append(cell)
    if cur:
        sections.append(cur)

    out, setno = [], 0
    for i, songs in enumerate(sections):
        if i in explicit:
            label = explicit[i]
        elif i == len(sections) - 1 and len(sections) > 1 and len(songs) <= 3:
            label = "Encore"
        else:
            setno += 1
            label = "Set %s" % ("I" * setno if setno <= 3 else setno)
        out.append((label, songs))
    return out


def parse_title(name):
    m = DATE_RE.match(name.strip())
    if not m:
        return None, name.strip(), ""
    y = int(m.group("y"))
    y += 2000 if y < 100 else 0
    try:
        d = date(y, int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None, name.strip(), ""
    venue = m.group("venue").replace("_", " ").strip(" ,-")
    city = ""
    if "," in venue:
        venue, city = [p.strip() for p in venue.split(",", 1)]
    return d, venue, city


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
    when = "%s %d, %d" % (MONTHS[d.month - 1], d.day, d.year) if d else ""
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
    shows.sort(key=lambda s: (s[0] is not None, s[0] or date.min), reverse=True)
    if not shows:
        return '      <p class="dim">Setlists are on their way.</p>'
    out, year = [], object()
    for i, (d, venue, city, sections) in enumerate(shows):
        y = d.year if d else None
        if y != year:
            year = y
            out.append('      <p class="setlist-year">%s</p>' % (y or "Undated"))
        out.append(render_show(d, venue, city, sections, i == 0))
    return "\n".join(out)


def main():
    global DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="directory of exported .csv files")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    DEBUG = args.debug

    if args.local:
        shows = []
        for fn in sorted(os.listdir(args.local)):
            if not fn.lower().endswith(".csv"):
                continue
            name = re.sub(r'^.*Setlists?[_ -]+', '', fn[:-4]).replace("_", " ")
            with open(os.path.join(args.local, fn), newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh))
            d, venue, city = parse_title(name)
            shows.append((d, venue, city, parse_rows(rows)))
            log("  parsed %-38s %s" % (name, d))
    else:
        shows = load_from_sheet()

    if not shows:
        log("")
        log("  !! No setlists parsed - leaving index.html untouched.")
        sys.exit(1)

    page = open(args.index, encoding="utf-8").read()
    if START not in page or END not in page:
        sys.exit("Markers not found in %s" % args.index)
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
