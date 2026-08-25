#!/usr/bin/env python3
"""
Rebuild the setlist archive in index.html from the band's Google Sheet.

The spreadsheet convention
--------------------------
  * One tab per show.
  * Tab name  = "<Venue> <M>/<D>/<YY>"      e.g. "Three Heads Brewing 11/22/25"
                or "<Venue>, <City> <M>/<D>/<YY>" if you want a city shown.
  * Column A  = one song per row, in order.
  * A BLANK ROW starts a new set. (Two blank rows is fine too — any run of
    blanks counts as one break.)
  * Sets are labelled automatically: Set I, Set II, ... and the final short
    section becomes the Encore. To override, put a row containing just
    "Set 1", "Set II", "Encore" etc. and it will be used verbatim.
  * Segues: end a song with ">" or "->" exactly as you'd write it by hand.

Usage
-----
  python3 scripts/build_setlists.py                 # pull from the live sheet
  python3 scripts/build_setlists.py --local DIR     # parse .csv files in DIR
"""

import argparse, csv, html, io, os, re, sys, urllib.request
from datetime import date

PUB_ID = ("2PACX-1vST7H40jW8Xxfr6AZueb6Sa_WayMFtmHGip1m6vQRytnw5RyH0"
          "Jh31ohnhe_xHH14InlPJXAvqYFTpE")
PUBHTML = "https://docs.google.com/spreadsheets/d/e/%s/pubhtml" % PUB_ID
SHEETCSV = ("https://docs.google.com/spreadsheets/d/e/%s/pub"
            "?gid=%%s&single=true&output=csv" % PUB_ID)

START, END = "<!-- SETLISTS:START -->", "<!-- SETLISTS:END -->"
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
LABEL_RE = re.compile(r'^(set\s*[ivx0-9]+|encore\s*\d*|e\d?)$', re.I)
DATE_RE  = re.compile(r'^(?P<venue>.*?)[\s_-]*'
                      r'(?P<m>\d{1,2})[/_\s.-](?P<d>\d{1,2})[/_\s.-](?P<y>\d{2,4})\s*$')


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nasty-flyers-site/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def discover_tabs():
    """Return [(sheet_name, gid), ...] from the published workbook."""
    page = get(PUBHTML)
    tabs = re.findall(r'<li[^>]*id="sheet-button-(\d+)"[^>]*>.*?>([^<]+)</a>', page, re.S)
    if not tabs:                      # fallback for the older markup
        tabs = re.findall(r'#gid=(\d+)[^>]*>\s*([^<]+?)\s*<', page)
    seen, out = set(), []
    for gid, name in tabs:
        name = html.unescape(name).strip()
        if gid not in seen and name:
            seen.add(gid); out.append((name, gid))
    return out


def parse_rows(rows):
    """Rows of column A -> [(label, [songs]), ...]"""
    sections, cur, explicit = [], [], {}
    for raw in rows:
        cell = (raw[0].strip() if raw else "")
        if not cell:
            if cur:
                sections.append(cur); cur = []
            continue
        if LABEL_RE.match(cell):                       # an explicit set label
            if cur:
                sections.append(cur); cur = []
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
    """'Three Heads Brewing 11/22/25' -> (date, 'Three Heads Brewing', city)"""
    m = DATE_RE.match(name.strip())
    if not m:
        return None, name.strip(), ""
    y = int(m.group("y"));  y += 2000 if y < 100 else 0
    try:
        d = date(y, int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None, name.strip(), ""
    venue = m.group("venue").replace("_", " ").strip(" ,-")
    city = ""
    if "," in venue:
        venue, city = [p.strip() for p in venue.split(",", 1)]
    return d, venue, city


def render_songs(songs):
    """Flowing phish.net-style line: segues kept, everything else comma joined."""
    parts = []
    for i, song in enumerate(songs):
        s = song.strip()
        seg = ""
        m = re.search(r'\s*(->|>)\s*$', s)
        if m:
            seg = m.group(1); s = s[:m.start()].strip()
        # segues written inside one cell, e.g. "Lawn Boy > Hold Your Head Up"
        body = re.sub(r'\s*(->|>)\s*',
                      lambda mm: ' <i class="sg">%s</i> ' % html.escape(mm.group(1)),
                      html.escape(s))
        last = i == len(songs) - 1
        if seg:
            parts.append(body + ' <i class="sg">%s</i> ' % html.escape(seg))
        else:
            parts.append(body + ("" if last else ", "))
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
            '        </summary>\n'
            '%s\n'
            '      </details>' % (" open" if is_first else "", when, where, sets))


def build(shows):
    shows.sort(key=lambda s: (s[0] is not None, s[0] or date.min), reverse=True)
    if not shows:
        return '      <p class="dim">Setlists are on their way.</p>'
    out, year = [], None
    for i, (d, venue, city, sections) in enumerate(shows):
        y = d.year if d else None
        if y != year:
            year = y
            out.append('      <p class="setlist-year">%s</p>' % (y or "Undated"))
        out.append(render_show(d, venue, city, sections, i == 0))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="directory of exported .csv files")
    ap.add_argument("--index", default="index.html")
    args = ap.parse_args()

    shows = []
    if args.local:
        for fn in sorted(os.listdir(args.local)):
            if not fn.lower().endswith(".csv"):
                continue
            name = re.sub(r'^.*Setlists?[_ -]+', '', fn[:-4]).replace("_", " ")
            with open(os.path.join(args.local, fn), newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh))
            d, venue, city = parse_title(name)
            shows.append((d, venue, city, parse_rows(rows)))
            print("  parsed %-42s %s" % (name, d))
    else:
        tabs = discover_tabs()
        if not tabs:
            sys.exit("Could not find any tabs — is the sheet still published to the web?")
        for name, gid in tabs:
            rows = list(csv.reader(io.StringIO(get(SHEETCSV % gid))))
            d, venue, city = parse_title(name)
            shows.append((d, venue, city, parse_rows(rows)))
            print("  parsed %-42s %s" % (name, d))

    page = open(args.index, encoding="utf-8").read()
    a, b = page.index(START) + len(START), page.index(END)
    new = page[:a] + "\n" + build(shows) + "\n" + page[b:]
    if new == page:
        print("No change.")
        return
    open(args.index, "w", encoding="utf-8").write(new)
    print("Updated %s with %d show(s)." % (args.index, len(shows)))


if __name__ == "__main__":
    main()
