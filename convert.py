#!/usr/bin/env python3
"""
convert.py — Batch converter for Tenedian Brotherhood family tree pages.

Reads Windows-1252 encoded HTML from the source directory, strips FrontPage
markup and Wayback artifacts, parses dot-notation genealogy text, builds a
nested tree structure, and outputs interactive HTML5 family tree diagrams.

Usage:
    python3 convert.py --source ~/tenedian-recovery/site/ \
                       --output ~/tenedian-brotherhood-new/ \
                       --verbose
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# ── Pages to skip (main nav / non-family-tree pages) ──────────────────────────
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
    "apokria 2001.html", "apokria 2001.htm",
    "picnic 2002.html", "picnic 2002.htm",
    "picnic 2003.html", "picnic 2003.htm",
    "picnic 2004.html", "picnic 2004.htm",
    "veterans.html", "veterans.htm",
    "souvenir programs.html", "souvenir programs.htm",
    "food wine & recipes.html", "food wine & recipes.htm",
    "food wine _ recipes.html", "food wine _ recipes.htm",
    "photo gallery index page.html", "photo gallery index page.htm",
    "tenedian wedding page 2.html", "tenedian wedding page 2.htm",
    "tenedian obituaries - page 2.html", "tenedian obituaries - page 2.htm",
    "tenedian obituaries - page 3.html", "tenedian obituaries - page 3.htm",
    "tenedian obituaries - page 4.html", "tenedian obituaries - page 4.htm",
    "georg fenady _ actors photos.html", "georg fenady _ actors photos.htm",
    "pavlis.html", "pavlis.htm",
}

# ── HTML text extractor ────────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
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
            char = chr(int(name[1:], 16) if name.startswith("x") else int(name))
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


# ── Wayback artifact stripper ──────────────────────────────────────────────────
WAYBACK_RE = re.compile(
    r"<!--\s*FILE ARCHIVED ON.*?-->|<!--\s*Mediatype.*?-->|<!--\s*Wayback.*?-->|"
    r"<script[^>]*web\.archive\.org[^>]*>.*?</script>|"
    r"<div[^>]*id=['\"]wm-[^'\"]*['\"][^>]*>.*?</div>",
    re.DOTALL | re.IGNORECASE,
)


def strip_wayback(html):
    return WAYBACK_RE.sub("", html)


# ── Encoding artifact fixer ────────────────────────────────────────────────────
ENCODING_FIXES = [
    ("\u00e2\u0080\u0093", "–"), ("\u00e2\u0080\u0094", "—"),
    ("\u00e2\u0080\u0098", "'"), ("\u00e2\u0080\u0099", "'"),
    ("\u00e2\u0080\u009c", "\u201c"), ("\u00e2\u0080\u009d", "\u201d"),
    ("\u00c2\u00a0", " "), ("\u00c2\u00b7", "·"),
]


def fix_encoding(text):
    for bad, good in ENCODING_FIXES:
        text = text.replace(bad, good)
    return text


# ── Person text parser ─────────────────────────────────────────────────────────
# Matches " b:" or " b." preceded by a space, capturing birth date up to "d:" or end
BIRTH_RE = re.compile(r'\s+b[.:]\s*(.*?)(?=\s+d[.:]|\s*$)', re.IGNORECASE)
DEATH_RE = re.compile(r'\s+d[.:]\s*(.+)$', re.IGNORECASE)
PRIVATE_YEAR_RE = re.compile(r'\b(?:19[2-9]\d|20\d{2})\b')


def parse_person_text(text):
    """Extract name, birth, death from 'Name b: date d: date' text."""
    text = re.sub(r'\s{2,}', ' ', fix_encoding(text.strip()))

    b_m = BIRTH_RE.search(text)
    d_m = DEATH_RE.search(text)

    if b_m:
        name = text[:b_m.start()].strip()
        birth_raw = b_m.group(1).strip()
        # Strip trailing location info ("in Tenedos, Greece" etc.)
        birth = re.sub(r'\s+in\s+\S.*$', '', birth_raw, flags=re.IGNORECASE).strip()
        birth = birth.rstrip('.,') or None
    else:
        name = text
        birth = None

    death = d_m.group(1).strip().rstrip('.,') if d_m else None

    # "Private" birth means living person
    is_private = bool(birth and birth.lower() == 'private')
    if is_private:
        birth = None
    elif birth and not d_m:
        # Born after 1920 with no recorded death = treat as private
        yr_m = PRIVATE_YEAR_RE.search(birth)
        if yr_m and int(yr_m.group()) >= 1920:
            is_private = True

    return {'name': name, 'birth': birth, 'death': death, 'is_private': is_private}


# ── Genealogy line parser ──────────────────────────────────────────────────────
PERSON_RE = re.compile(r'^(\d+)\s+(.+)$')
SPOUSE_RE = re.compile(r'^\+(.+)$')
# "*2nd Wife of X: SpouseName b: date" — spouse name inline after colon
INLINE_REMARRIAGE_RE = re.compile(
    r'^\*\s*(?:\d+(?:st|nd|rd|th)\s+)?(?:wife|husband|partner)\s+of\s+[^:]+:\s*(.+)$',
    re.IGNORECASE,
)


def count_leading_dots(s):
    count = 0
    for ch in s:
        if ch == '.':
            count += 1
        else:
            break
    return count


def parse_genealogy_lines(raw_lines):
    """Parse dot-notation genealogy lines into flat entry list."""
    entries = []
    current_gen = 0
    dot_to_gen = {}   # dot-count → gen level, so remarriage notes can reset current_gen

    for raw in raw_lines:
        line = fix_encoding(raw.strip())
        if not line:
            continue

        # Skip section headings — we derive section titles from root persons
        if re.match(
            r'^(?:descendants?\s+of|family\s+trees?|click\s|welcome|tenedian)',
            line, re.IGNORECASE
        ):
            continue

        # Strip leading dots
        dots = count_leading_dots(line)
        body = line[dots:].strip()
        if not body:
            continue

        # Normalize internal whitespace: embedded \n and \xa0 from wrapped HTML
        # lines must be collapsed to spaces before regex matching
        body = re.sub(r'[\xa0\t\n\r]+', ' ', body)
        body = re.sub(r' {2,}', ' ', body).strip()
        if not body:
            continue

        m_person = PERSON_RE.match(body)
        m_spouse = SPOUSE_RE.match(body)
        m_inline = INLINE_REMARRIAGE_RE.match(body)

        if m_person:
            gen = int(m_person.group(1)) - 1   # 1-indexed → 0-indexed
            text = m_person.group(2).strip()
            current_gen = gen
            dot_to_gen[dots] = gen   # record dot→gen for remarriage resolution
            entries.append({'gen': gen, 'is_spouse': False, 'text': text})

        elif m_spouse:
            text = m_spouse.group(1).strip()
            entries.append({'gen': current_gen, 'is_spouse': True, 'text': text})

        elif m_inline:
            # "*2nd Wife of X: SpouseName b: date" pattern — appears at same dot level
            # as person X, so use dot_to_gen to find the correct gen rather than stale current_gen
            gen = dot_to_gen.get(dots, current_gen)
            current_gen = gen   # reset so any following + spouse lines are also correct
            text = m_inline.group(1).strip()
            if text and not text.lower().startswith('b:'):
                entries.append({'gen': gen, 'is_spouse': True, 'text': text})
            # else: nothing after the colon (two-line format), skip

        else:
            # Plain note/asterisk line — check if it's a remarriage note that signals
            # the next + spouse line should be at a different gen level
            if re.match(
                r'^\*\s*(?:\d+(?:st|nd|rd|th)\s+)?(?:wife|husband|partner)\s+of\s+',
                body, re.IGNORECASE
            ):
                if dots in dot_to_gen:
                    current_gen = dot_to_gen[dots]

        # Everything else (notes, warnings) is silently dropped

    return entries


# ── Tree builder ───────────────────────────────────────────────────────────────
def ordinal(n):
    return str(n) + {1: 'st', 2: 'nd', 3: 'rd'}.get(n, 'th')


def build_trees(entries):
    """
    Convert flat entry list into nested tree structure.
    Returns a list of root person dicts (usually 1, sometimes 2+ for split families).
    """
    counter = [0]

    def new_id():
        counter[0] += 1
        return 'p' + str(counter[0])

    person_at_level = {}   # gen → current person dict
    roots = []

    for entry in entries:
        gen = entry['gen']

        if not entry['is_spouse']:
            parsed = parse_person_text(entry['text'])
            person = {
                'id': new_id(),
                'name': parsed['name'],
                'm': [],
            }
            if parsed['birth']:
                person['birth'] = parsed['birth']
            if parsed['death']:
                person['death'] = parsed['death']
            if parsed['is_private']:
                person['priv'] = True

            person_at_level[gen] = person
            # Clear all deeper levels (they belong to previous branches)
            for k in list(person_at_level.keys()):
                if k > gen:
                    del person_at_level[k]

            if gen == 0:
                roots.append(person)
            else:
                parent = person_at_level.get(gen - 1)
                if parent:
                    # Attach to parent's most recent marriage; create one if needed
                    if not parent['m']:
                        parent['m'].append({'kids': []})
                    parent['m'][-1]['kids'].append(person)
                else:
                    # No known parent — treat as an additional root
                    roots.append(person)

        else:
            # Spouse entry
            person = person_at_level.get(gen)
            if person is None:
                continue

            parsed = parse_person_text(entry['text'])
            spouse = {'id': new_id(), 'name': parsed['name']}
            if parsed['birth']:
                spouse['birth'] = parsed['birth']
            if parsed['death']:
                spouse['death'] = parsed['death']
            if parsed['is_private']:
                spouse['priv'] = True

            if not person['m']:
                # First marriage
                person['m'].append({'sp': spouse, 'kids': []})
            elif 'sp' not in person['m'][-1]:
                # Pending childless marriage with no spouse yet — fill it in
                person['m'][-1]['sp'] = spouse
            else:
                # Remarriage — label it "2nd marriage", "3rd marriage", etc.
                label = ordinal(len(person['m']) + 1) + ' marriage'
                person['m'].append({'sp': spouse, 'kids': [], 'label': label})

    return roots


# ── Slug / filename generator ──────────────────────────────────────────────────
def slugify(name):
    slug = name.lower()
    slug = re.sub(r'[/\\|&,]', '-', slug)
    slug = re.sub(r'\(.*?\)', '', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-{2,}', '-', slug)
    slug = slug.strip('-')
    if not slug.endswith('-family-tree'):
        slug += '-family-tree'
    return slug


def escape_html(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))


# ── HTML page builder ──────────────────────────────────────────────────────────
NAV_HTML = """\
<nav class="site-nav" role="navigation" aria-label="Main navigation">
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

FOOTER_HTML = """\
<footer class="site-footer" role="contentinfo">
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
    <p class="footer-copy">Original content &copy; Tenedian Brotherhood.
      Website restored and modernized from archived materials.</p>
  </div>
</footer>"""

TREE_CSS = """\
    .tree-page { padding: 0; }
    .tree-outer { overflow-x: auto; padding: 2.5rem 1.5rem 3rem;
                  background: var(--color-off-white, #f8f5f0); }
    .tree-forest { display: flex; flex-direction: column; gap: 3.5rem; }
    .tree-section-heading {
      font-family: var(--font-heading, 'Playfair Display', serif);
      color: var(--color-navy, #0a1628); font-size: 1.2rem;
      margin: 0 0 1.25rem; padding-bottom: 0.4rem;
      border-bottom: 2px solid var(--color-gold, #c9a227); }
    .tree-legend { display: flex; gap: 1.2rem; flex-wrap: wrap;
                   margin-bottom: 2rem; font-size: 0.8rem; color: #555;
                   align-items: center; }
    .legend-item { display: flex; align-items: center; gap: 5px; }
    .ls { width: 20px; height: 13px; border-radius: 3px;
          border: 2px solid var(--color-gold, #c9a227);
          display: inline-block; flex-shrink: 0; }
    .ls.navy  { background: var(--color-navy, #0a1628); }
    .ls.white { background: #fff; }
    .ls.blue  { background: #dce8ff; border-color: #6888cc; }
    .ls.gray  { background: #eee; border-color: #bbb; }
    /* Tree layout */
    .tree-section { overflow-x: auto; padding-bottom: 0.5rem; }
    .tree-root { display: inline-flex; flex-direction: column;
                 align-items: center; padding: 0.5rem 1rem; }
    .tree-node { display: flex; flex-direction: column; align-items: center;
                 position: relative; }
    .node-body { display: flex; flex-direction: column; align-items: center;
                 gap: 3px; position: relative; }
    .couple-row { display: flex; align-items: center; gap: 5px; }
    .cx { color: var(--color-gold, #c9a227); font-weight: 700; font-size: 1rem;
          padding: 0 2px; flex-shrink: 0; }
    .remarriage-lbl { font-size: 0.65rem; color: #999; font-style: italic;
                      text-align: center; margin-top: 5px; }
    /* Cards */
    .card { background: #fff; border: 2px solid var(--color-gold, #c9a227);
            border-radius: 6px; padding: 7px 10px; width: 148px;
            text-align: center; font-size: 0.74rem; line-height: 1.35;
            position: relative; }
    .card .n { font-weight: 700; color: var(--color-navy, #0a1628);
               display: block; font-size: 0.78rem; }
    .card .d { color: #888; font-size: 0.67rem; display: block; margin-top: 2px; }
    .card.root { background: var(--color-navy, #0a1628);
                 border-color: var(--color-gold, #c9a227); }
    .card.root .n { color: var(--color-gold, #c9a227); }
    .card.root .d { color: #99aabb; }
    .card.spouse { background: #dce8ff; border-color: #6888cc; }
    .card.spouse .n { color: #1a3a80; }
    .card.priv  { background: #eee; border-color: #bbb; }
    .card.priv .n { color: #666; }
    .card.priv .d { color: #aaa; }
    .card.collapsible { cursor: pointer; }
    .card.collapsible::after { content: '\\25BE'; position: absolute;
      bottom: 3px; right: 5px; font-size: 0.6rem;
      color: var(--color-gold, #c9a227); }
    .tree-node.closed > .node-body .card.collapsible::after { content: '\\25B8'; }
    /* Connector lines (CSS pseudo-elements) */
    :root { --gap: 44px; }
    .tree-node.has-ch > .node-body::after {
      content: ''; position: absolute; left: 50%; transform: translateX(-50%);
      top: 100%; width: 2px; height: var(--gap);
      background: var(--color-gold, #c9a227); }
    .tree-children { display: flex; flex-direction: row; gap: 14px;
                     align-items: flex-start; justify-content: center;
                     margin-top: var(--gap); }
    .tree-node.closed > .node-body::after  { display: none !important; }
    .tree-node.closed > .tree-children     { display: none !important; }
    .tree-children > .tree-node { position: relative; }
    .tree-children > .tree-node::before {
      content: ''; position: absolute; left: 50%; transform: translateX(-50%);
      top: calc(-1 * var(--gap)); width: 2px; height: var(--gap);
      background: var(--color-gold, #c9a227); }
    .tree-children > .tree-node::after {
      content: ''; position: absolute; top: calc(-1 * var(--gap));
      left: 0; right: 0; height: 2px;
      background: var(--color-gold, #c9a227); }
    .tree-children > .tree-node:first-child::after  { left: 50%; }
    .tree-children > .tree-node:last-child::after   { right: 50%; }
    .tree-children > .tree-node:first-child:last-child::after { display: none; }"""

# The JavaScript renderer — reads from TREES / TREE_TITLES injected below
JS_RENDERER = """\
function makeCard(p, cls) {
  var div = document.createElement('div');
  div.className = 'card ' + (cls || '');
  var n = document.createElement('span'); n.className = 'n';
  n.textContent = p.name; div.appendChild(n);
  var parts = [];
  if (p.birth) parts.push('b. ' + p.birth);
  if (p.death) parts.push('d. ' + p.death);
  if (p.priv && !p.birth && !p.death) parts.push('Living');
  if (parts.length) {
    var d = document.createElement('span'); d.className = 'd';
    d.textContent = parts.join('  \u00B7  '); div.appendChild(d);
  }
  return div;
}

function renderNode(p, gen) {
  var wrapper = document.createElement('div'); wrapper.className = 'tree-node';
  var body = document.createElement('div'); body.className = 'node-body';
  var marriages = p.m || [];
  var allKids = [];
  for (var i = 0; i < marriages.length; i++) {
    var ks = marriages[i].kids || [];
    for (var j = 0; j < ks.length; j++) allKids.push(ks[j]);
  }
  var cls = gen === 0 ? 'root' : (p.priv ? 'priv' : '');
  if (allKids.length) cls += (cls ? ' ' : '') + 'collapsible';
  var mc = makeCard(p, cls);
  if (marriages.length > 0) {
    var row = document.createElement('div'); row.className = 'couple-row';
    row.appendChild(mc);
    if (marriages[0].sp) {
      var dot = document.createElement('span'); dot.className = 'cx';
      dot.textContent = '\u00D7'; row.appendChild(dot);
      var spCls = 'spouse' + (marriages[0].sp.priv ? ' priv' : '');
      row.appendChild(makeCard(marriages[0].sp, spCls));
    }
    body.appendChild(row);
    for (var mi = 1; mi < marriages.length; mi++) {
      var mg = marriages[mi];
      if (mg.label) {
        var lbl = document.createElement('div'); lbl.className = 'remarriage-lbl';
        lbl.textContent = mg.label + ':'; body.appendChild(lbl);
      }
      if (mg.sp) {
        var r2 = document.createElement('div'); r2.className = 'couple-row';
        var ph = document.createElement('div'); ph.style.cssText = 'width:148px;flex-shrink:0;';
        r2.appendChild(ph);
        var d2 = document.createElement('span'); d2.className = 'cx';
        d2.textContent = '\u00D7'; r2.appendChild(d2);
        var sp2Cls = 'spouse' + (mg.sp.priv ? ' priv' : '');
        r2.appendChild(makeCard(mg.sp, sp2Cls)); body.appendChild(r2);
      }
    }
  } else {
    var soloRow = document.createElement('div'); soloRow.className = 'couple-row';
    soloRow.appendChild(mc); body.appendChild(soloRow);
  }
  wrapper.appendChild(body);
  if (allKids.length) {
    wrapper.classList.add('has-ch');
    var cr = document.createElement('div'); cr.className = 'tree-children';
    for (var ki = 0; ki < allKids.length; ki++) cr.appendChild(renderNode(allKids[ki], gen + 1));
    wrapper.appendChild(cr);
    mc.addEventListener('click', (function(nd) {
      return function(e) { e.stopPropagation(); nd.classList.toggle('closed'); };
    }(wrapper)));
  }
  return wrapper;
}

function buildSection(title, data, showTitle) {
  var sec = document.createElement('div'); sec.className = 'tree-section';
  if (showTitle) {
    var h = document.createElement('h2'); h.className = 'tree-section-heading';
    h.textContent = title; sec.appendChild(h);
  }
  var root = document.createElement('div'); root.className = 'tree-root';
  root.appendChild(renderNode(data, 0)); sec.appendChild(root);
  return sec;
}

var forest = document.getElementById('forest');
var multiTree = TREES.length > 1;
for (var ti = 0; ti < TREES.length; ti++) {
  forest.appendChild(buildSection(TREE_TITLES[ti], TREES[ti], multiTree));
}"""


def build_page(title, trees, tree_titles):
    """Generate a complete interactive HTML family tree page."""
    has_trees = bool(trees)
    trees_json = json.dumps(trees, ensure_ascii=False, separators=(',', ':'))
    titles_json = json.dumps(tree_titles, ensure_ascii=False, separators=(',', ':'))

    if not has_trees:
        forest_content = (
            '<p style="color:#666;font-style:italic;padding:2rem 0;">'
            'No genealogy content could be recovered from this page.</p>'
        )
        script_block = ''
    else:
        forest_content = ''
        script_block = (
            '<script>\n'
            'var TREES = ' + trees_json + ';\n'
            'var TREE_TITLES = ' + titles_json + ';\n'
            + JS_RENDERER + '\n'
            '</script>\n'
        )

    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '  <title>' + escape_html(title) + ' \u2014 Tenedian Brotherhood</title>\n'
        '  <link rel="stylesheet" href="css/style.css">\n'
        '  <style>\n' + TREE_CSS + '\n  </style>\n'
        '</head>\n'
        '<body>\n\n'
        + NAV_HTML + '\n\n'
        '<main>\n'
        '  <header class="page-header">\n'
        '    <div class="page-header-inner">\n'
        '      <h1 class="page-title">' + escape_html(title) + '</h1>\n'
        '      <p class="page-subtitle">'
        '<a href="family-trees.html" style="color:rgba(255,255,255,.65);font-size:.85rem;">'
        '&larr; Back to Family Trees</a></p>\n'
        '    </div>\n'
        '  </header>\n\n'
        '  <div class="page-content tree-page">\n'
        '    <div class="tree-outer">\n'
        '      <div class="tree-legend">\n'
        '        <div class="legend-item"><div class="ls navy"></div> Ancestor</div>\n'
        '        <div class="legend-item"><div class="ls white"></div> Descendant</div>\n'
        '        <div class="legend-item"><div class="ls blue"></div> Spouse (married-in)</div>\n'
        '        <div class="legend-item"><div class="ls gray"></div> Living (private)</div>\n'
        '        <div class="legend-item" style="color:var(--color-gold,#c9a227);'
        'font-weight:700;font-size:1rem">&times;</div>&thinsp;Married\n'
        '        <div class="legend-item" style="font-size:.75rem;color:#999">'
        'Click a descendant card to collapse/expand</div>\n'
        '      </div>\n'
        '      <div class="tree-forest" id="forest">' + forest_content + '</div>\n'
        '    </div>\n'
        '  </div>\n'
        '</main>\n\n'
        + FOOTER_HTML + '\n\n'
        + script_block
        + '</body>\n</html>\n'
    )


# ── Main converter ─────────────────────────────────────────────────────────────
HEADING_RE = re.compile(
    r'^(?:descendants?\s+of\s+|family\s+of\s+|the\s+)?(.+?)\s*(?:family\s*tree|family)?$',
    re.IGNORECASE,
)


def convert_file(src_path, output_dir, verbose=False):
    name_lower = src_path.name.lower()

    # Skip .htm if .html counterpart exists
    if src_path.suffix.lower() == '.htm':
        if src_path.with_suffix('.html').exists():
            return None

    if name_lower in SKIP_PAGES:
        return None

    try:
        html = src_path.read_text(encoding='windows-1252', errors='replace')
    except Exception as e:
        print(f'  ERROR reading {src_path.name}: {e}', file=sys.stderr)
        return None

    html = strip_wayback(html)

    parser = TextExtractor()
    try:
        parser.feed(html)
    except Exception as e:
        if verbose:
            print(f'  WARN parsing {src_path.name}: {e}', file=sys.stderr)

    raw_lines = parser.get_lines()
    page_title = parser.title.strip() or src_path.stem

    # Clean up title → "X Family"
    family_name = page_title
    m = HEADING_RE.match(page_title)
    if m:
        family_name = m.group(1).strip()
        if not re.search(r'\bfamily\b', family_name, re.IGNORECASE):
            family_name += ' Family'

    # Parse and build tree
    entries = parse_genealogy_lines(raw_lines)
    roots = build_trees(entries)

    # Derive per-tree section titles
    if len(roots) == 1:
        tree_titles = [family_name]
    else:
        tree_titles = ['Descendants of ' + r['name'] for r in roots]

    if verbose:
        status = f'{sum(1 for e in entries if not e.get("is_spouse", False))} persons' if entries else 'EMPTY'
        multi = f' ({len(roots)} trees)' if len(roots) > 1 else ''
        print(f'  {src_path.name} → {status}{multi}')

    slug = slugify(family_name.replace(' Family', '').strip())
    out_name = slug + '.html'
    out_path = output_dir / out_name

    page_html = build_page(family_name, roots, tree_titles)
    out_path.write_text(page_html, encoding='utf-8')

    return slug, family_name, out_name


def main():
    ap = argparse.ArgumentParser(description='Convert Tenedian family tree pages to interactive HTML5.')
    ap.add_argument('--source', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    source_dir = Path(args.source).expanduser()
    output_dir = Path(args.output).expanduser()

    if not source_dir.is_dir():
        print(f'Error: source directory not found: {source_dir}', file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(
        list(source_dir.glob('*.html')) + list(source_dir.glob('*.htm')),
        key=lambda p: p.name.lower()
    )

    print(f'Found {len(html_files)} HTML/HTM files in {source_dir}')
    print(f'Output → {output_dir}')
    print()

    results, empty, skipped = [], [], 0

    for src in html_files:
        result = convert_file(src, output_dir, verbose=args.verbose)
        if result is None:
            skipped += 1
            continue
        slug, family_name, out_name = result
        results.append((family_name, slug, out_name))
        content = (output_dir / out_name).read_text(encoding='utf-8')
        if 'No genealogy content' in content:
            empty.append(out_name)

    results.sort(key=lambda x: x[0].lower())
    print(f'\nConverted: {len(results)} family trees  |  Skipped: {skipped}')
    if empty:
        print(f'\nEMPTY ({len(empty)}):')
        for e in empty:
            print(f'  {e}')

    # Print sorted index HTML
    print('\n' + '=' * 60)
    print('SORTED INDEX (paste into family-trees.html):')
    print('=' * 60 + '\n')

    by_letter = {}
    for fam, _, out in results:
        by_letter.setdefault(fam[0].upper(), []).append((fam, out))

    letters = sorted(by_letter.keys())
    print('<div class="letter-nav">')
    for l in letters:
        print(f'  <a href="#{l}">{l}</a>')
    print('</div>\n')
    for l in letters:
        print(f'<div class="letter-section" id="{l}">')
        print(f'  <div class="letter-heading">{l}</div>')
        print('  <div class="family-grid">')
        for fam, out in by_letter[l]:
            print(f'    <a href="{out}" class="family-card">{escape_html(fam)}</a>')
        print('  </div>\n</div>\n')


if __name__ == '__main__':
    main()
