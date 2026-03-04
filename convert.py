#!/usr/bin/env python3
"""
convert.py — Batch converter for Tenedian Brotherhood family tree pages.

Reads Windows-1252 encoded HTML files from the source directory,
strips FrontPage markup and Wayback Machine artifacts, parses
dot-notation genealogy text, and outputs clean HTML5 family tree pages.

Usage:
    python3 convert.py --source ~/tenedian-recovery/site/ \
                       --output ~/tenedian-brotherhood-new/ \
                       --verbose
"""

import argparse
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# ── Pages to skip (main nav pages, not family trees) ──────────────────────────
SKIP_PAGES = {
    "index.html", "index.htm",
    "calendar of events.html", "calendar of events.htm",
    "contact us.html", "contact us.htm",
    "family trees.html", "family trees.htm",
    "food and wine.html", "food and wine.htm",
    "food wine.html", "food wine.htm",
    "georg fenady & actors photos.html", "georg fenady & actors photos.htm",
    "greek superstitions.html", "greek superstitions.htm",
    "how tenedos was named.html", "how tenedos was named.htm",
    "just for fun.html", "just for fun.htm",
    "links.htm", "links.html",
    "photo gallery.html", "photo gallery.htm",
    "tenedian brotherhood history.html", "tenedian brotherhood history.htm",
    "tenedian obituaries.html", "tenedian obituaries.htm",
    "tenedian obituaries 2.html", "tenedian obituaries 2.htm",
    "tenedian obituaries 3.html", "tenedian obituaries 3.htm",
    "tenedian obituaries 4.html", "tenedian obituaries 4.htm",
    "tenedian obituaries pg2.html", "tenedian obituaries pg2.htm",
    "tenedian obituaries pg3.html", "tenedian obituaries pg3.htm",
    "tenedian obituaries pg4.html", "tenedian obituaries pg4.htm",
    # photo album / misc non-family pages
    "apokria 2001.html", "apokria 2001.htm",
    "picnic 2002.html", "picnic 2002.htm",
    "picnic 2003.html", "picnic 2003.htm",
    "picnic 2004.html", "picnic 2004.htm",
    "veterans.html", "veterans.htm",
    "souvenir programs.html", "souvenir programs.htm",
    # food/wine and photo pages accidentally included
    "food wine & recipes.html", "food wine & recipes.htm",
    "food wine _ recipes.html", "food wine _ recipes.htm",
    "photo gallery index page.html", "photo gallery index page.htm",
    "tenedian wedding page 2.html", "tenedian wedding page 2.htm",
    # obituary pages (handled separately)
    "tenedian obituaries - page 2.html", "tenedian obituaries - page 2.htm",
    "tenedian obituaries - page 3.html", "tenedian obituaries - page 3.htm",
    "tenedian obituaries - page 4.html", "tenedian obituaries - page 4.htm",
    # variant fenady photo page (underscore instead of &)
    "georg fenady _ actors photos.html", "georg fenady _ actors photos.htm",
    # stub/test pages
    "pavlis.html", "pavlis.htm",
}

# ── HTML text extractor ────────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    """Extracts plain text from HTML, collecting paragraph/div text."""
    def __init__(self):
        super().__init__()
        self._lines = []
        self._current = []
        self._in_body = False
        self._skip_tags = {"script", "style", "head"}
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        if tag == "title":
            self._in_title = True
        if tag in self._skip_tags:
            self._skip += 1
        if tag in ("p", "div", "br", "h1", "h2", "h3", "li"):
            if self._current:
                line = "".join(self._current).strip()
                if line:
                    self._lines.append(line)
                self._current = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            if self._current:
                self.title = "".join(self._current).strip()
                self._current = []
        if tag in self._skip_tags:
            self._skip -= 1
        if tag in ("p", "div", "h1", "h2", "h3", "li"):
            if self._current:
                line = "".join(self._current).strip()
                if line:
                    self._lines.append(line)
                self._current = []

    def handle_data(self, data):
        if self._in_title:
            self._current.append(data)
            return
        if self._skip > 0 or not self._in_body:
            return
        self._current.append(data)

    def handle_entityref(self, name):
        entities = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ",
                    "quot": '"', "apos": "'", "mdash": "—", "ndash": "–",
                    "lsquo": "'", "rsquo": "'", "ldquo": "\u201c", "rdquo": "\u201d"}
        char = entities.get(name, "")
        if self._in_title:
            self._current.append(char)
        elif self._skip == 0 and self._in_body:
            self._current.append(char)

    def handle_charref(self, name):
        try:
            if name.startswith("x"):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
        except (ValueError, OverflowError):
            char = ""
        if self._in_title:
            self._current.append(char)
        elif self._skip == 0 and self._in_body:
            self._current.append(char)

    def get_lines(self):
        if self._current:
            line = "".join(self._current).strip()
            if line:
                self._lines.append(line)
            self._current = []
        return self._lines


# ── Wayback Machine artifact stripper ─────────────────────────────────────────
WAYBACK_RE = re.compile(
    r"<!--\s*FILE ARCHIVED ON.*?-->|"
    r"<!--\s*Mediatype.*?-->|"
    r"<!--\s*Wayback.*?-->|"
    r"<script[^>]*web\.archive\.org[^>]*>.*?</script>|"
    r"<div[^>]*id=['\"]wm-[^'\"]*['\"][^>]*>.*?</div>",
    re.DOTALL | re.IGNORECASE,
)


def strip_wayback(html: str) -> str:
    return WAYBACK_RE.sub("", html)


# ── Encoding artifact fixer ────────────────────────────────────────────────────
ENCODING_FIXES = [
    ("\u00e2\u0080\u0093", "–"),   # â€" → en dash
    ("\u00e2\u0080\u0094", "—"),   # â€" → em dash
    ("\u00e2\u0080\u0098", "'"),   # â€˜ → left single quote
    ("\u00e2\u0080\u0099", "'"),   # â€™ → right single quote
    ("\u00e2\u0080\u009c", "\u201c"),
    ("\u00e2\u0080\u009d", "\u201d"),
    ("\u00c2\u00a0", " "),         # Â + NBSP → space
    ("\u00c2\u00b7", "·"),
]


def fix_encoding(text: str) -> str:
    for bad, good in ENCODING_FIXES:
        text = text.replace(bad, good)
    return text


# ── Genealogy line parser ──────────────────────────────────────────────────────
PERSON_RE = re.compile(r"^(\d+)\s+(.+)$")
SPOUSE_RE = re.compile(r"^\+(.+)$")
PRIVATE_RE = re.compile(
    r"\bb(?:orn|:)\s*(?:19[2-9]\d|20\d{2})",  # born after 1920
    re.IGNORECASE,
)
HEADING_RE = re.compile(
    r"^(?:descendants? of|family of|the\s+)?(.+?)\s*(?:family tree|family)?$",
    re.IGNORECASE,
)


def count_leading_dots(s: str) -> int:
    count = 0
    for ch in s:
        if ch == ".":
            count += 1
        else:
            break
    return count


def parse_genealogy_lines(raw_lines: list[str]) -> list[dict]:
    """
    Parse lines like:
      "1 Theodore Arvanitis b: Abt. 1810"        → gen 0, person
      ".. +Unknown Wife b: Unknown"               → gen 0, spouse
      "..... 2 Vasilios T. Arvanitis b: Abt.1830" → gen 1, person
    Returns list of {"gen": int, "is_spouse": bool, "is_private": bool, "text": str}
    """
    entries = []
    current_gen = 0

    for raw in raw_lines:
        line = raw.strip()
        if not line or line.isspace():
            continue

        # Skip page-level headings like "Descendants of X" or "Family Trees"
        if re.match(r"^(?:descendants? of|family trees?|click\s|welcome|tenedian)",
                    line, re.IGNORECASE):
            continue

        # Strip leading dots
        dots = count_leading_dots(line)
        line_body = line[dots:].strip()

        if not line_body:
            continue

        # Match person: starts with digit + space
        m_person = PERSON_RE.match(line_body)
        m_spouse = SPOUSE_RE.match(line_body)

        if m_person:
            gen_num = int(m_person.group(1))
            text = m_person.group(2).strip()
            gen = gen_num - 1  # 1-indexed → 0-indexed
            current_gen = gen
            is_private = bool(PRIVATE_RE.search(text)) and "d:" not in text.lower()
            entries.append({
                "gen": gen,
                "is_spouse": False,
                "is_private": is_private,
                "text": fix_encoding(text),
            })
        elif m_spouse:
            text = m_spouse.group(1).strip()
            is_private = bool(PRIVATE_RE.search(text)) and "d:" not in text.lower()
            entries.append({
                "gen": current_gen,
                "is_spouse": True,
                "is_private": is_private,
                "text": fix_encoding(text),
            })
        else:
            # Free-form text, treat as a note at current gen
            text = line_body.strip()
            if text and len(text) > 2:
                entries.append({
                    "gen": current_gen,
                    "is_spouse": False,
                    "is_private": False,
                    "text": fix_encoding(text),
                    "is_note": True,
                })

    return entries


# ── Slug generator ─────────────────────────────────────────────────────────────
def slugify(name: str) -> str:
    """Convert family name to URL-safe slug."""
    slug = name.lower()
    # Replace slashes and common separators with hyphen
    slug = re.sub(r"[/\\|&,]", "-", slug)
    # Remove parentheses content (keep what's inside if helpful)
    slug = re.sub(r"\(.*?\)", "", slug)
    # Keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    # Add -family-tree suffix
    if not slug.endswith("-family-tree"):
        slug = slug + "-family-tree"
    return slug


# ── HTML template ──────────────────────────────────────────────────────────────
NAV_HTML = """<nav class="site-nav" role="navigation" aria-label="Main navigation">
  <div class="nav-inner">
    <a href="index.html" class="nav-brand">Tenedian Brotherhood</a>
    <ul class="nav-links">
      <li><a href="index.html">Home</a></li>
      <li><a href="history.html">History</a></li>
      <li><a href="family-trees.html" class="active">Family Trees</a></li>
      <li><a href="obituaries.html">Obituaries</a></li>
      <li><a href="photo-gallery.html">Photos</a></li>
      <li><a href="food-wine.html">Food &amp; Wine</a></li>
      <li><a href="just-for-fun.html">Just for Fun</a></li>
      <li><a href="calendar.html">Calendar</a></li>
      <li><a href="links.html">Links</a></li>
      <li><a href="contact.html">Contact</a></li>
    </ul>
  </div>
</nav>"""

FOOTER_HTML = """<footer class="site-footer" role="contentinfo">
  <div class="footer-inner">
    <div class="footer-brand">Tenedian Brotherhood</div>
    <nav class="footer-links" aria-label="Footer navigation">
      <a href="index.html">Home</a>
      <a href="history.html">History</a>
      <a href="family-trees.html">Family Trees</a>
      <a href="obituaries.html">Obituaries</a>
      <a href="contact.html">Contact</a>
      <a href="not-recovered.html">Not Archived</a>
    </nav>
    <p class="footer-copy">
      Original content &copy; Tenedian Brotherhood. Website restored and modernized from archived materials.
    </p>
  </div>
</footer>"""


def escape_html(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_entry(entry: dict) -> str:
    classes = ["tree-entry", f"gen-{min(entry['gen'], 4)}"]
    if entry.get("is_spouse"):
        classes.append("spouse")
    if entry.get("is_private"):
        classes.append("private")
    if entry.get("is_note"):
        classes.append("note")

    prefix = "+ " if entry.get("is_spouse") else ""
    text = escape_html(entry["text"])

    if entry.get("is_private"):
        return f'<div class="{" ".join(classes)}">{prefix}<em>Living (born after 1920 — name withheld for privacy)</em></div>\n'

    return f'<div class="{" ".join(classes)}">{prefix}{text}</div>\n'


def build_page(title: str, entries: list[dict], back_link: str = "family-trees.html") -> str:
    entries_html = "".join(render_entry(e) for e in entries)
    if not entries_html.strip():
        entries_html = '<p class="text-muted">No genealogy content could be recovered from this page.</p>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape_html(title)} — Tenedian Brotherhood</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>

{NAV_HTML}

<main>
  <header class="page-header">
    <div class="page-header-inner">
      <h1 class="page-title">{escape_html(title)}</h1>
      <p class="page-subtitle"><a href="{back_link}" style="color:rgba(255,255,255,.6); font-size:.85rem;">&larr; Back to Family Trees</a></p>
    </div>
  </header>

  <div class="page-content">
    <div class="privacy-notice">
      <strong>Privacy notice:</strong> Per the original website policy, birth dates are not
      disclosed for individuals born after 1920 unless they are deceased.
    </div>

    <div class="family-tree-content">
{entries_html}
    </div>
  </div>
</main>

{FOOTER_HTML}

</body>
</html>
"""


# ── Main converter ─────────────────────────────────────────────────────────────
def convert_file(src_path: Path, output_dir: Path, verbose: bool = False) -> tuple[str, str] | None:
    """
    Convert a single family tree HTML file.
    Returns (slug, family_name) on success, None if skipped.
    """
    name_lower = src_path.name.lower()

    # Skip .htm duplicates if .html exists
    if src_path.suffix.lower() == ".htm":
        html_equiv = src_path.with_suffix(".html")
        if html_equiv.exists():
            if verbose:
                print(f"  SKIP (duplicate .htm): {src_path.name}")
            return None

    # Skip non-family-tree pages
    if name_lower in SKIP_PAGES:
        if verbose:
            print(f"  SKIP (nav page): {src_path.name}")
        return None

    # Read with Windows-1252 encoding
    try:
        html = src_path.read_text(encoding="windows-1252", errors="replace")
    except Exception as e:
        print(f"  ERROR reading {src_path.name}: {e}", file=sys.stderr)
        return None

    # Strip Wayback artifacts
    html = strip_wayback(html)

    # Extract text
    parser = TextExtractor()
    try:
        parser.feed(html)
    except Exception as e:
        print(f"  WARN parsing {src_path.name}: {e}", file=sys.stderr)

    raw_lines = parser.get_lines()
    page_title = parser.title.strip() or src_path.stem

    # Determine family name from title
    family_name = page_title
    m = HEADING_RE.match(page_title)
    if m:
        family_name = m.group(1).strip()
        if not family_name.lower().endswith("family"):
            family_name = family_name + " Family"

    # Parse genealogy entries
    entries = parse_genealogy_lines(raw_lines)

    if verbose:
        status = f"{len(entries)} entries" if entries else "EMPTY"
        print(f"  {src_path.name} → {status}")

    # Generate slug and output filename
    slug = slugify(family_name.replace(" Family", "").strip())
    out_name = slug + ".html"
    out_path = output_dir / out_name

    # Build and write output
    page_html = build_page(page_title, entries)
    out_path.write_text(page_html, encoding="utf-8")

    return slug, family_name, out_name


def main():
    parser = argparse.ArgumentParser(description="Convert Tenedian family tree pages to modern HTML5.")
    parser.add_argument("--source", required=True, help="Source directory (tenedian-recovery/site/)")
    parser.add_argument("--output", required=True, help="Output directory (tenedian-brotherhood-new/)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    source_dir = Path(args.source).expanduser()
    output_dir = Path(args.output).expanduser()

    if not source_dir.is_dir():
        print(f"Error: source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all .html and .htm files
    html_files = sorted(
        list(source_dir.glob("*.html")) + list(source_dir.glob("*.htm")),
        key=lambda p: p.name.lower()
    )

    print(f"Found {len(html_files)} HTML/HTM files in {source_dir}")
    print(f"Output → {output_dir}")
    print()

    results = []
    empty = []
    skipped = 0

    for src in html_files:
        result = convert_file(src, output_dir, verbose=args.verbose)
        if result is None:
            skipped += 1
            continue
        slug, family_name, out_name = result
        results.append((family_name, slug, out_name))
        # Check if the output file has entries
        out_path = output_dir / out_name
        content = out_path.read_text(encoding="utf-8")
        if "No genealogy content could be recovered" in content:
            empty.append(out_name)

    # Sort alphabetically by family name
    results.sort(key=lambda x: x[0].lower())

    print()
    print(f"Converted: {len(results)} family trees")
    print(f"Skipped:   {skipped} non-family pages")
    if empty:
        print(f"\nEMPTY pages ({len(empty)}) — may need manual review:")
        for e in empty:
            print(f"  {e}")

    # Print sorted index HTML for family-trees.html
    print()
    print("=" * 70)
    print("SORTED INDEX HTML (paste into family-trees.html):")
    print("=" * 70)
    print()

    # Group by first letter
    by_letter: dict[str, list] = {}
    for family_name, slug, out_name in results:
        letter = family_name[0].upper()
        by_letter.setdefault(letter, []).append((family_name, out_name))

    # Letter nav
    letters = sorted(by_letter.keys())
    print('<div class="letter-nav">')
    for letter in letters:
        print(f'  <a href="#{letter}">{letter}</a>')
    print("</div>")
    print()

    for letter in letters:
        print(f'<div class="letter-section" id="{letter}">')
        print(f'  <div class="letter-heading">{letter}</div>')
        print('  <div class="family-grid">')
        for family_name, out_name in by_letter[letter]:
            print(f'    <a href="{out_name}" class="family-card">{escape_html(family_name)}</a>')
        print("  </div>")
        print("</div>")
        print()


if __name__ == "__main__":
    main()
