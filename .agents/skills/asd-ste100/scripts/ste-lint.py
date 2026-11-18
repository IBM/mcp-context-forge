#!/usr/bin/env python3
"""Deterministic linter for the structural STE rules in SKILL.md.

Checks only rules verifiable without ASD's dictionary. Deliberately never
flags hedges or modality (may/might/could): the skill treats confidence as
content, and a linter that pressures hedges out would rewrite claims.

Usage:
    ste-lint.py FILE [FILE ...]
    echo "text" | ste-lint.py [--json]
    ste-lint.py --baseline 5 FILE      # pass unless hard violations exceed 5
    ste-lint.py --disable passive-voice,present-perfect FILE
    ste-lint.py --selftest

Exit 1 when hard ("advisory-free") violations exceed the baseline (default 0).
Advisory findings (passive voice, compound tenses) never fail the run.
Exit 2 on a usage error (unknown flag, bad value, unknown rule, unreadable file).
"""
import argparse
import bisect
import contextlib
import html.entities
import io
import json
import os
import re
import sys
import tempfile
import unicodedata

# ponytail: regex heuristics, not a parser. No noun-cluster rule — needs POS
# tagging to avoid constant false positives; add spaCy-backed rule if ever needed.
# No ellipsis rule by owner's choice: technical writing sometimes earns one.
# Irregular past participles used by the present-perfect heuristic.
IRREGULAR_PARTICIPLES = "given|taken|made|done|found|seen|known|shown|written|built|sent|set|run|read|kept|held|left|put|cut|hit|let|shut|split|spread|begun|become|come|gone|got|gotten|lost|met|paid|said|sold|told|thought|brought|bought|caught|taught|won|worn|torn|born|drawn|grown|thrown|flown|driven|risen|chosen|broken|spoken|frozen|hidden|ridden|forgotten|fallen|eaten|beaten|understood|stood|struck|stuck|swung|hung|led|fed|bled|fled|sped|bound|wound|dug|spun|slid|bit|lit|quit"

# Preserve the original passive heuristic; perfects also include intransitive verbs.
PASSIVE_PARTICIPLES = "given|taken|made|done|found|seen|known|shown|written|built|sent|set|run|read|kept|held|left|put"
# Up to two words may stand between the modal and "have": "may not",
# "might already", "could not possibly", "may very well".
MODAL_PERFECT_PREFIX = re.compile(
    r"\b(?:(?:may|might|could|should|would|must|can|will|shall)(?:n['’]t)?"
    r"|cannot|can['’]t|won['’]t|shan['’]t)"
    r"(?:\s+(?:not|already|also|ever|even|just|never|still|very|well|\w+ly)){0,2}\s+$",
    re.I,
)

RULES = [
    ("semicolon", "advisory-free",
     re.compile(r";"),
     "STE bans the semicolon (Rule 8.1). Split into separate sentences."),
    ("phrasal-verb", "advisory-free",
     re.compile(r"\b(spin(?:ning|s)? up|spun up|reach(?:ing|es|ed)? out|div(?:e|es|ing|ed) into|dove into|kick(?:ing|s|ed)? off|circl(?:e|es|ing|ed) back|touch(?:ing|es|ed)? base)\b", re.I),
     "Soft phrasal verb. Use the single plain verb (start, contact, read, begin)."),
    ("marketing-adjective", "advisory-free",
     re.compile(r"\b(seamless(?:ly)?|robust(?:ly)?|cutting-edge|effortless(?:ly)?|blazing[- ]fast|world-class|state-of-the-art|game-chang(?:ing|er))\b", re.I),
     "Marketing adjective. Delete, or replace with the measurement that earns the claim."),
    ("nominalization", "advisory-free",
     re.compile(r"\b(perform|performs|performed|conduct|conducts|conducted|carry out|carries out|carried out)\s+(?:a|an|the)\s+\w+(?:tion|sion|ment|ance|ence|ysis)\b", re.I),
     "Action frozen into a noun. Use the verb (analyze, not perform an analysis of)."),
    ("passive-voice", "advisory",
     re.compile(r"\b(is|are|was|were|been|being)\s+(\w+ed|" + PASSIVE_PARTICIPLES + r")\b(?!\s+(?:to|for|by)\s+\w+ing)", re.I),
     "Possible passive voice. Name the actor and use an active verb, unless the actor is unknown or irrelevant."),
    ("present-perfect", "advisory",
     # modal + perfect infinitive ("may have failed") is a protected hedge, not present perfect
     re.compile(r"(?<!\bmay )(?<!\bmight )(?<!\bcould )(?<!\bshould )(?<!\bwould )(?<!\bmust )\b(has|have|had)\s+(?:been\s+)?(?:\w+(?:ed|en)|" + IRREGULAR_PARTICIPLES + r")\b", re.I),
     "Compound tense. Use simple past/present unless current relevance is the point (then keep and flag)."),
]

# One word, one meaning: groups of verbs commonly rotated for the same action.
# Only pairs where the members are genuinely interchangeable — error/fault/failure
# are distinct concepts and stay out.
SYNONYM_GROUPS = [
    ("check", "verify", "confirm", "validate"),
    ("delete", "remove", "erase"),
    ("start", "launch", "begin", "initiate"),
    ("stop", "halt", "terminate"),
    ("show", "display"),
    ("use", "utilize", "employ"),
    ("fix", "repair", "correct"),
    ("send", "transmit"),
    ("get", "retrieve", "fetch", "obtain"),
    ("change", "modify", "alter"),
]

MAX_WORDS = 25  # descriptions cap; instructions cap is 20 but undetectable without context

CODE_FENCE = re.compile(r"^(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`]*`")
BACKTICK_RUN = re.compile(r"`+")
# A list item start at any indent, to find the content indent of its item.
LIST_ITEM_INDENT = re.compile(r"^( *)([-*+]|[0-9]{1,9}[.)])( +|$)")
# Markup that is not prose: character references (&nbsp; &#39; &#x2192;) and
# autolinks (<https://...>). Inline link destinations ("](url") are found by
# _link_destination_end. A reference is markup only when GitHub reads it as one.
CHAR_REF = re.compile(r"&(?:([A-Za-z][A-Za-z0-9]{1,31})|#([0-9]{1,7})|#[xX]([0-9A-Fa-f]{1,6}));")
LINK_OPEN = re.compile(r"\]\(")
BRACKET = re.compile(r"[\[\]]")
# A list item or a fence that can interrupt a paragraph: a bullet or "1." with text.
PARAGRAPH_INTERRUPT = re.compile(r" {0,3}(?:[-+*][ \t]+\S|1[.)][ \t]+\S|`{3,}|~{3,})")
AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*>")
EMAIL_AUTOLINK = re.compile(r"<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>")
# A GFM extended autolink (www.example.com, https://example.com) ends before
# white space or "<".
GFM_LINK_STOP = re.compile(r"[ \t\r\n<]")
# An inline HTML open or closing tag on one line (CommonMark 6.6).
INLINE_TAG = re.compile(
    r"<(?:(?P<name>[A-Za-z][A-Za-z0-9-]*)(?:[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:[ \t]*=[ \t]*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*[ \t]*/?"
    r"|/[A-Za-z][A-Za-z0-9-]*[ \t]*)>"
)
# Other inline HTML (CommonMark 6.6): a comment, a processing instruction, a
# declaration, a CDATA section. Each pair is (opener, closer).
INLINE_HTML_OTHER = ((re.compile(r"<!--"), "-->"), (re.compile(r"<\?"), "?>"),
                     (re.compile(r"<![A-Za-z]"), ">"), (re.compile(r"<!\[CDATA\["), "]]>"))
# The start of an open tag that goes on after the end of its line: GitHub lets
# the white space between the parts of a tag hold a line break. A closing tag
# holds no "*" or "_", so where it ends does not change the emphasis.
WRAPPED_TAG = re.compile(
    r"<[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:[ \t]*=[ \t]*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*"
    r"(?:[ \t]+(?:[A-Za-z_:][A-Za-z0-9_.:-]*[ \t]*(?:=[ \t]*(?:[^\s\"'=<>`]+|'[^']*|\"[^\"]*)?)?)?)?$"
)
HTML_ITEM_START = re.compile(r"<[A-Za-z!?]")
# GitHub shows these tags as text (GFM 6.11, the tagfilter extension).
FILTERED_TAGS = {"title", "textarea", "style", "xmp", "iframe", "noembed", "noframes", "script", "plaintext"}
ATTRIBUTE_VALUE = re.compile(r"=[ \t]*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)")
# CommonMark 6.3 lets an implementation limit the nesting of parentheses in a
# link destination. The limit keeps the scan of a long line linear.
MAX_LINK_PARENS = 32
ASCII_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
# The white space next to an emphasis run, as GitHub's parser (cmark-gfm) reads it.
UNICODE_SPACE = frozenset("\t\n\f\r \xa0           "
                          "   　")
LIST_ITEM_START = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>[-*+]|[0-9]+[.)])(?P<gap> +)(?P<body>.*)$"
)
CONJUNCTION_END = re.compile(r"\b(?:and|or)\s*$", re.I)
TABLE_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
# Headings, thematic breaks, front-matter delimiters, and HTML lines stand alone.
STANDALONE_LINE = re.compile(r"^ {0,3}(?:#|<|(?:[-*_=] *){3,}$)")
BLOCKQUOTE_PREFIX = re.compile(r"^ {0,3}(?:> ?)+")
# A GitHub alert marker, alone on the first line of a quote: "> [!NOTE]".
GITHUB_ALERT = re.compile(r"\[!(?:note|tip|important|warning|caution)\]", re.I)
# MkDocs admonition title lines. Four spaces allow a title inside a list item.
# Only ??? admonitions support the collapsible "+" marker.
ADMONITION_TITLE = re.compile(
    r'^ {0,4}(?:!!!|\?\?\?\+?)[ \t]*[\w-]+'
    r'(?:[ \t]+[\w-]+)*(?:[ \t]+".*")?[ \t]*$'
)
# Track ordinary block containers, not inline or void tags such as span or hr.
HTML_BLOCK_TAG = re.compile(
    r"<(/?)(address|article|aside|blockquote|body|caption|center|dd|details|"
    r"dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|"
    r"header|hgroup|html|iframe|legend|li|main|menu|nav|noframes|ol|"
    r"optgroup|option|p|pre|script|search|section|style|summary|table|"
    r"tbody|td|textarea|tfoot|th|thead|title|tr|ul)(?=[\s/>])[^>]*>", re.I,
)
# The indent and the list markers before the text of a line, after its quote prefix.
ITEM_PREFIX = re.compile(r"[ \t]*(?:(?:[-*+]|[0-9]{1,9}[.)])[ \t]+)*")
# Any list marker at any depth starts a new prose block.
ANY_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|[0-9]+[.)])(?:\s|$)")
# A letter or a digit: a token without one is punctuation, not a word.
WORD_CHAR = re.compile(r"[^\W_]")
# A token that ends in terminal punctuation, optionally followed by closing
# quotes, brackets, or Markdown emphasis markers ("**Lead.**").
SENTENCE_END = re.compile(r"[.!?][\"'”’)\]*_]*$")
# A run of emphasis markers (CommonMark 6.2). A "*" or "_" after the stop ends
# a sentence only when emphasis uses it: "**Lead.**" does, "file.*" does not.
DELIMITER_RUN = re.compile(r"\*+|_+")
# The runs that _emphasis_runs reads: emphasis runs and the strikethrough runs
# of GFM. GitHub's parser reads at most 100 "~" as one run.
EMPHASIS_RUN = re.compile(r"\*+|_+|~{1,100}")
OPENERS = "\"'“‘([*_"
# Abbreviations whose period never ends a sentence.
ABBREVIATIONS = {"vs.", "cf.", "approx.", "mr.", "mrs.", "ms.", "dr.", "fig.", "no."}
# Dotted initialisms such as "e.g." and "U.S." end a sentence only when the
# next word starts with a capital letter.
DOTTED_ABBREVIATION = re.compile(r"(?:[a-z]\.){2,}", re.I)


def _word_re(base):
    return re.compile(r"\b" + base + r"(?:s|es|ed|d|ing)?\b", re.I)


def _count_words(text):
    """Count whitespace-separated tokens that contain a letter or a digit.

    Bare punctuation is not a word: a comma left behind by a masked code
    span, or a spaced em dash, does not make a sentence longer.
    """
    return sum(1 for token in text.split() if WORD_CHAR.search(token))


def _mask_inline_code(text):
    """Blank code spans with equal-length spaces so columns stay true."""
    return INLINE_CODE.sub(lambda match: " " * len(match.group(0)), text)


def _list_item(rest, list_indent, in_paragraph):
    """Return the match of the list item that starts REST, or None (CommonMark 5.2).

    REST is a line after its quote prefix. A thematic break such as "* * *" is no
    item. IN_PARAGRAPH: the line would otherwise continue a paragraph in the same
    quote. Then an item to the left of LIST_INDENT is the next item of the open
    list, and a new list starts only with a bullet or "1" and some text, and not
    as indented code.
    """
    if NO_PARAGRAPH.match(rest):
        return None
    item = LIST_ITEM_INDENT.match(rest)
    if not item or not in_paragraph or len(item.group(1)) < list_indent:
        return item
    marker = item.group(2)
    if (len(item.group(1)) < list_indent + 4 and rest[item.end():].strip()
            and (marker in "-*+" or int(marker[:-1]) == 1)):
        return item
    return None


def _breaks_paragraph(depth, line, list_indent):
    """True when LINE ends a paragraph at quote DEPTH, as the main loop ends it.

    These lines end it (CommonMark 4-5): a blank or quote-only line, a deeper quote,
    a heading, a thematic break, a setext underline in the open item, a fence that is
    no indented code, an HTML block of types 1 to 6, and a list item that can
    interrupt a paragraph. A text line with fewer ">" is a lazy line and continues
    the paragraph, but any list item there ends it. A code span ends there too.
    """
    line_depth, rest = _strip_quotes(line.expandtabs(4))
    in_item = _indent_width(rest) >= list_indent
    return (not rest.strip() or line_depth > depth
            or bool(NO_PARAGRAPH.match(rest)
                    or (_fence_step(None, line)[0] and _indent_width(rest) < list_indent + 4)
                    or (line_depth == depth and in_item and SETEXT_UNDERLINE.match(rest))
                    or any(start.match(rest) for start, _ in HTML_BLOCK_KINDS)
                    or _list_item(rest, list_indent, line_depth == depth)))


def _paragraph_runs(lines, start, depth, list_indent):
    """Return (end, last) for the paragraph that continues at LINES[START].

    END is the index of the line that ends it. LAST maps each backtick run length
    to the index of its last line before END. One scan serves every run in the
    paragraph, so the cost stays linear in the line count.
    """
    last, end = {}, start
    while end < len(lines) and not _breaks_paragraph(depth, lines[end], list_indent):
        for run in BACKTICK_RUN.finditer(lines[end]):
            last[len(run.group())] = end
        end += 1
    return end, last


def _mask_code_spans(line, open_run, closes_later, lines=(), next_index=0, depth=0, skip=0, carry=None,
                     brackets=None, hidden=None):
    """Blank the code spans in LINE, also a span that wraps across lines.

    OPEN_RUN is the backtick run length of a span still open from an earlier
    line, or 0. LINES[NEXT_INDEX:] are the lines after LINE. As in CommonMark 6.1, a
    span ends at the next run of the same length, and a run that no later run
    in the paragraph closes is literal text. Outside code spans, fill inline
    link destinations with underscores, blank link titles, and fill the
    inline HTML that GitHub does not show. What starts first wins: a code
    span that opens before "](" hides the link, and a backtick in a link, an
    autolink or inline HTML is text.
    DEPTH is the quote depth of the paragraph that LINE is in, or None when no
    paragraph goes on after LINE, so a link must close in it. SKIP is where a
    link from an earlier line ends in LINE. When a link goes on in a later
    line, CARRY gets [lines ahead, column after its ")"]. BRACKETS carries the
    open "[" marks from line to line of a paragraph. HIDDEN, when it is a list,
    gets the (start, end) of each underscore fill and of each autolink and
    inline HTML item, all of it: GitHub reads no emphasis run in one, also
    where it shows a part (a tag name, an attribute name). Return (masked line, open
    run).
    """
    masked = list(line)
    start = 0 if open_run else None
    runs = list(BACKTICK_RUN.finditer(line))
    last = {len(run.group()): i for i, run in enumerate(runs)}  # last run of each length
    opens = [m.end() for m in LINK_OPEN.finditer(line) if not _escaped(line, m.start())]
    # Autolinks and inline HTML tags: a code span or a link in one is text.
    # An item is (start, end, the parts of it that GitHub does not show).
    atoms = [(m.start(), m.end(), ()) for m in AUTOLINK.finditer(line)]
    for m in INLINE_TAG.finditer(line):
        # GitHub shows no attribute value. A bare word stays, as in the
        # placeholder "<one of the two>".
        hide = ()
        if m.group("name") and m.group("name").lower() not in FILTERED_TAGS:
            hide = [value.span() for value in ATTRIBUTE_VALUE.finditer(line, m.end("name"), m.end())]
        atoms.append((m.start(), m.end(), hide))
    atoms += _inline_html_other(line)
    atoms.sort(key=lambda atom: atom[:2])
    atoms = [atom for atom in atoms if not _escaped(line, atom[0])]
    marks = [m.start() for m in BRACKET.finditer(line) if not _escaped(line, m.start())]
    if brackets is None:
        brackets = [[], 0]
    # BRACKETS[0] holds the "[" marks of the paragraph that no "]" closed yet,
    # True for an image "![". A "[" below BRACKETS[1] is in a link, so it
    # opens no link (CommonMark 6.3); an image "![" can still open an image.
    stack = brackets[0]
    a = 0
    b = 0
    k = 0
    done = skip  # the end of the last code span or link
    _blank_title(masked, line, 0, skip)  # a link title from an earlier line

    def pop_bracket():
        image = stack.pop()
        active = image or len(stack) >= brackets[1]
        brackets[1] = min(brackets[1], len(stack))
        return image, active

    def take_brackets(limit):
        # Read the "[" and "]" marks before LIMIT, outside code, links and tags.
        nonlocal b
        while b < len(marks) and marks[b] < limit:
            pos = marks[b]
            b += 1
            if pos < done:
                continue
            if line[pos] == "[":
                stack.append(pos > 0 and line[pos - 1] == "!" and not _escaped(line, pos - 1))
            elif line[pos + 1:pos + 2] != "(" and stack:
                pop_bracket()  # mask_links reads a "](" mark

    def take_atoms(limit):
        # Let the autolinks and tags that start before LIMIT start first.
        nonlocal a, done
        while a < len(atoms) and atoms[a][0] < limit:
            begin, end, hide = atoms[a]
            a += 1
            if begin < done:
                continue
            take_brackets(begin)
            done = end
            if hidden is not None:
                hidden.append((begin, end))
            # Keep the spaces, so the token count stays.
            for left, right in hide:
                masked[left:right] = [c if c.isspace() else "_" for c in line[left:right]]

    def mask_links(limit):
        # Fill the destinations after the "](" marks before LIMIT.
        nonlocal k, done
        while k < len(opens) and opens[k] <= limit:
            pos = opens[k]
            k += 1
            take_atoms(pos - 2)
            take_brackets(pos - 2)
            if pos - 2 < done or not stack:
                continue  # no "[" opens link text, so "](" is text
            image, active = pop_bracket()
            if not active:
                continue
            later = (lines[index] for index in range(next_index, len(lines)))
            link = _link_destination_end(line, pos, later, depth)
            if link is None or (link[0] == pos and line[pos:link[1]].strip() != ")"):
                continue  # with no destination, a "title" is the destination: a gap this reads as no link
            if not image:
                brackets[1] = len(stack)  # a link holds no link
            masked[pos:link[0]] = "_" * (link[0] - pos)
            if hidden is not None:
                hidden.append((pos, link[0]))
            _blank_title(masked, line, link[0], link[1])
            done = link[1]
            if carry is not None and link[2]:
                carry[:] = link[2]

    for i, run in enumerate(runs):
        n = len(run.group())
        if start is not None:
            if n == open_run:
                masked[start:run.end()] = " " * (run.end() - start)
                start, open_run = None, 0
                done = run.end()
            continue
        mask_links(run.start())
        take_atoms(run.start())
        if run.start() < done:
            continue  # a backtick in a link, an autolink or a tag is text
        first = run.start()
        if _escaped(line, first):
            first, n = first + 1, n - 1  # an escaped backtick is text
        if n and (last.get(n, -1) > i or closes_later(n)):
            take_brackets(first)
            start, open_run = first, n
    if start is not None:
        masked[start:] = " " * (len(line) - start)
    else:
        mask_links(len(line))
        take_atoms(len(line))
        take_brackets(len(line))  # a "[" that a later line can close
    return "".join(masked), open_run


def _inline_html_other(line):
    """Return (start, end, hidden parts) for each comment, processing
    instruction, declaration and CDATA section that starts and ends in LINE.

    GitHub shows none of a comment or a declaration. Its HTML sanitizer reads
    a processing instruction and CDATA as a comment that ends at the first ">",
    so it shows the text after that ">".
    """
    found = []
    for opener, closer in INLINE_HTML_OTHER:
        for m in opener.finditer(line):
            if closer == "-->" and line.startswith(("<!-->", "<!--->"), m.start()):
                end = line.index(">", m.end()) + 1
                found.append((m.start(), end, [(m.start(), end)]))
                continue
            end = line.find(closer, m.end())
            if end < 0:
                break  # no later opener closes either
            end += len(closer)
            shown = end if closer in ("-->", ">") else line.index(">", m.start()) + 1
            found.append((m.start(), end, [(m.start(), shown)]))
    return found


def _html_item_wraps(source, masked, hidden, start):
    """True when an inline HTML item can start in SOURCE and end on a later line.

    MASKED is SOURCE masked, at the same length. HIDDEN holds the (start, end)
    of the items that end in SOURCE. An open tag can go on after the end of
    the line, also a comment, a processing instruction, a declaration or a
    CDATA section without its closer in SOURCE. A "<" in a code span, in a hidden
    range, after a backslash or before START starts no item.
    """
    items = sorted(hidden)
    item = 0
    last = {closer: source.rfind(closer) for _, closer in INLINE_HTML_OTHER}
    for m in HTML_ITEM_START.finditer(source, start):
        pos = m.start()
        while item < len(items) and items[item][1] <= pos:
            item += 1
        if (item < len(items) and items[item][0] <= pos) or masked[pos] != "<" or _escaped(source, pos):
            continue
        if WRAPPED_TAG.match(source, pos):
            return True
        for opener, closer in INLINE_HTML_OTHER:
            other = opener.match(source, pos)
            if other and last[closer] < other.end():
                return True
    return False


def _escaped(line, pos):
    """True when an odd number of backslashes comes right before LINE[POS]."""
    start = pos
    while start and line[start - 1] == "\\":
        start -= 1
    return (pos - start) % 2 == 1


def _blank_title(masked, line, start, end):
    """Blank the link title in MASKED[START:END] with spaces, but keep its ")".

    GitHub shows a title in no text, so it is not prose. The ")" stays, so the
    link stays one token for the word count, as it is when it has no title.
    """
    if start < end:
        masked[start:end] = " " * (end - start)
        if line[end - 1] == ")":
            masked[end - 1] = ")"


def _char_ref_is_markup(match):
    """True when the character reference MATCH renders as one character.

    A named reference counts only when its name is in the HTML5 list. A
    reference that renders as a semicolon is prose: GitHub shows a semicolon.
    """
    name, decimal, hexadecimal = match.groups()
    if name is not None:
        return name + ";" in html.entities.html5 and name != "semi"
    value = int(decimal) if decimal is not None else int(hexadecimal, 16)
    return value != ord(";")


def _paragraph_lines(later_lines, depth):
    """Yield (text, column, lines ahead) for the lines that continue the paragraph.

    TEXT is the line without its quote prefix, which ends at COLUMN.

    DEPTH is the quote depth of the paragraph, or None when no paragraph goes
    on. A blank line, a deeper quote and a line that starts a block end the
    paragraph (CommonMark 4.1 to 4.6, 5.1 and 5.2). A line with fewer ">" is a
    lazy line and continues it.
    """
    if depth is None:
        return
    for ahead, line in enumerate(later_lines, 1):
        levels, rest = _strip_quotes(line)
        if (levels > depth or not rest.strip() or NO_PARAGRAPH.match(rest)
                or SETEXT_UNDERLINE.match(rest) or PARAGRAPH_INTERRUPT.match(rest)
                or any(start.match(rest) for start, _ in HTML_BLOCK_KINDS)):
            return
        yield rest, len(line) - len(rest), ahead


def _skip_link_gap(item, pos, rest):
    """Skip spaces and tabs from POS, with at most one line ending.

    ITEM is (text, column, lines ahead), and REST yields the next items of the
    paragraph. Return (item, pos, crossed), or None when the paragraph ends.
    """
    while pos < len(item[0]) and item[0][pos] in " \t":
        pos += 1
    if pos < len(item[0]):
        return item, pos, False
    item = next(rest, None)
    if item is None:
        return None
    pos = 0
    while pos < len(item[0]) and item[0][pos] in " \t":
        pos += 1
    return item, pos, True


def _skip_link_title(item, pos, rest):
    """Return (item, pos) after a link title that starts at POS, or None.

    ITEM is (text, column, lines ahead). The title can go on in the next lines
    of the paragraph (REST), but it must close before the paragraph ends.
    """
    line = item[0]
    closer = {'"': '"', "'": "'", "(": ")"}[line[pos]]
    pos += 1
    while True:
        while pos < len(line):
            if line[pos] == "\\" and pos + 1 < len(line) and line[pos + 1] in ASCII_PUNCTUATION:
                pos += 2
                continue
            if line[pos] == closer:
                return item, pos + 1
            if closer == ")" and line[pos] == "(":
                return None
            pos += 1
        item, pos = next(rest, None), 0
        if item is None:
            return None
        line = item[0]


def _link_destination_end(text, start, later_lines=(), depth=None):
    """Return (destination end, link end, carry) for the destination at START, or None.

    START is after "](". CommonMark 6.3: the destination is in <...>, or it has
    no space or control character and its parentheses are balanced. An
    optional title and ")" must follow, in the same paragraph. LATER_LINES are
    the lines after TEXT, and DEPTH is the quote depth of the paragraph (see
    _paragraph_lines). Each gap of spaces and tabs may hold one line ending,
    and the title may span lines. The link end is after ")" when the link
    closes in TEXT, else the end of TEXT, and CARRY is then (lines ahead,
    column after ")") of the line where it closes, else None.
    """
    pos = start
    if pos < len(text) and text[pos] == "<":
        pos += 1
        while pos < len(text) and text[pos] not in "<>":
            pos += 2 if text[pos] == "\\" and pos + 1 < len(text) else 1
        if pos >= len(text) or text[pos] != ">":
            return None
        end = pos + 1
    else:
        parens = 0
        while pos < len(text):
            char = text[pos]
            if char == "\\" and pos + 1 < len(text) and text[pos + 1] in ASCII_PUNCTUATION:
                pos += 2
                continue
            if char <= " " or char == "\x7f":
                break
            if char == "(":
                parens += 1
                if parens > MAX_LINK_PARENS:
                    return None
            elif char == ")":
                if parens == 0:
                    break
                parens -= 1
            pos += 1
        if parens:
            return None
        end = pos
    rest = _paragraph_lines(later_lines, depth)
    gap = _skip_link_gap((text, 0, 0), end, rest)
    if gap is None:
        return None
    item, pos, crossed = gap
    if (crossed or pos > end) and item[0][pos] in "\"'(":
        title = _skip_link_title(item, pos, rest)
        if title is None:
            return None
        gap = _skip_link_gap(*title, rest)
        if gap is None:
            return None
        item, pos, _ = gap
    if item[0][pos] != ")":
        return None
    if item[2] == 0:
        return end, pos + 1, None
    return end, len(text), (item[2], item[1] + pos + 1)


def _mask_non_prose(text, hidden=None):
    """Fill character references and autolinks.

    The fill is underscores, not spaces, so a token stays one token and word
    counts do not change. An underscore is not a word character for _count_words.
    Code spans and link destinations are blanked by _mask_code_spans. HIDDEN,
    when it is a list, gets the (start, end) of each fill.
    """
    out = []
    pos = done = 0
    while pos < len(text):
        end = None
        if text[pos] == "&":
            ref = CHAR_REF.match(text, pos)
            if ref and _char_ref_is_markup(ref):
                end = ref.end()
        if end is None and text[pos] == "<":
            link = AUTOLINK.match(text, pos)
            if link:
                end = link.end()
        if end is None:
            pos += 1
            continue
        out.append(text[done:pos])
        out.append("_" * (end - pos))
        if hidden is not None:
            hidden.append((pos, end))
        pos = done = end
    out.append(text[done:])
    return "".join(out)


def _gfm_autolinks(source, masked, start, depth, hidden):
    """Add the (start, end) of each autolink in SOURCE[START:] to HIDDEN, for the emphasis view.

    These are the links that _mask_non_prose leaves: an email autolink
    (<user@example.com>), and a GFM extended autolink (www.example.com,
    https://example.com). GitHub reads a "*" or "_" in a link as text. MASKED
    is SOURCE masked: a link starts only where the two agree, and not in a
    range that HIDDEN already holds, so not in code, a link destination, an
    autolink or inline HTML (all of it, also the text of a processing
    instruction after its first ">"). START is where the text of the line
    starts, after a quote or list marker. As on GitHub (cmark-gfm), no extended
    autolink starts after a "[" that no "]" closed yet. DEPTH is the number of
    such "[" marks before the line. Return the number after the line.
    """
    items = []  # the ranges in HIDDEN, merged
    for begin, end in sorted(hidden):
        if items and begin <= items[-1][1]:
            items[-1][1] = max(items[-1][1], end)
        else:
            items.append([begin, end])
    item = 0
    pos = start
    while pos < len(source):
        while item < len(items) and items[item][1] <= pos:
            item += 1
        if item < len(items) and items[item][0] <= pos:
            pos = items[item][1]
            continue
        char = masked[pos]
        if char != source[pos] or (char in "[]<" and _escaped(source, pos)):
            pos += 1
            continue
        link = None
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(depth - 1, 0)
        elif char == "<":
            email = EMAIL_AUTOLINK.match(source, pos)
            link = email and email.span()
        elif depth == 0 and char in "w:":
            link = _gfm_extended_autolink(source, pos, start)
        if link:
            hidden.append(link)
            pos = link[1]
        else:
            pos += 1
    return depth


def _gfm_extended_autolink(text, pos, start):
    """Return (start, end) of the GFM extended autolink at the "w" or ":" at TEXT[POS], or None.

    This follows www_match and url_match of GitHub's parser (cmark-gfm). A
    "www." link starts after white space, "*", "_", "~" or "(", or at START. A
    ":" ends the scheme http, https or ftp, which starts the link. The domain
    must pass _gfm_domain. The link ends before white space or "<", without
    its trailing punctuation (_gfm_link_end). An escaped ":" has a backslash
    before it, so no scheme.
    """
    if text[pos] == "w":
        if pos > start and text[pos - 1] not in "*_~( \t\r\n":
            return None
        if not text.startswith("www.", pos) or not _gfm_domain(text, pos):
            return None
        begin = pos
    else:
        begin = pos
        while begin > start and text[begin - 1].isascii() and text[begin - 1].isalpha():
            begin -= 1
        if (text[begin:pos].lower() not in ("http", "https", "ftp") or not text.startswith("://", pos)
                or pos + 3 >= len(text) or _flanking(text[pos + 3]) != "other"
                or not _gfm_domain(text, pos + 3)):
            return None
    stop = GFM_LINK_STOP.search(text, pos)
    end = _gfm_link_end(text, pos, stop.start() if stop else len(text))
    return (begin, end) if end > pos else None


def _gfm_domain(text, start):
    """True when GitHub reads the domain at TEXT[START:] as the domain of a link (cmark-gfm check_domain).

    The domain ends at the first character that is not a letter, a digit,
    "-", "_", "." or one after a backslash. An underscore in one of its last
    two parts makes it no domain, unless it has more than ten dots. (cmark-gfm
    also wants a dot in the domain of a "www." link: the dot of "www." counts,
    unless the paragraph ends there, and then the link holds no "*" or "_".)
    cmark-gfm reads the domain byte by byte, so it ends after the first
    character that is not ASCII.
    """
    dots = before_last = in_last = 0  # the dots, the underscores in the last two parts
    pos = start + 1 if text[start].isascii() else len(text)
    while pos < len(text):
        char = text[pos]
        if char == "\\" and pos + 1 < len(text):
            pos += 1
            char = text[pos]
        if char == "_":
            in_last += 1
        elif char == ".":
            before_last, in_last = in_last, 0
            dots += 1
        elif not char.isascii() or (char != "-" and _flanking(char) != "other"):
            break
        pos += 1
    return not (before_last or in_last) or dots > 10


def _gfm_link_end(text, start, end):
    """Return END without the trailing punctuation that GitHub leaves out of a link (cmark-gfm autolink_delim).

    TEXT[START:END] is the link from its "w" or ":". The punctuation is
    ? ! . , : * _ ~ ' ", a character reference such as "&amp;", and a ")" that
    has no "(" in the link.
    """
    opening, closing = text.count("(", start, end), text.count(")", start, end)
    while end > start:
        char = text[end - 1]
        if char == ")":
            if closing <= opening:
                break
            closing -= 1
        elif char == ";":
            ref = end - 2
            while ref > start and text[ref].isascii() and text[ref].isalpha():
                ref -= 1
            if ref < end - 2 and text[ref] == "&":
                end = ref
                continue
        elif char not in "?!.,:*_~'\"":
            break
        end -= 1
    return end


def _emphasis_view(source, masked, hidden):
    """Return SOURCE with each "*", "_" and "~" that the masking hid shown as "x".

    MASKED is SOURCE masked, at the same length. HIDDEN holds the (start, end)
    of each underscore fill, where a "_" stays the same, of each autolink and
    inline HTML item, and of each autolink that _gfm_autolinks finds. The
    emphasis runs are read in this view, as GitHub reads them: a code span next
    to "**" is a backtick there, and a "*" or "_" in a code span, a link
    destination, an autolink or inline HTML is no run.
    """
    view = ["x" if original in "*_~" and char != original else original
            for char, original in zip(masked, source)]
    for start, end in hidden:
        for index in range(start, end):
            if view[index] in "*_~":
                view[index] = "x"
    return "".join(view)


def _flanking(char):
    """Classify CHAR next to a delimiter run: "space", "punct", or "other".

    The classes are those of GitHub's parser (cmark-gfm): punctuation is ASCII
    punctuation or a Unicode P* character, so a symbol such as "→" is "other".
    """
    if char in UNICODE_SPACE:
        return "space"
    if char in ASCII_PUNCTUATION or (char > "\x7f" and unicodedata.category(char)[0] == "P"):
        return "punct"
    return "other"


def _emphasis_runs(text):
    """Return the end offsets of the "*" and "_" runs in TEXT that emphasis uses.

    TEXT is one prose block. This follows the delimiter run rules of
    CommonMark 6.2 and its "process emphasis" procedure. A left-flanking run can
    open, and a right-flanking run can close. An "_" run that is both opens only
    after punctuation and closes only before punctuation, so an underscore
    inside a word does neither. A run closes when an open run of the same
    character comes before it anywhere in the block, also in an earlier
    sentence. The rule of 3 applies: when one of the two runs can both open and
    close, their lengths must not add up to a multiple of 3, unless both are
    multiples of 3. The open runs between the two close with them, and their
    markers stay text. Emphasis uses a run when it uses one or more of its
    markers, to open or to close. A backslash makes the first marker of a run
    text. As in GitHub's parser (cmark-gfm), the strikethrough runs ("~" and
    "~~") are in the same stack: a closing one removes its opener and the runs
    between. A "~" next to a "*" or "_" run is skipped when the run is
    classified. BOTTOMS keeps the cost linear: after a search for an opener
    fails, the next search for a closer of the same character and length
    modulo 3 stops there.
    """
    ends = set()
    stack = []  # [character, length left, length, can close, end offset] of each open run
    bottoms = {}  # (character, length % 3) of a closer -> stack size below which no opener fits

    def cut(size):
        del stack[size:]
        for key in bottoms:
            bottoms[key] = min(bottoms[key], size)

    for run in EMPHASIS_RUN.finditer(text):
        start = run.start() + _escaped(text, run.start())  # a backslash makes the first marker text
        if start == run.end():
            continue
        char, length = run.group()[0], run.end() - start
        if char == "~" and length > 2:
            continue  # a strikethrough run has one or two markers
        left, right = start, run.end()
        while char != "~" and left and text[left - 1] == "~":
            left -= 1
        while char != "~" and right < len(text) and text[right] == "~":
            right += 1
        before = _flanking(text[left - 1]) if left else "space"
        after = _flanking(text[right]) if right < len(text) else "space"
        can_open = after != "space" and (after != "punct" or before != "other")
        can_close = before != "space" and (before != "punct" or after != "other")
        if char == "_":
            can_open, can_close = (can_open and (not can_close or before == "punct"),
                                   can_close and (not can_open or after == "punct"))
        full = length
        while can_close and length:
            key = (char, full % 3)
            for index in range(len(stack) - 1, bottoms.get(key, 0) - 1, -1):
                open_char, open_left, open_full, open_close, open_end = stack[index]
                if open_char == char and not ((open_close or can_open) and (open_full + full) % 3 == 0
                                              and (open_full % 3 or full % 3)):
                    break
            else:
                bottoms[key] = len(stack)
                break
            if char == "~":
                cut(index)  # the strikethrough closes, with both runs and all runs between
                length = 0
                break
            ends.update((run.end(), open_end))
            used = 2 if length >= 2 and open_left >= 2 else 1
            length -= used
            if open_left > used:
                stack[index][1] -= used
                cut(index + 1)
            else:
                cut(index)
        if can_open and length:
            stack.append([char, length, full, can_close, run.end()])
    return ends


def _sentence_starts(text, view=None, emphasis=None):
    """Return the offset of each sentence start in text.

    A sentence ends at a word that ends in terminal punctuation, after any
    closing quotes or brackets. Known abbreviations do not end a sentence.
    VIEW is TEXT as _emphasis_view gives it, where the emphasis runs are read.
    A "*" or "_" after the stop ends the sentence only when emphasis uses it,
    as GitHub shows it. An underscore that the masking put there is no run.
    EMPHASIS holds the end offsets of the runs that emphasis uses. When it is
    None, the runs are read in VIEW. One pass over the words keeps the cost
    linear in the text length.
    """
    words = list(re.finditer(r"\S+", text))
    if not words:
        return [0]
    view = text if view is None else view
    if emphasis is None:
        emphasis = _emphasis_runs(view)
    starts = [words[0].start()]
    for word, next_word in zip(words, words[1:]):
        end = SENTENCE_END.search(word.group())
        if not end:
            continue
        if not all(run.end() in emphasis
                   for run in DELIMITER_RUN.finditer(view, word.start() + end.start(), word.end())):
            continue
        core = word.group()[:end.start() + 1].lstrip(OPENERS)
        if core.lower() in ABBREVIATIONS:
            continue
        if (DOTTED_ABBREVIATION.fullmatch(core)
                and not next_word.group().lstrip(OPENERS)[:1].isupper()):
            continue
        starts.append(next_word.start())
    return starts


def _long_sentence_findings(pieces, filename, emphasis=None):
    """Flag long sentences in one prose block.

    pieces is a list of (lineno, source_column, text, view, ...) tuples. TEXT is the
    line with code spans and links masked. VIEW is the line as _emphasis_view
    gives it, at the same length. The texts are joined with spaces, so a
    sentence wrapped across source lines is counted once, and each finding
    points at the line and column where it starts. EMPHASIS holds the end
    offsets of the runs that emphasis uses in the joined views, or None.
    """
    offsets, position = [], 0
    for piece in pieces:
        offsets.append(position)
        position += len(piece[2]) + 1
    joined = " ".join(piece[2] for piece in pieces)
    view = " ".join(piece[3] for piece in pieces)
    findings = []
    starts = _sentence_starts(joined, view, emphasis)
    for start, end in zip(starts, starts[1:] + [len(joined)]):
        n = _count_words(joined[start:end])
        if n <= MAX_WORDS:
            continue
        index = bisect.bisect_right(offsets, start) - 1
        offset = offsets[index]
        lineno, source_column = pieces[index][:2]
        findings.append({"file": filename, "line": lineno,
                         "col": source_column + start - offset + 1,
                         "rule": "long-sentence", "level": "advisory-free",
                         "match": f"{n} words",
                         "message": f"Sentence has {n} words (cap {MAX_WORDS}). Split it."})
    return findings


def _block_emphasis(blocks):
    """Return, for each block in BLOCKS, the end offsets of the runs that emphasis uses.

    A block is a list of (lineno, source_column, text, view, paragraph, wraps,
    unsure) pieces, and the offsets are in its views joined with spaces.
    GitHub reads the emphasis of a paragraph as a whole, and a paragraph can
    hold more than one block: a lazy line after a quote line starts a new
    block, for example. So the runs are read in the joined views of all pieces
    of a PARAGRAPH. WRAPS is True when an inline HTML item can start in the
    piece and end on a later line. The view does not show where that item
    ends. UNSURE is True when GitHub can put the line in another paragraph
    than the main loop does. So when a piece other than the last piece of a
    paragraph wraps, or when a piece is unsure, each run of that paragraph
    counts as used, as before this check.
    """
    flat = [piece for block in blocks for piece in block]
    paragraphs = {}  # paragraph -> the indexes of its pieces in FLAT
    for index, piece in enumerate(flat):
        paragraphs.setdefault(piece[4], []).append(index)
    used = [None] * len(flat)  # the run ends of each piece, in its view
    for indexes in paragraphs.values():
        view = " ".join(flat[index][3] for index in indexes)
        if any(flat[index][5] for index in indexes[:-1]) or any(flat[index][6] for index in indexes):
            ends = [run.end() for run in DELIMITER_RUN.finditer(view)]
        else:
            ends = sorted(_emphasis_runs(view))
        offset = 0
        for index in indexes:
            size = len(flat[index][3])
            low = bisect.bisect_right(ends, offset)
            high = bisect.bisect_right(ends, offset + size)
            used[index] = [end - offset for end in ends[low:high]]
            offset += size + 1
    result, index = [], 0
    for block in blocks:
        ends, offset = set(), 0
        for piece in block:
            ends.update(offset + end for end in used[index])
            offset += len(piece[3]) + 1
            index += 1
        result.append(ends)
    return result


# One blockquote level: up to three spaces, ">", and one optional space.
QUOTE_LEVEL = re.compile(r" {0,3}> ?")


def _strip_quotes(line, depth=None):
    """Return (levels, rest): the blockquote levels that start LINE and the text after them.

    With DEPTH, remove at most DEPTH levels: a deeper ">" is content.
    """
    levels, pos = 0, 0
    while depth is None or levels < depth:
        level = QUOTE_LEVEL.match(line, pos)
        if not level:
            break
        levels, pos = levels + 1, level.end()
    return levels, line[pos:]


def _indent_width(text):
    """Columns of the spaces and tabs that start TEXT, with a tab stop of 4."""
    return len(text[:len(text) - len(text.lstrip(" \t"))].expandtabs(4))


def _fence_ends_with_quote(fence, line):
    """True when LINE has fewer blockquote levels than the open FENCE."""
    return fence is not None and _strip_quotes(line.expandtabs(4), fence[1])[0] < fence[1]


def _fence_step(fence, line):
    """Return (is_fence_line, open_fence) after LINE.

    FENCE is None, or the open fence as (run, quote depth, indent). This follows
    CommonMark 4.5 for blockquotes and for the fence itself: a fence in a blockquote
    ends when its quote ends. Only a run of the same character, at least as long,
    with only spaces or tabs after it, closes the block. A backtick fence has no
    backtick in its info string. List items are not tracked, so the indent of a
    fence is not limited to three columns. A closing fence may have at most three
    columns more indent than the opening fence, also at the top level.
    """
    # Tabs become spaces from the real column, so a tab after ">" counts correctly.
    line = line.expandtabs(4)
    if fence is None:
        depth, rest = _strip_quotes(line)
        content = rest.lstrip(" \t")
        marker = CODE_FENCE.match(content)
        if not marker:
            return False, None
        run = marker.group(1)
        if run[0] == "`" and "`" in content[marker.end():]:
            return False, None
        return True, (run, depth, _indent_width(rest))
    if _fence_ends_with_quote(fence, line):
        # The quote that holds the fence ended, so the fence ended too.
        return _fence_step(None, line)
    run, depth, indent = fence
    rest = _strip_quotes(line, depth)[1]
    content = rest.lstrip(" \t")
    marker = CODE_FENCE.match(content)
    if (marker and marker.group(1)[0] == run[0] and len(marker.group(1)) >= len(run)
            and _indent_width(rest) <= indent + 3
            and not content[marker.end():].strip(" \t")):
        return True, None
    return False, fence


# CommonMark 4.6: how each kind of HTML block starts, and the text that ends it.
# None: the block ends at a blank line (types 6 and 7).
_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
    "optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|"
    "tr|track|ul"
)
HTML_BLOCK_KINDS = [
    (re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?:[ \t]|>|$)", re.I),
     re.compile(r"</(?:script|pre|style|textarea)>", re.I)),
    (re.compile(r"^ {0,3}<!--"), re.compile(r"-->")),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(rf"^ {{0,3}}</?(?:{_BLOCK_TAGS})(?:[ \t]|/?>|$)", re.I), None),
]
HTML_COMMENT_END = HTML_BLOCK_KINDS[1][1]
# Type 7: one complete open or closing tag alone on its line (CommonMark 6.6 grammar).
# It cannot interrupt a paragraph. In one line, CommonMark whitespace is a space or a
# tab: a no-break space or another Unicode space is text, so the line is no tag.
_ATTRIBUTE = (r"[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*"
              r"(?:[ \t]*=[ \t]*(?:[^ \t\"'=<>`]+|'[^']*'|\"[^\"]*\"))?")
# The names of type 1 (pre, script, style, textarea) never start a type 7 block,
# as an open tag or as a closing tag. A custom name such as pre-x is no type 1 name.
_TYPE1_NAME = r"(?!(?i:pre|script|style|textarea)(?![A-Za-z0-9-]))"
HTML_TYPE7 = re.compile(
    rf"^ {{0,3}}(?:<{_TYPE1_NAME}[A-Za-z][A-Za-z0-9-]*(?:{_ATTRIBUTE})*[ \t]*/?>"
    rf"|</{_TYPE1_NAME}[A-Za-z][A-Za-z0-9-]*[ \t]*>)[ \t]*$")
# Lines that end a paragraph and are no paragraph line, after the quote prefix: an ATX
# heading and a thematic break of one repeated character. A quote line with no text
# also ends a paragraph.
NO_PARAGRAPH = re.compile(
    r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|(?:-[ \t]*){3,}$|(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$)")
# A setext underline. It ends a paragraph only when a paragraph is open at the same
# quote depth. Else it is text, also as a lazy line after a quote (CommonMark 4.3).
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")


def _html_block_step(block, line, in_paragraph):
    """Return (in_html_block, open_block) for LINE.

    BLOCK is None, False (an HTML block that ends at a blank line), or the pattern
    that ends the open block. IN_PARAGRAPH: a paragraph is open before LINE. A ">"
    in an HTML block is text, so it opens no fence.
    """
    if block is None:
        for start, end in HTML_BLOCK_KINDS:
            if start.match(line):
                block = False if end is None else end
                break
        else:
            if in_paragraph or not HTML_TYPE7.match(line):
                return False, None
            block = False
    if block is False:
        return bool(line.strip()), (block if line.strip() else None)
    return True, (None if block.search(line) else block)


# GitHub shows the text of an HTML block of type 6 or 7. It also shows the text of a
# <script>, <style> or <textarea> block, because it escapes these tags (tagfilter). It
# shows a <pre> block as code, and it hides a comment and a "<?", "<!X" or CDATA block.
SHOWN_TYPE1 = re.compile(r"^ {0,3}<(?i:script|style|textarea)(?:[ \t]|>|$)")


def _block_shows_text(block, line):
    """True when GitHub shows the text of the HTML BLOCK that starts on LINE as prose."""
    return block is False or bool(SHOWN_TYPE1.match(line))


def _tab_item(line):
    """Match LINE as a list marker that the pass reads as no item, or return None.

    The marker has a tab after it, or nothing after it (an empty item). Tabs become
    spaces, so the match has the columns of GitHub.
    """
    expanded = line.expandtabs(4)
    return LIST_ITEM_START.match(expanded) or LIST_ITEM_START.match(expanded + " ")


def _is_list_continuation(line, content_indent):
    if not line.strip():
        return True
    if LIST_ITEM_START.match(line):
        return False
    return len(line[:len(line) - len(line.lstrip(" \t"))].expandtabs(4)) >= content_indent


def _split_table_row(line):
    """Return trimmed table cells and their zero-based source columns.

    A row needs a leading or trailing pipe, or a pipe between two cells.
    Escaped pipes stay in their cell. This deliberately implements only the
    ordinary Markdown table shape; it is enough to distinguish a table from
    prose that happens to contain a pipe.
    """
    left = len(line) - len(line.lstrip())
    right = len(line.rstrip())
    content = line[left:right]
    if "|" not in content:
        return None
    edge_pipe = False
    if content.startswith("|"):
        content = content[1:]
        left += 1
        edge_pipe = True
    if content.endswith("|"):
        content = content[:-1]
        edge_pipe = True
    raw_cells = re.split(r"(?<!\\)\|", content)
    if len(raw_cells) < 2 and not edge_pipe:
        return None

    cells = []
    column = left
    for raw_cell in raw_cells:
        leading = len(raw_cell) - len(raw_cell.lstrip())
        cells.append((raw_cell.strip(), column + leading))
        column += len(raw_cell) + 1
    return cells


def _markdown_table_cells(lines):
    """Map ordinary Markdown table rows to their prose cells.

    The separator row anchors detection, so pipe-containing prose is not
    treated as a table. Both leading-pipe and no-leading-pipe table styles are
    accepted. As in GFM, the header and separator must have the same number of
    cells, but a body row may have fewer or more. A line without a pipe ends
    the table.
    """
    table_cells = {}
    index = 1
    while index < len(lines):
        separator = _split_table_row(lines[index])
        header = _split_table_row(lines[index - 1])
        if (not separator or not header or len(separator) != len(header)
                or not all(TABLE_SEPARATOR_CELL.fullmatch(cell)
                           for cell, _ in separator)):
            index += 1
            continue

        table_cells[index - 1] = header
        table_cells[index] = []
        index += 1
        while index < len(lines):
            row = _split_table_row(lines[index])
            if not row:
                break
            table_cells[index] = row
            index += 1
    return table_cells


def _dangling_conjunction_findings(text, filename):
    lines = text.splitlines()
    findings = []
    fence = None
    # The content indent of the list item whose marker line opened FENCE (0: none). On
    # GitHub such a fence ends with its item at the latest.
    fence_container = 0
    # True after a fence on the line of a list marker (see below). From there on, a
    # fence that opens in a list item ends with its item, as on GitHub. Before it, such
    # a fence can go on after the item, as in the earlier versions of this pass, so a
    # document with no fence on a marker line keeps its findings.
    marker_fences = False
    # The HTML block open outside the item loop below, as _html_block_step returns it,
    # the content indent of the list item that holds it (0: no item), and whether
    # GitHub shows its text.
    html_block, html_container, html_shows = None, 0, False
    # The content indents of the list items that can still hold a line, outermost first.
    open_items = []
    # A paragraph is open before the line: a text line with less indent continues it
    # (a lazy line). PARAGRAPH_INDENT is the content indent of the list item that holds
    # the paragraph (0: no item), or None in a quote. As in cmark-gfm, type 7 cannot
    # interrupt the paragraph on a line that is in that item too.
    in_paragraph, paragraph_indent = False, None

    def close_items(indent):
        """A line with INDENT ends the list items with more content indent."""
        while open_items and open_items[-1] > indent:
            open_items.pop()

    index = 0
    while index < len(lines):
        line = lines[index]
        if (fence is not None and fence_container and line.strip(" \t")
                and _indent_width(line) < fence_container):
            fence = None
        if _fence_ends_with_quote(fence, line):
            # The quote of the fence ended: judge this line as any other line.
            fence = None
        if fence is None:
            fence_container = 0
            # A line with less indent than the item that holds the block ends the item,
            # and the block in it. GitHub still hides the text after an open comment up to
            # "-->", as in the item loop below.
            if (html_block is not None and html_block is not HTML_COMMENT_END
                    and line.strip(" \t") and _indent_width(line) < html_container):
                html_block = None
            open_block = html_block
            continues = (in_paragraph and paragraph_indent is not None
                         and _indent_width(line) >= paragraph_indent)
            # A block starts at the indent of the list item that holds the line, not at
            # the start of the line.
            line_indent = _indent_width(line)
            block_indent = next((indent for indent in reversed(open_items)
                                 if indent <= line_indent), 0)
            block_line = line.expandtabs(4)[block_indent:]
            in_html, html_block = _html_block_step(html_block, block_line, continues)
            if in_html and open_block is None:
                close_items(line_indent)
                html_container = open_items[-1] if open_items else 0
                html_shows = _block_shows_text(html_block, block_line)
            # An HTML block holds literal text: no fence opens in it, and outside list items
            # no list item starts in it. In a list item, the text that GitHub shows in the
            # block is item text, so a list marker there starts an item, as before. The
            # block stays open after that item, so a fence line in it is still text. The
            # line that ends the block is in the block, so no item starts on it.
            if (in_html and open_block is not None and html_block is not None
                    and html_shows and html_container and LIST_ITEM_START.match(line)):
                in_html = False
            if in_html:
                in_paragraph = False
                index += 1
                continue
        is_fence, fence = _fence_step(fence, line)
        if is_fence or fence:
            if is_fence and fence is not None:
                close_items(_indent_width(line))
                if marker_fences and open_items:
                    fence_container = open_items[-1]
            in_paragraph = False
            index += 1
            continue
        start = LIST_ITEM_START.match(line)
        if not start:
            # A blank line has only spaces and tabs: a no-break space is text. A line
            # with only quote markers is blank in its quote.
            depth, content = _strip_quotes(line.expandtabs(4))
            # A setext underline in the container of the paragraph makes it a heading,
            # so the paragraph ends. As a lazy line it is text (CommonMark 4.3).
            underline = (in_paragraph and paragraph_indent is not None and not depth
                         and _indent_width(line) >= paragraph_indent
                         and SETEXT_UNDERLINE.match(content))
            text_line = (bool(content.strip(" \t")) and not NO_PARAGRAPH.match(content)
                         and not underline)
            # A list marker with a tab after it starts an item on GitHub. The pass reads no
            # item there, as before, but an HTML block after the marker line can be in that
            # item, so its content indent goes on the stack, and the text of the line is a
            # paragraph in the item. As a paragraph line, it starts an item only where a
            # list item can interrupt the paragraph. After a fence on a marker line, a
            # marker with nothing after it is such an item too (an empty item).
            tab_item = (None if depth or underline or NO_PARAGRAPH.match(content)
                        else _tab_item(line) if marker_fences
                        else LIST_ITEM_START.match(line.expandtabs(4)))
            if (tab_item and in_paragraph and paragraph_indent is not None
                    and _indent_width(line) >= paragraph_indent):
                tab_marker = tab_item.group("marker")
                if ((tab_marker[:-1].isdigit() and tab_marker[:-1].lstrip("0") != "1")
                        or not tab_item.group("body").strip(" \t")):
                    tab_item = None
            if line.strip(" \t") and not (in_paragraph and text_line and not depth):
                close_items(_indent_width(line))
                paragraph_indent = None if depth else (open_items[-1] if open_items else 0)
            if tab_item:
                close_items(len(tab_item.group("indent")))
                # An empty item, or indented code after five or more columns, holds no
                # paragraph, and the content starts one column after the marker.
                no_paragraph = (len(tab_item.group("gap")) > 4
                                or not tab_item.group("body").strip(" \t"))
                paragraph_indent = (tab_item.end("marker") + 1 if no_paragraph
                                    else tab_item.start("body"))
                # An empty item ends at a blank line after its marker (see below).
                if (tab_item.group("body").strip(" \t")
                        or (index + 1 < len(lines) and lines[index + 1].strip(" \t"))):
                    open_items.append(paragraph_indent)
                text_line = (text_line and not no_paragraph
                             and not NO_PARAGRAPH.match(tab_item.group("body")))
                # An HTML block or a fence can start on the line of the marker, in the item.
                if not no_paragraph and html_block is None:
                    tab_body = tab_item.group("body")
                    tab_fence = _fence_step(None, " " * paragraph_indent + tab_body)[1]
                    tab_html, html_block = _html_block_step(None, tab_body, False)
                    if tab_fence is not None:
                        fence, fence_container = tab_fence, paragraph_indent
                        marker_fences = True
                        html_block, text_line = None, False
                    elif tab_html:
                        html_container = paragraph_indent
                        html_shows = _block_shows_text(html_block, tab_body)
                        text_line = False
            in_paragraph = text_line
            index += 1
            continue

        # A list item that starts with a number other than 1, and an empty list item,
        # cannot interrupt a paragraph (CommonMark 5.2): GitHub reads the line as text of
        # the paragraph. An empty "-" item there is a setext underline, so the paragraph
        # ends. The pass still reads the lines of the item, but with no HTML block in them
        # (they are paragraph text), and after the item the paragraph stays open in its
        # container. The item is not open for later lines.
        marker, body = start.group("marker"), start.group("body")
        outer_paragraph = (in_paragraph and paragraph_indent is not None
                           and _indent_width(line) >= paragraph_indent
                           and ((marker[:-1].isdigit() and marker[:-1].lstrip("0") != "1")
                                or (not body.strip(" \t") and marker != "-")))
        outer_indent = paragraph_indent
        # An empty "-" item there is a setext underline on GitHub: no item.
        underline = (in_paragraph and paragraph_indent is not None
                     and _indent_width(line) >= paragraph_indent
                     and marker == "-" and not body.strip(" \t"))
        close_items(len(start.group("indent")))
        # After five or more spaces the text is indented code, and the content column
        # is one space after the marker (CommonMark 5.2).
        gap = len(start.group("gap"))
        if gap > 4 and body.strip(" \t"):
            gap = 1
        content_indent = len(start.group("indent")) + len(start.group("marker")) + gap
        # A list marker in an open HTML block around the item is text of the block on
        # GitHub, so the item is not open for later lines (see the item loop below).
        # After five or more columns, or in an empty item, the content of the item starts
        # one column after the marker (CommonMark 5.2), so an HTML block there is in it.
        # A tab in the gap goes to the next tab stop. Indented code is no paragraph.
        expanded = LIST_ITEM_START.match(line.expandtabs(4))
        # After five or more columns the body is no item text: it is indented code, or
        # text of a paragraph outside list items. In an open HTML block, and in a
        # paragraph of a list item, it is item text.
        code_body = (len(expanded.group("gap")) > 4 and html_block is None
                     and not (outer_paragraph and outer_indent))
        # After indented code, also with a tab in the gap, a line of the item can start an
        # HTML block from one column after the marker (CommonMark 5.2), or None: from the
        # content indent. A line with four or more columns more is indented code.
        html_column = expanded.end("marker") + 1 if code_body else None
        # The content column of the item on GitHub, for a fence in the item (see the
        # fence step below), or None. An empty item ends at a blank line after its marker,
        # so it holds no later line.
        fence_column = None
        if not outer_paragraph and not underline and html_block is None:
            item_indent = expanded.start("body")
            if code_body or not body.strip(" \t"):
                item_indent = expanded.end("marker") + 1
            if body.strip(" \t") or (index + 1 < len(lines) and lines[index + 1].strip(" \t")):
                open_items.append(item_indent)
                fence_column = item_indent
        # An HTML block can start on the line of the marker. It is in the item, and it
        # ends when the item ends. After five or more spaces the text is indented code.
        body_html, item_html, item_shows = False, None, False
        # A fence can open on the line of the marker too. It is in the item, and it ends
        # with the item at the latest.
        body_fence = None
        # In an open HTML block around the item, the body is text of that block.
        if html_block is None and not outer_paragraph and len(start.group("gap")) <= 4:
            # After five or more columns (a tab goes to the next tab stop), the text is
            # indented code, not a fence.
            if not code_body:
                body_fence = _fence_step(None, " " * content_indent + body)[1]
            marker_fences = marker_fences or body_fence is not None
            if body_fence is None:
                body_html, item_html = _html_block_step(None, body, False)
                item_shows = _block_shows_text(item_html, body)
            else:
                # The item holds the fence from the column where its body starts, also
                # after a tab in the gap, and it ends with the first line with less indent.
                content_indent = expanded.start("body")
        item_paragraph = outer_paragraph or (bool(body.strip(" \t")) and not body_html
                                             and body_fence is None and not code_body
                                             and not NO_PARAGRAPH.match(body))
        # A block of code or hidden text that stays open shows no item text (see below),
        # and the line that opens a fence, or indented code after the marker, is no item
        # text.
        item_lines = ([] if (item_html and not item_shows) or body_fence or code_body
                      else [(index, body)])
        next_index = index + 1
        # The fence of the item, and the content indent of the item (or of the nested
        # item, see below) when the fence opened on the line of its marker (else 0).
        item_fence, fence_indent = body_fence, content_indent if body_fence else 0
        # The content indent of the nested item that holds the open HTML block of the
        # item (a list marker with a tab after it, see below), or None.
        nested_indent = None
        # The content column of a nested empty item, or of a nested item with indented
        # code after its marker (see below), for a fence in it, or None.
        nested_fence = None
        # A nested list that GitHub starts in this item (see below) is the last block of
        # the item: the item holds no paragraph of its own, so an empty item or any number
        # can start a nested item there. nested_code: the nested item holds no paragraph
        # (it is empty, or it holds indented code), so no lazy line continues it.
        nested_list = nested_code = False
        while next_index < len(lines):
            candidate = lines[next_index]
            # An open HTML block around this item (a list marker in it started the item,
            # see above) goes on over the lines of the item, as raw item text, up to a
            # blank line, its end pattern or a line with less indent than its container.
            if html_block is not None:
                if candidate.strip(" \t") and _indent_width(candidate) < html_container:
                    html_block = None
                else:
                    in_outer_html, html_block = _html_block_step(html_block, candidate, False)
                    if html_block is None:
                        # The block ended. GitHub reads the next lines in its container.
                        content_indent = html_container
                    if in_outer_html:
                        # The line that ends the block is in it, also after a list marker.
                        if (html_block is not None
                                and not _is_list_continuation(candidate, content_indent)):
                            break
                        item_lines.append((next_index, candidate))
                        item_paragraph = False
                        next_index += 1
                        continue
            if _fence_ends_with_quote(item_fence, candidate):
                # The quote of the fence ended: judge this line as any other line.
                item_fence = None
            if nested_list and candidate.strip(" \t"):
                column = nested_indent if nested_indent is not None else nested_fence
                if column is not None and _indent_width(candidate) >= column:
                    # A line of the nested item: indented code goes on, text is a paragraph.
                    if nested_fence is not None and nested_code:
                        nested_code = _indent_width(candidate) >= nested_fence + 4
                elif not _tab_item(candidate):
                    # A line outside the nested item ends the nested list, unless it goes
                    # on with the paragraph of the nested item (a lazy line) or starts the
                    # next nested item. The line is in this item, not in a paragraph, so
                    # any block starts there, also an HTML block of type 7.
                    text = (" " * max(0, _indent_width(candidate) - content_indent)
                            + candidate.lstrip(" \t"))
                    nested_list = (item_paragraph and not nested_code
                                   and not NO_PARAGRAPH.match(text)
                                   and not text.lstrip(" ").startswith(">")
                                   and not _fence_step(None, text)[0]
                                   and not _html_block_step(None, text, False)[0])
            # A line with less indent than the nested item (see below) ends that item, and
            # the HTML block in it. GitHub still hides an open comment up to "-->".
            if (nested_indent is not None and candidate.strip(" \t")
                    and _indent_width(candidate) < nested_indent):
                nested_indent = None
                if item_html is not HTML_COMMENT_END:
                    item_html = None
            if (nested_fence is not None and candidate.strip(" \t")
                    and _indent_width(candidate) < nested_fence):
                nested_fence = None
            # A fence from the line of a marker ends with its item at the latest.
            if (item_fence is not None and fence_indent and candidate.strip(" \t")
                    and _indent_width(candidate) < fence_indent):
                item_fence, fence_indent = None, 0
            if item_html is HTML_COMMENT_END:
                # GitHub hides the text from "<!--" up to "-->", also over the end of the
                # item and over the next items. The text after "-->" joins this item. No
                # item, block or fence starts in the comment.
                end = HTML_COMMENT_END.search(candidate)
                if end:
                    item_html = None
                    # spaces keep the columns
                    item_lines.append((next_index, " " * end.end() + candidate[end.end():]))
                item_paragraph = False
                next_index += 1
                continue
            in_html = hidden = False
            if item_fence is None and not outer_paragraph:
                if candidate.strip() and _indent_width(candidate) < content_indent:
                    item_html = None  # the line ends the item, and the HTML block in it
                else:
                    # The item holds its lines from the content indent on, and the nested
                    # item from its content indent on.
                    open_block = item_html
                    rest = candidate.expandtabs(4)[nested_indent or html_column or content_indent:]
                    line_paragraph = item_paragraph
                    # A list marker with a tab after it starts no item for the pass, as
                    # before: its line is a line of this item. On GitHub it starts a nested
                    # item, and an HTML block can start on its line, in that item (as in the
                    # text branch above). A number other than 1 cannot interrupt the paragraph.
                    # An empty item (also with nothing after the marker), and an item with
                    # indented code after five or more columns, hold their lines from one
                    # column after the marker on GitHub. The pass keeps that column only for
                    # a fence in the item (see the fence step below). An empty item cannot
                    # interrupt the paragraph either (an empty "-" is a setext underline), and
                    # it ends at a blank line after its marker. After a nested item, the
                    # paragraph is that of the nested item (see nested_list above).
                    nested = (None if open_block is not None or LIST_ITEM_START.match(candidate)
                              else _tab_item(candidate))
                    empty = nested is not None and not nested.group("body").strip(" \t")
                    own_paragraph = item_paragraph and not nested_list
                    if (nested and (empty or len(nested.group("gap")) > 4)
                            and not (own_paragraph and (empty or (
                                nested.group("marker")[:-1].isdigit()
                                and nested.group("marker")[:-1].lstrip("0") != "1")))
                            and not (empty and not (next_index + 1 < len(lines)
                                                    and lines[next_index + 1].strip(" \t")))):
                        nested_fence = nested.end("marker") + 1
                        nested_list = nested_code = True
                    elif (nested and len(nested.group("gap")) <= 4
                            and nested.group("body").strip(" \t")):
                        nested_marker = nested.group("marker")
                        if not (own_paragraph and nested_marker[:-1].isdigit()
                                and nested_marker[:-1].lstrip("0") != "1"):
                            nested_list, nested_code = True, False
                            nested_indent = nested.start("body")
                            nested_body = nested.group("body")
                            item_fence = _fence_step(None, " " * nested_indent + nested_body)[1]
                            if item_fence is not None:
                                fence_indent, marker_fences = nested_indent, True
                            elif _html_block_step(None, nested_body, False)[0]:
                                rest, line_paragraph = nested_body, False
                    in_html, item_html = _html_block_step(open_block, rest, line_paragraph)
                    if in_html and open_block is None:
                        item_shows = _block_shows_text(item_html, rest)
                    # A <pre> block holds code, and GitHub hides a comment and a "<?", "<!X"
                    # or CDATA block. As in a fence, the lines of such a block, from its
                    # first line up to its last line, are no item text, and no list item
                    # starts there. The last line can show text after the end of the block.
                    # (An open end pattern is not None or False.)
                    hidden = bool(item_html) and not item_shows
            if hidden:
                item_paragraph = False
                next_index += 1
                continue
            # A line outside the item ends it, also when it opens a fence. The line that ends
            # an HTML block of the item is in the block, also after a list marker.
            if (item_fence is None and not _is_list_continuation(candidate, content_indent)
                    and not (in_html and item_html is None)):
                break
            # Fence delimiters are state markers, not meaningful item lines.
            # In an HTML block, a fence line is text.
            if not in_html:
                is_fence, item_fence = _fence_step(item_fence, candidate)
                if item_fence is None:
                    fence_indent = 0
                elif is_fence and marker_fences and not outer_paragraph:
                    # After a fence on a marker line, a fence ends with its item (see above).
                    fence_indent = nested_indent if nested_indent is not None else content_indent
                    # On GitHub the item holds its lines from its content column on: one column
                    # after the marker in an empty item or after indented code, and after a tab
                    # in the gap at the next tab stop. A fence line from that column on, with
                    # less than four columns more indent, is a fence of the item there. A fence
                    # line with less indent ends the item, and the fence opens after it.
                    # In such a nested item, empty or with indented code, the column is that
                    # of the nested item (see above).
                    item_column = fence_column if nested_fence is None else nested_fence
                    if nested_indent is None and item_column is not None:
                        if item_column <= _indent_width(candidate) < item_column + 4:
                            fence_indent = item_column
                        elif _indent_width(candidate) < item_column:
                            item_fence, fence_indent = None, 0
                            break
                if is_fence or item_fence:
                    item_paragraph = False
                    next_index += 1
                    continue
            item_lines.append((next_index, candidate))
            item_paragraph = (not in_html and bool(candidate.strip(" \t"))
                              and not NO_PARAGRAPH.match(
                                  candidate.expandtabs(4)[nested_indent or content_indent:]))
            next_index += 1
        # A list marker in a block of the item whose text GitHub shows ends the item, as
        # before, but on GitHub the block goes on. Hand it on, so that the lines after the
        # next item are still in it.
        if (item_html is not None and next_index < len(lines)
                and LIST_ITEM_START.match(lines[next_index])
                and _indent_width(lines[next_index]) >= content_indent):
            html_block, html_container, html_shows = item_html, content_indent, item_shows
        # The line after the item can continue the last paragraph of the item.
        in_paragraph = item_paragraph
        paragraph_indent = outer_indent if outer_paragraph else content_indent

        meaningful = []
        for line_index, item_line in item_lines:
            # Preserve code spans as neutral operands while ignoring their contents.
            cleaned = INLINE_CODE.sub(" CODE ", item_line).strip()
            if cleaned:
                meaningful.append((line_index, cleaned))
        if meaningful:
            end_line_index, end_line = meaningful[-1]
            conjunction = CONJUNCTION_END.search(end_line)
        else:
            end_line_index, end_line, conjunction = None, None, None
        if conjunction:
            if end_line_index == index:
                finding_line = index + 1
                finding_col = start.start("marker") + 1
            else:
                raw_end_line = next(
                    raw for line_index, raw in item_lines
                    if line_index == end_line_index
                )
                masked_end_line = INLINE_CODE.sub(
                    lambda match: " " * len(match.group(0)), raw_end_line
                )
                raw_conjunction = CONJUNCTION_END.search(masked_end_line)
                finding_line = end_line_index + 1
                finding_col = raw_conjunction.start() + 1 if raw_conjunction else 1
            findings.append({
                "file": filename,
                "line": finding_line,
                "col": finding_col,
                "rule": "dangling-conjunction",
                "level": "advisory-free",
                "match": end_line,
                "message": "List item ends with a coordinating conjunction. Complete the item or join it with the next item.",
            })
        index = next_index
    return findings


# A line of YAML front matter: a key, a list item, an indented line, or a comment.
# A key is quoted, or a plain word that starts with no YAML indicator; ": "
# or ":" at the end of the line ends it. A plain key with a space is valid
# YAML, but prose such as "Step 1: run it" looks the same, so it is Markdown.
_YAML_KEY = (r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s#'"\[\]{},&*!|>%@`-]\S*?)"""
             r"[ \t]*:(?:[ \t]|$)")
FRONT_MATTER_KEY = re.compile(_YAML_KEY)
FRONT_MATTER_LINE = re.compile(_YAML_KEY + r"|-(?:[ \t]|$)|[ \t]+\S|#")
# The key "description", plain or in quotes.
DESCRIPTION_KEY = re.compile(r"""(?:description|"description"|'description')[ \t]*:(?:[ \t]+|$)""")
# A block scalar indicator ("|", ">-", "|2+"), with an optional comment.
BLOCK_SCALAR = re.compile(r"[|>][1-9+-]{0,2}(?:[ \t]+#.*)?")
# A YAML comment in a plain scalar: "#" at the start or after a space or tab.
YAML_COMMENT = re.compile(r"(?:^|[ \t])#")


def _closing_quote(text, quote):
    """Return the index of the QUOTE that closes a quoted YAML scalar in TEXT, or None.

    In single quotes, '' is a quote. In double quotes, a backslash escapes the
    next character.
    """
    pos = 0
    while pos < len(text):
        if quote == '"' and text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == quote:
            if quote == "'" and text[pos + 1:pos + 2] == "'":
                pos += 2
                continue
            return pos
        pos += 1
    return None


def _scalar_pieces(value, parts):
    """Return the prose pieces of a YAML scalar as (line index, column, text).

    VALUE is the text after the key. PARTS are the lines of the scalar with
    their line index and the column of their text, the key line first when
    VALUE is not empty. A block scalar ("|", ">-") keeps each later line up to
    one with less indent than its first, also a "#". A quoted scalar ends at
    its closing quote. A plain scalar ends at a comment. A comment after the
    scalar is not prose.
    """
    pieces = []
    if BLOCK_SCALAR.fullmatch(value):
        # The first line sets the indent. A line with less indent, such as a
        # comment, ends the scalar.
        for piece in parts[1:]:
            if piece[1] < parts[1][1]:
                break
            pieces.append(piece)
    elif value[:1] in ("'", '"'):
        index, column, text = parts[0]
        parts = [(index, column + 1, text[1:])] + parts[1:]
        for index, column, text in parts:
            close = _closing_quote(text, value[0])
            pieces.append((index, column, text if close is None else text[:close]))
            if close is not None:
                break
    else:
        for index, column, text in parts:
            comment = YAML_COMMENT.search(text)
            pieces.append((index, column, text if comment is None else text[:comment.start()]))
            if comment is not None:
                break
    return [piece for piece in pieces if piece[2].strip()]


def _front_matter(text):
    """Find a leading YAML front-matter block.

    Return (text, description): TEXT with the block blanked, so line numbers
    stay true, and the value of its "description:" key as (line index,
    column, text) pieces. The block counts only when its first line that is
    not a comment is a key, and every line is a key, a list item, an indented
    line, a comment or a blank line. Else it is Markdown: a thematic break,
    prose and a second thematic break. Only the description is prose, because
    agents act on it.
    """
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return text, []
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            break
    else:
        return text, []
    body = [line for line in lines[1:end] if line.strip()]
    content = [line for line in body if not line.startswith("#")]
    if (body and (not content or not FRONT_MATTER_KEY.match(content[0]))
            or not all(FRONT_MATTER_LINE.match(line) for line in body)):
        return text, []
    pieces = []
    # "description" in quotes is the same key. The first key counts: a later line that
    # starts with the key can be in a quoted value that goes on over lines.
    for index in range(1, end):
        key = DESCRIPTION_KEY.match(lines[index])
        if key:
            break
    else:
        index = end
    if index < end:
        value = lines[index][key.end():].rstrip()
        parts = [(index, key.end(), value)] if value else []
        for later in range(index + 1, end):
            line = lines[later]
            if line.strip() and line[0] not in " \t":
                break
            lead = len(line) - len(line.lstrip(" \t"))
            if line[lead:].rstrip():
                parts.append((later, lead, line[lead:].rstrip()))
        pieces = _scalar_pieces(value, parts)
    return "\n" * (end + 1) + "\n".join(lines[end + 1:]), pieces


def lint(text, filename="<stdin>"):
    text, description = _front_matter(text)
    findings = []
    words_total = 0
    fence = None
    html_block = None
    html_depth = 0
    in_paragraph = False
    # content indent of the open list item, so its indented lines are not code
    list_indent = 0
    # backtick run length of a code span that is open across lines, or 0
    open_span = 0
    paragraph_depth = 0
    # (line number, column) where a link from an earlier line ends, or None
    link_end = None
    html_containers = []
    lines = text.splitlines()
    table_cells = _markdown_table_cells(lines)
    # first occurrence of each synonym-group member: (group_idx, base) -> (line, col, match)
    seen_synonyms = {}
    # consecutive prose lines form one block, so wrapped sentences count once
    block = []
    blocks = []  # the blocks, read after the last line
    # the paragraph of the current line, where GitHub reads the emphasis runs
    paragraph = 0
    # A line of the open list item starts an HTML block, a heading, a
    # thematic break or a block quote. GitHub ends the list at the next line
    # with less indent, and the main loop can read that line as text of the
    # item or as a line of the same quote. Or the main loop ends the list at an
    # indented line that GitHub keeps in an item.
    unsure_list = False
    list_depth = 0  # the quote depth of the open list item
    unquoted = ""  # the line before, after its quote prefix
    in_quote = False
    after_boundary = True

    # the end index and backtick run index of the paragraph that holds the current line
    span_end, span_runs = -1, {}

    def flush():
        if block:
            blocks.append(block[:])
        block.clear()

    def check(lineno, segment, source_column, line, skip, is_table,
              add_to_block=True, hidden=(), wraps=False, unsure=False):
        nonlocal words_total
        words_total += len(line.split())
        for rule_id, level, pattern, msg in RULES:
            for m in pattern.finditer(line):
                # the modal may end the line before: "may" / "have failed"
                before = (block[-1][2] + " " if block else "") + line[skip:m.start()]
                if rule_id == "present-perfect" and MODAL_PERFECT_PREFIX.search(before):
                    continue
                findings.append({"file": filename, "line": lineno,
                                 "col": source_column + m.start() + 1,
                                 "rule": rule_id, "level": level,
                                 "match": m.group(0), "message": msg})
        for gi, group in enumerate(SYNONYM_GROUPS):
            for base in group:
                if (gi, base) in seen_synonyms:
                    continue
                m = _word_re(base).search(line)
                if m:
                    seen_synonyms[(gi, base)] = (
                        lineno, source_column + m.start() + 1, m.group(0)
                    )
        # This flag affects sentence blocks only; rule checks still scan the line.
        if add_to_block and line[skip:].strip():
            block.append((lineno, source_column + skip, line[skip:],
                          _emphasis_view(segment, line, hidden)[skip:], paragraph, wraps, unsure))

    # The description in the front matter is one paragraph of prose.
    span = 0
    values = [piece[2] for piece in description]
    last_piece = {}  # the last piece with a run of each length
    for piece_index, piece_value in enumerate(values):
        for m in BACKTICK_RUN.finditer(piece_value):
            last_piece[len(m.group())] = piece_index
    piece_end = None  # (piece, column) where a link from an earlier piece ends
    piece_brackets = [[], 0]
    piece_depth = 0  # the "[" marks still open, for the GFM autolinks
    for position, (index, column, value) in enumerate(description):
        skip = 0
        if piece_end and piece_end[0] > position:
            skip = len(value)  # the whole piece is in the title of a link
        elif piece_end and piece_end[0] == position:
            skip = piece_end[1]
        carry, hidden = [], []
        masked, span = _mask_code_spans(value, span, lambda run: last_piece.get(run, -1) > position, values, position + 1,
                                        0, skip, carry, piece_brackets, hidden)
        if carry:
            piece_end = (position + carry[0], carry[1])
        elif piece_end and piece_end[0] <= position:
            piece_end = None
        line = _mask_non_prose(masked, hidden)
        piece_depth = _gfm_autolinks(value, line, 0, piece_depth, hidden)
        check(index + 1, value, column, line, 0, False, hidden=hidden,
              wraps=_html_item_wraps(value, line, hidden, 0))
    flush()
    def closes_later(run):
        """True when a run of length RUN closes a span on a later line of this paragraph."""
        nonlocal span_end, span_runs
        if not in_paragraph:
            return False
        if lineno > span_end:
            span_end, span_runs = _paragraph_runs(lines, lineno, paragraph_depth, list_indent)
        return span_runs.get(run, -1) >= lineno

    for lineno, raw_line in enumerate(lines, 1):
        was_paragraph = in_paragraph
        new_paragraph = not was_paragraph or _breaks_paragraph(paragraph_depth, raw_line, list_indent)
        if new_paragraph:
            paragraph += 1
            open_span = 0
            open_brackets = [[], 0]  # the "[" marks that can open link text
            link_depth = 0  # the "[" marks still open, for the GFM autolinks
        if _fence_ends_with_quote(fence, raw_line):
            # The quote that holds the fence ended: judge this line as any other line.
            fence = None
        in_html = False
        if fence is None:
            # An HTML block can sit in a block quote. It ends when its quote ends. An
            # open block strips only its own ">" levels: a deeper ">" is its text.
            if html_block is not None:
                line_depth, line_unquoted = _strip_quotes(raw_line.expandtabs(4), html_depth)
                if line_depth < html_depth:
                    html_block = None
            if html_block is None:
                line_depth, line_unquoted = _strip_quotes(raw_line.expandtabs(4))
            # A deeper quote starts a block quote, which a paragraph outside it does not continue.
            continues = in_paragraph and line_depth <= paragraph_depth
            was_html = html_block is not None
            in_html, html_block = _html_block_step(html_block, line_unquoted, continues)
            if in_html and not was_html:
                html_depth = line_depth
        if in_html:
            # An HTML block holds literal text until it ends, so no fence opens in it.
            is_fence = False
        else:
            is_fence, fence = _fence_step(fence, raw_line)
        after_blank = not unquoted.strip()  # the line before is blank or a quote marker only
        # A paragraph is open after a line of text that no other block takes.
        # The paragraph state reads the line after its quote prefix, so a line with only
        # quote markers is blank inside its quote.
        depth, unquoted = _strip_quotes(raw_line.expandtabs(4))
        prev_depth = paragraph_depth
        # an underline left of the open item's content is a lazy line, not an underline
        underline = (in_paragraph and depth == paragraph_depth
                     and _indent_width(unquoted) >= list_indent
                     and SETEXT_UNDERLINE.match(unquoted))
        in_paragraph = bool(unquoted.strip() and not in_html and not is_fence and not fence
                            and not NO_PARAGRAPH.match(unquoted) and not underline)
        if not in_paragraph:
            paragraph_depth = 0
        elif (not was_paragraph or depth > paragraph_depth
              or (depth < paragraph_depth
                  and _breaks_paragraph(paragraph_depth, raw_line, list_indent))):
            paragraph_depth = depth
        # A lazy line with fewer ">" keeps the depth of the paragraph. A list item
        # with fewer ">" is no lazy line: it ends the quote and starts a paragraph.
        if is_fence:
            flush()
            # A fence inside a quote does not start the quote: an alert marker after it is text.
            after_boundary = _strip_quotes(raw_line)[0] == 0
            continue
        if fence:
            continue
        # CommonMark 4.4: an indented code block. It cannot interrupt a paragraph.
        rest = _strip_quotes(raw_line.expandtabs(4))[1]
        indent = _indent_width(rest)
        # The indent at the quote depth of the list: it is before a deeper ">".
        lead = _indent_width(_strip_quotes(raw_line.expandtabs(4), list_depth)[1])
        if unsure_list and not list_indent and after_blank and rest.strip() and not lead:
            unsure_list = False  # after a blank line, a line without indent is in no item
        # The line that ends the list is unsure too, unless a blank line ends it.
        unsure = unsure_list and not after_blank
        if rest.strip() and not in_html:
            if indent >= list_indent + 4:
                if not was_paragraph:
                    in_paragraph = False
                    continue
            else:
                # An item line sets the content indent also after a text line or
                # in a tight list. A lazy line does not end the item.
                item = _list_item(rest, list_indent, was_paragraph and depth == prev_depth)
                if item:
                    list_indent = len(item.group(0)) if item.group(3) else len(item.group(0)) + 1
                    list_depth = depth
                elif indent < list_indent and not (was_paragraph and in_paragraph):
                    # only a lazy text line keeps the item open, not a heading or a break
                    list_indent = 0
                    # An indented line can be in an outer item, and a ">" with an indent
                    # can start a block quote in the item: GitHub reads the list on.
                    unsure_list = lead > 0
        item_text = rest[ITEM_PREFIX.match(rest).end():]
        if (list_indent and indent < list_indent + 4
                and (depth > list_depth or item_text.startswith(">") or NO_PARAGRAPH.match(item_text)
                     or HTML_TYPE7.match(item_text) or any(start.match(item_text) for start, _ in HTML_BLOCK_KINDS))):
            unsure_list = True
        if HTML_BLOCK_TAG.match(raw_line.lstrip()):
            for tag in HTML_BLOCK_TAG.finditer(_mask_inline_code(raw_line)):
                name = tag.group(2).lower()
                if tag.group(1):
                    if name in html_containers:
                        while html_containers:
                            if html_containers.pop() == name:
                                break
                elif not tag.group().endswith("/>"):
                    html_containers.append(name)
        segments = table_cells.get(lineno - 1, [(raw_line, 0)])
        is_table = (lineno - 1) in table_cells
        quote = BLOCKQUOTE_PREFIX.match(raw_line)
        is_quote = bool(quote)
        # judge block boundaries on the text inside any blockquote prefix
        content = raw_line[quote.end():] if quote else raw_line
        # a GitHub alert marker is a label that stands alone, as a heading does.
        # Accept it only in an unindented quote of one level after a blank line,
        # a fence, or at the start of the text. Elsewhere a list item or a lazy
        # continuation line can hold the quote, and GitHub shows the marker as
        # text. Markers inside HTML containers are also plain text.
        alert = (not html_containers and raw_line.startswith(">") and after_boundary
                 and quote.group().count(">") == 1
                 and GITHUB_ALERT.fullmatch(content.strip()))
        admonition_title = bool(ADMONITION_TITLE.match(content))
        standalone = STANDALONE_LINE.match(content) or admonition_title or alert
        if (is_table or not content.strip() or standalone
                or ANY_LIST_ITEM.match(content) or is_quote != in_quote
                # a deeper quote starts a new paragraph, so the text before it is no context
                or depth > prev_depth):
            flush()
        in_quote = is_quote
        after_boundary = not raw_line.strip()
        for segment, source_column in segments:
            if is_table:
                paragraph += 1  # a table cell is a paragraph of its own
            hidden = []  # the underscore fills and the autolinks, for the emphasis view
            if in_html:
                # an HTML block has no Markdown links; backtick pairs stay blanked
                line = _mask_non_prose(_mask_inline_code(segment), hidden)
            elif is_table:
                # a table cell holds its own spans and links
                line = _mask_non_prose(_mask_code_spans(segment, 0, lambda run: False, hidden=hidden)[0],
                                       hidden)
            else:
                skip = 0
                if link_end and link_end[0] > lineno:
                    skip = len(segment)  # the whole line is in the title of a link
                elif link_end and link_end[0] == lineno:
                    skip = link_end[1]
                carry = []
                masked, open_span = _mask_code_spans(segment, open_span, closes_later, lines, lineno,
                                                     paragraph_depth if in_paragraph else None,
                                                     skip, carry, open_brackets, hidden)
                if carry:
                    link_end = (lineno + carry[0], carry[1])
                elif link_end and link_end[0] <= lineno:
                    link_end = None
                line = _mask_non_prose(masked, hidden)
            # The blockquote prefix and list marker are markup.
            skip = quote.end() if quote and not is_table else 0
            marker = None if is_table else ANY_LIST_ITEM.match(segment[skip:])
            if marker:
                skip += marker.end()
            if in_html or is_table:
                _gfm_autolinks(segment, line, skip, 0, hidden)
            else:
                link_depth = _gfm_autolinks(segment, line, skip, link_depth, hidden)
            check(
                lineno, segment, source_column, line, skip, is_table,
                add_to_block=not admonition_title, hidden=hidden,
                wraps=not (in_html or is_table) and _html_item_wraps(segment, line, hidden, skip),
                unsure=unsure or unsure_list,
            )
            if is_table:
                flush()  # each table cell is its own block
        if is_table:
            paragraph += 1  # a line after the table starts a paragraph
        if standalone:
            flush()
    flush()
    for prose, emphasis in zip(blocks, _block_emphasis(blocks)):
        findings.extend(_long_sentence_findings(prose, filename, emphasis))
    # synonym rotation: flag each member after the first, at its first occurrence
    for gi, group in enumerate(SYNONYM_GROUPS):
        present = [(seen_synonyms[(gi, b)], b) for b in group if (gi, b) in seen_synonyms]
        if len(present) > 1:
            present.sort()  # document order
            first_base = present[0][1]
            for (lineno, col, match), base in present[1:]:
                findings.append({"file": filename, "line": lineno, "col": col,
                                 "rule": "synonym-rotation", "level": "advisory-free",
                                 "match": match,
                                 "message": f"'{base}' and '{first_base}' name the same action. Pick one and use it every time."})
    findings.extend(_dangling_conjunction_findings(text, filename))
    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings, words_total


def report(findings, words_total, as_json, hard_count, baseline):
    rate = round(len(findings) * 100 / words_total, 1) if words_total else 0.0
    if as_json:
        print(json.dumps({"violations": findings, "count": len(findings),
                          "hard_count": hard_count, "baseline": baseline,
                          "words": words_total, "per_100_words": rate}, indent=2))
        return
    for f in findings:
        print(f"{f['file']}:{f['line']}:{f['col']} {f['rule']}: {f['message']} [{f['match']}]")
    print(f"\n{len(findings)} violations ({hard_count} hard, baseline {baseline}), "
          f"{words_total} words, {rate} per 100 words")
    print("Hedges/modality (may, might, could) are never flagged: confidence is content.")


def selftest():
    bad = ("The panel is removed; spin up the job. "
           "Perform an analysis of the seamless log. "
           "We have received the report.")
    bad_findings, _ = lint(bad)
    rules = {f["rule"] for f in bad_findings}
    for expected in ("semicolon", "phrasal-verb", "nominalization",
                     "marketing-adjective", "passive-voice", "present-perfect"):
        assert expected in rules, (expected, bad_findings)

    # MkDocs admonition title variants, including multiple classes and no space.
    for title in (
        "!!! note",
        "!!!note",
        "!!! info inline end \"Title\"",
        "!!! danger highlight blink \"Title\"",
        "??? note",
        "???+ note",
        '!!! note "Quoted title"',
    ):
        assert ADMONITION_TITLE.fullmatch(title), title
    for title in ("!!!+ note", "!!!+note"):
        assert not ADMONITION_TITLE.fullmatch(title), title

    # Long admonition titles are headings, not prose sentences.
    long_title = '!!! note "' + " ".join(["title"] * 30) + '"'
    findings, _ = lint(long_title)
    assert not any(f["rule"] == "long-sentence" for f in findings), findings

    # A standalone title does not join the four-space-indented body sentence.
    body = " ".join(["word"] * 26) + "."
    findings, _ = lint('!!! note "Title"\n    ' + body)
    long_sentences = [
        f for f in findings if f["rule"] == "long-sentence"
    ]
    assert len(long_sentences) == 1, findings
    assert long_sentences[0]["match"] == "26 words", findings

    # A four-space-indented title inside a list item is also standalone.
    list_title = '!!! info inline end "' + " ".join(["title"] * 30) + '"'
    findings, _ = lint("- item\n    " + list_title + "\n        " + body)
    long_sentences = [
        f for f in findings if f["rule"] == "long-sentence"
    ]
    assert len(long_sentences) == 1, findings
    assert long_sentences[0]["line"] == 3, findings
    assert long_sentences[0]["match"] == "26 words", findings

    # A long whitespace-only title candidate must fail quickly.
    assert not ADMONITION_TITLE.fullmatch("!!!" + " " * 32000)
    # Many class words followed by a broken title must also fail without backtracking.
    assert not ADMONITION_TITLE.fullmatch("!!! " + "info " * 16000 + '"')
    # hedges must never be flagged, including modal + perfect infinitive
    findings, _ = lint("The request may have failed. It could be a timeout. "
                       "The disk might have filled.")
    assert findings == [], findings
    # irregular participles: "has run" is a compound tense as much as "has failed"
    findings, _ = lint("The task has run. The job has set the flag. We have begun.")
    assert sum(1 for f in findings if f["rule"] == "present-perfect") == 3, findings
    findings, _ = lint("The job may have run.")
    assert not any(f["rule"] == "present-perfect" for f in findings), findings
    # Modal perfects remain protected across negation and variable whitespace.
    for modal in ("may", "might", "could", "should", "would", "must"):
        for gap in (" ", "  ", "\t", " not "):
            findings, _ = lint(f"The task {modal}{gap}have run.")
            assert not any(f["rule"] == "present-perfect" for f in findings), findings
    findings, _ = lint("The task couldn't have run. The task MAY NOT HAVE RUN.")
    assert not any(f["rule"] == "present-perfect" for f in findings), findings
    findings, _ = lint("It might already have finished. It could not possibly have run. "
                       "It may never have started. It should probably have stopped.")
    assert not any(f["rule"] == "present-perfect" for f in findings), findings
    findings, _ = lint("It cannot have run. It won't have finished. It can't have stopped. "
                       "It may well have failed. It may very well have failed.\n\n"
                       "The request may\nhave failed.")
    assert not any(f["rule"] == "present-perfect" for f in findings), findings
    # a modal in an earlier paragraph does not protect the next one
    findings, _ = lint("It may\n\nhave failed.")
    assert sum(f["rule"] == "present-perfect" for f in findings) == 1, findings
    # the quote prefix and the list marker are markup: a modal at the end of the
    # line before still protects the perfect, also in a quote and in a list
    for text in ("> It may\n> have failed.", "> > It may\n> > have failed.",
                 "It may\nhave failed.", "- It may\n  have run.", "> - It may\n>   have run."):
        findings, _ = lint(text)
        assert not any(f["rule"] == "present-perfect" for f in findings), (text, findings)
    for text in ("> It may\n>\n> have failed.", "> It may\n>> have failed."):
        findings, _ = lint(text)
        perfect_lines = [f["line"] for f in findings if f["rule"] == "present-perfect"]
        assert perfect_lines == [text.count("\n") + 1], (text, findings)
    # an adverb without a modal is not a hedge
    findings, _ = lint("The task already has run. They probably have finished.")
    assert sum(f["rule"] == "present-perfect" for f in findings) == 2, findings
    findings, _ = lint("The task has run. We have begun. The flag is set.")
    assert sum(f["rule"] == "present-perfect" for f in findings) == 2, findings
    assert any(f["rule"] == "passive-voice" for f in findings), findings
    findings, _ = lint("The task is gone.")
    assert not any(f["rule"] == "passive-voice" for f in findings), findings
    # code blocks skipped
    findings, _ = lint("```\nx = a; y = b\n```")
    assert findings == []
    # a fence closes only on the same character, at least as long, with nothing after it
    for text in ("````md\n```\n````\n\nProse; here.",
                 "```\n~~~\n```\n\nProse; here.",
                 "~~~~\n~~~\n~~~~\n\nProse; here."):
        findings, _ = lint(text)
        assert [f["rule"] for f in findings] == ["semicolon"], (text, findings)
    findings, _ = lint("```\n```sh\nx = a; y = b\n```")
    assert findings == [], findings
    # a fence inside a blockquote is a fence
    findings, _ = lint("Text.\n\n> ```\n> x = a; y = b\n> ```\n\nProse; here.")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 7)], findings
    # the dangling-conjunction rule uses the same fence state
    findings, _ = lint("````md\n```\n- Do this and\n````")
    assert findings == [], findings
    findings, _ = lint("- Do this\n  ````md\n  ```\n  code and\n  ````\n- Do that")
    assert findings == [], findings
    # it tracks HTML blocks: there no fence opens and no list item starts
    for text, lines in (("<div>\n```\n</div>\n\n- Open the valve and\n", [5]),
                        ("<!--\n```\n-->\n- Open the valve and\n", [4]),
                        ("<div>\n- Open the valve and\n</div>\n", []),
                        ("- x\n<div>\n- y and\n", []),
                        # an HTML block in an item, also on the line of the marker
                        ("- Open the valve\n\n  <div>\n  ```\n  </div>\n\n- Close it and\n", [7]),
                        ("- x\n  - y\n  <div>\n  ```\n  </div>\n\n- z and\n", [7]),
                        ("- <pre>\n  ```\n  </pre>\n- y and\n", [4]),
                        # a line with less indent ends the item, and the HTML block in it
                        ("- x\n  <div>\n- y and\n", [3]),
                        ("- <pre>\n```\n- y and\n```\n", []),
                        ("- a\n  - b\n  <div>\n- c and\n", [4]),
                        # the lines in a <pre> block or a comment are no item text, and no
                        # item starts there; GitHub hides the text after an open comment
                        ("- Close it\n  <pre>\n  ```\n  - Step and\n- Next\n", []),
                        ("- a\n  <!--\n  x\n- b and\n", []),
                        ("- a\n  <?php\n  x and\n- b\n", []),
                        # an open comment joins the next items up to "-->"
                        ("- Run tests and\n  <!-- pending\n- Next:\n  <!-- closes -->\n  finish the checklist.\n", []),
                        ("- Run tests and\n  <!-- pending\n- Next\n", [1]),
                        # also the first line of such a block, when the block stays open
                        ("- Change summary:\n  <!-- Explain the change and\n  include test results.\n", []),
                        ("- <pre>Expected an expression after and\n  at parser.py:12\n", []),
                        ("- Fix it\n  <!-- old -->\n  <pre>a</pre> and\n", [3]),
                        # GitHub shows the text of a <script> block: it escapes the tag
                        ("- a\n  <script>\n  x and\n- b\n", [3]),
                        ("- a\n  <!--\n- b and\n\n<div>\n-->\n</div>\n\n- c and\n", [9]),
                        # in an item, the text of a <div> block is item text: a list marker
                        # there starts an item, as before
                        ("- <div>\n  ```\n  - Step and\n- Next\n", [3]),
                        ("- a\n  - b\n  <div>\n  - c and\n  </div>\n", [4]),
                        ("  <!--\n  ```\n- Open it and\n", []),
                        # one tag alone after a text line continues the paragraph, so the
                        # fence after it opens
                        ("Text\n<span>\n```\n```\n- a and\n", [5]),
                        ("- x\n  <span>\n  ```\n  - y and\n  ```\n", []),
                        # a no-break space is no whitespace in a tag
                        ("<div\u00a0class=\"note\">\n- Next and\n", [2]),
                        ("<br/>\u00a0\n- Next and\n", [2]),
                        # a line with a no-break space is text, also after "#"
                        ("#\u00a0Notes\n<img src=\"a.png\">\n- Run checks and\n", [3]),
                        ("Text\n\u00a0\n<img src=\"a.png\">\n- Run checks and\n", [4]),
                        # a line with only ">" ends the paragraph, and a heading in a quote too
                        (">\n<img src=\"a.png\">\n- Run checks and\n", []),
                        ("> # Head\n<img src=\"a.png\">\n- Run checks and\n", []),
                        # a tag alone interrupts a paragraph of a quote or of an item that
                        # the line is not in, as in cmark-gfm
                        ("> Note\n<img src=\"a.png\">\n- Run checks and\n", []),
                        ("- a\n<span>\n- b and\n", []),
                        ("- a\nlazy\n<span>\n- b and\n", []),
                        ("- a\n  - b\n  text\n  <span>\n  ```\n  ```\n- c and\n", [7]),
                        ("- a\n  - b\n\n  text\n  <span>\n  ```\n  ```\n- c and\n", [8]),
                        # "2." cannot interrupt a paragraph, so the tag line is paragraph text
                        ("Text\n2. Example\n<br>\n- Open the valve and\n", [4]),
                        ("- a\n  Text\n  2. Example\n  <br>\n- Open the valve and\n", [5]),
                        ("Text\n1. Example\n<br>\n- Open the valve and\n", []),
                        ("Screenshot:\n2. <img src=\"example.png\">\n<br>\n- Run tests and\n", [4]),
                        ("Text\n2. # Heading\n<br>\n- Run tests and\n", [4]),
                        # an empty item cannot interrupt a paragraph; an empty "-" is a setext underline
                        ("Text\n1. \n<br>\n- Run tests and\n", [4]),
                        ("Text\n* \n<br>\n- Run tests and\n", [4]),
                        ("Text\n- \n<br>\n- Run tests and\n", []),
                        # its lines are paragraph text: no HTML block starts in them
                        ("Example:\n2. Steps\n   <details>\n   ```markdown\n- Run tests and\n   ```\n"
                         "   </details>\n", []),
                        ("Text\n2. Steps and\n   <details>\n", []),
                        ("Text\n2. Steps\n    <details>\n- Run tests and\n", [4]),
                        # a setext underline ends the paragraph, so "2." starts a list
                        ("Setup\n=====\n2. Install\n   - Linux\n   <div>Note</div>\n- Run tests and\n", [6]),
                        # a lazy underline is text, and "<br>" after the "2." item is a block
                        ("- Setup\n=====\n2. Install\n<br>\n- Run tests and\n", []),
                        # an HTML block in an item goes on after a list marker in it
                        ("- <div>\n  ~~~\n  - Note\n  ~~~\n  </div>\n\n- Open the valve and\n", [7]),
                        ("-     code\n  <div>Note</div>\n- Open the valve and\n", [3]),
                        ("1. <details>\n   ~~~\n   - Linux\n   ~~~\n   </details>\n\n2. Run tests and\n", [7]),
                        ("- <div>\n  - Note\n\n  ~~~\n  - x and\n  ~~~\n- y and\n", [7]),
                        ("- <div>\n  ~~~\n  - Note\n    ~~~\n  </div>\n\n- Open the valve and\n", [7]),
                        # a block starts at the indent of the item that holds the line
                        ("- Example:\n  - Linux\n  <div>\n  ~~~\n  </div>\n\n    <div>\n    ~~~\n    </div>\n\n"
                         "- Run tests and\n", [11]),
                        # after the block, the lines are in the item that held the block
                        ("- <div>\n  ~~~\n  - Note\n  </div>\n\n    <div>\n  ~~~\n    </div>\n\n- Run tests and\n",
                         [10]),
                        ("- <div>\n  ~~~\n  - Note\n\n    <div>\n  ~~~\n    </div>\n\n- Run tests and\n", [9]),
                        # a list marker on the line that ends the block is text of the block
                        ("- <textarea>\n  ~~~\n  - Note </textarea>\n\n    <div>\n  ~~~\n    </div>\n\n"
                         "- Run tests and\n", [9]),
                        ("- <pre>\n  ~~~\n  - Note </pre>\n\n    <div>\n  ~~~\n    </div>\n\n- Run tests and\n", [9]),
                        # after five or more spaces, or in an empty item, the content of the item
                        # starts one column after the marker, so the HTML block is in the item
                        ("1.      code\n   <div>Note</div>\n2. Open the valve and\n", [3]),
                        ("-   \n  <div>Note</div>\n- Open the valve and\n", [3]),
                        ("-   \tcode\n  <div>Note</div>\n- Run tests and\n", [3]),
                        # a tab after the marker starts an item that can hold an HTML block
                        ("-\t# Heading\n  Text\n    <!--\n- Run tests and\n", [4]),
                        ("- # H\n  Text\n    <!--\n- Run tests and\n", []),
                        ("- Intro\n  Text\n    <!--\n- Run tests and\n", []),
                        ("-\t\tcode\n  <div>Note</div>\n- Run tests and\n", [3]),
                        ("-\t\n-\t\n  <div>\n- Run tests and\n", [4]),
                        # indented code after the marker is no paragraph
                        ("  - \tcode\n  -->\n  <br>\n- Run tests and\n", [4]),
                        # an HTML block on the line of a marker with a tab is in that item
                        ("-\t<!--\n    <div>Example</div>\n    ~~~text\n\n    ~~~\n    -->\n- Run tests and\n", [7]),
                        ("- Parent\n  -\t<!--\n    <div>Example</div>\n    ~~~text\n\n    ~~~\n    -->\n- Run tests and\n", [8]),
                        ("- Parent\n  -\t<pre>\n    <div>Example</div>\n    ~~~text\n\n    ~~~\n    </pre>\n- Run tests and\n", [8]),
                        ("- Parent\n  -\t<!--\n    note\n    -->\n  Finish and\n", [5]),
                        ("- Parent\n  -\t<!--\n    ~~~\n    -->\n      <div>\n      ~~~\n      </div>\n- Run tests and\n", [8]),
                        ("- Parent\n  -\t<pre>\n    </pre>\n      <div>\n      ~~~\n      </div>\n- Run tests and\n", [7]),
                        ("- Parent\n  -\tExample\n    <!--\n    ~~~\n    -->\n      <div>\n      ~~~\n      </div>\n- Run tests and\n", [9]),
                        # a fence on a marker line holds code up to its end or the end of the item
                        ("- ~~~\n  <!--\n- Run tests and\n", [3]),
                        ("- ```html\n  <pre>\n  ```\n- Run tests and\n", [4]),
                        ("- Parent\n  -\t~~~\n    <!--\n- Run tests and\n", [4]),
                        ("- Parent\n  Text\n  -\t~~~\n      <!--\n- Run tests and\n", [5]),
                        # the line that opens such a fence is no item text, the item can close
                        # it, and after it a fence in a list item ends with its item
                        ("- ~~~ and\n  </div>\nText and\n", []),
                        ("- ~~~\n  ~~~\n  - Note and\n", [3]),
                        ("- ```\n  code\n  ```\n\n  ```\n  more\n\n- Run tests and\n", [8]),
                        ("-\t~~~\n    code\n    ~~~\n    ~~~\n    more\n- Run tests and\n", [6]),
                        ("- Parent\n  -\t~~~\n      code\n      ~~~\n  ~~~\n  more\n- Run tests and\n", [7]),
                        # a tab in the gap goes to the next tab stop, also for such a fence
                        ("- \t~~~\n  - Run tests and\n", [2]),
                        ("- \t\t~~~\n  - Run tests and\n", [2]),
                        # indented code after the marker is no item text
                        ("-     Step and\n- Run tests\n", []),
                        # an empty item holds its lines from one column after the marker,
                        # and a tab in the gap goes to the next tab stop, also for a later fence
                        ("- ```\n  ```\n\n-   \n    ~~~\n  - Run tests and\n  ~~~\n", []),
                        ("- ~~~\n  ~~~\n\n- \tStep\n    ~~~\n  - Run tests and\n", [6]),
                        ("- ```\n  ```\n\n- \tcode\n   ~~~\n- Run tests and\n", []),
                        # an empty item ends at a blank line after its marker, also after a tab
                        ("-   \n\n  <div>\n- Run tests and\n", []),
                        ("-\t\n\n  <div>\n- Run tests and\n", []),
                        # in an HTML block, and in a paragraph of an item, the body of a
                        # marker after five or more columns is text
                        ("- <div>\n  -     Run tests and\n  </div>\n", [2]),
                        ("- Text\n  2.     Step and\n", [2]),
                        # an empty "-" item after a paragraph is a setext underline
                        ("Heading\n-   \n  <div>\n- Run tests and\n", []),
                        ("Heading\n-  \t\n  <div>\n- Run tests and\n", []),
                        # after indented code with a tab in the gap, a line with four or more
                        # columns more than one column after the marker is code, not HTML
                        ("-   \tcode\n      <custom>\n    ~~~\n  - Run tests and\n    ~~~\n", []),
                        ("-   \tcode\n      <!--\n- Run tests and\n", [3]),
                        # elsewhere the item starts an HTML block from its content indent,
                        # also after a fence on the marker line and after a block ends
                        ("- \t~~~\n    ~~~\n      <!--\n    ~~~\n      -->\n    ~~~\n"
                         "    command and\n    ~~~\n", []),
                        ("- <div>\n  ~~~\n  - Note</div>\n\n  <!--\n  ~~~\n  -->\n- Run tests and\n",
                         [8]),
                        # a nested empty item with a tab or with nothing after the marker,
                        # and a nested item with indented code after a tab, hold a fence from
                        # one column after the marker, so the fence ends with the item
                        ("- ~~~\n  ~~~\n  -\t\n    ~~~\n  - Run tests and\n", [5]),
                        ("- ~~~\n  ~~~\n  -\t\tcode\n    ~~~\n  - Run tests and\n", [5]),
                        ("- ~~~\n  ~~~\n  1.\n     ~~~\n  - Run tests and\n", [5]),
                        ("- ~~~\n  ~~~\n  -\n  -\n    ~~~\n  - Run tests and\n", [6]),
                        # an empty item ends at a blank line, and it cannot interrupt a
                        # paragraph: the fence is in the outer item
                        ("- ~~~\n  ~~~\n  -\t\n\n    ~~~\n  - Run tests and\n", []),
                        ("- ~~~\n  ~~~\n  text\n  *\n    ~~~\n  - Run tests and\n", []),
                        # after a nested item, also after a lazy line of its paragraph, the
                        # item holds no paragraph of its own, so an empty item starts there
                        ("- ~~~\n  ~~~\n  -\tStep\n  -\n    ~~~\n  - Run tests and\n", [6]),
                        ("- ~~~\n  ~~~\n  -\tStep\n  more\n  -\n    ~~~\n  - Run tests and\n", [7]),
                        ("- ~~~\n  ~~~\n  -\t\tcode\n      more\n  -\n    ~~~\n  - Run tests and\n",
                         [7]),
                        # text after indented code is a paragraph of the outer item
                        ("- ~~~\n  ~~~\n  -\t\tcode\n  text\n  -\n    ~~~\n  - Run tests and\n",
                         []),
                        # an empty item with nothing after its marker holds the fence too
                        ("- ~~~\n  ~~~\n-\n  ~~~\n- Run tests and\n", [5]),
                        ("- ~~~\n  ~~~\n*\n  ~~~\n- Run tests and\n", [5]),
                        # "<br>" after an item starts an HTML block outside the list
                        ("-\tText\n<br>\n- Run tests and\n", [])):
        findings, _ = lint(text)
        assert [f["line"] for f in findings if f["rule"] == "dangling-conjunction"] == lines, (text, findings)
    # a quoted fence ends with its quote, and a deeper ">" in a fence is code
    for text, lines in (("> ```\n> code\n\nProse; here.", [4]),
                        ("```\n> ```\nx; y\n```\n\nProse; here.", [6]),
                        (">  > ```\n>  > x; y\n>  > ```\n\nProse; here.", [5]),
                        ("> ```\n>     ```\n> x; y\n> ```\n\nProse; here.", [6]),
                        ("```foo`bar\nProse; here.", [2]),
                        ("```\nx; y\n```` \t\n\nProse; here.", [5])):
        findings, _ = lint(text)
        assert [f["line"] for f in findings if f["rule"] == "semicolon"] == lines, (text, findings)
    # the end of a quoted fence in a list item does not join the next line to the item
    findings, _ = lint("- Item\n  > ```\n  > code\nProse and")
    assert findings == [], findings
    # a tab is indent up to the next tab stop of 4, from its real column, also after ">"
    for text, line in (("\t```\n\tx = 1\n\t```\n\nProse; here.", 5),
                       ("```\nx\n\t```\ny; z\n```\n\nProse; here.", 7),
                       ("> ```\n> x\n>\t```\n> Use a; b.", 4),
                       ("> ```\n> x\n>  \t```\n> Use a; b.", 4),
                       (">\t> ```\n>\t> x; y\n>\t> ```\n\nProse; here.", 5),
                       ("- Item\n  ```\n\t```\n\nProse; here.", 5)):
        findings, _ = lint(text)
        assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", line)], (text, findings)
    # a tab-indented fence stays in its list item
    findings, _ = lint("- Run the build and\n\t```\n\tmake\n\t```\n  check the log.")
    assert findings == [], findings
    # a ">" line in an HTML block is text, not a quoted fence. A blank line ends a
    # block that starts with a tag, and a quoted fence after it is a fence.
    for text, lines in (("<div>\n> ```\n> Prose; here.\n> ```\n</div>", [3]),
                        ("<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [3]),
                        ("<!--\n> ```\n> Prose; here.\n> ```\n-->", [3]),
                        ("<div>\n\n> ```\n> x; y\n> ```\n\nProse; here.", [7]),
                        ("<details>\n\n> ```\n> a; b\n> ```\n\n</details>\n\nProse; here.", [9]),
                        ("<pre>\n> ```\n> Prose; here.\n> ```\n</pre>", [3]),
                        ("<?php\n> ```\n> Prose; here.\n> ```\n?>", [3]),
                        ("<![CDATA[\n> ```\n> Prose; here.\n> ```\n]]>", [3]),
                        # inline HTML is no HTML block: the quoted fence after it is a fence
                        ("<span>Label</span>\n> ```\n> a; b\n> ```", []),
                        ("<kbd>Enter</kbd> starts the job.\n> ```\n> a; b\n> ```", []),
                        ("Text.\n<custom>\n> ```\n> a; b\n> ```", []),
                        # a type 7 tag after a heading or a fence starts a block
                        ("# Title\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [4]),
                        ("```\nx\n```\n<img src=\"a.png\">\n> ```\n> Prose; here.\n> ```", [6]),
                        # attribute values may hold "<" and ">", an invalid attribute is no tag
                        ('<span title="a > b">\n> ```\n> Prose; here.\n> ```', [3]),
                        ("<custom a=>\n> ```\n> a; b\n> ```", []),
                        # a setext underline, an empty quote line and a thematic break of one
                        # character end a paragraph, so a type 7 tag after them starts a block
                        ("Title\n=====\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [5]),
                        ("> Quote.\n>\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [5]),
                        ("-*-\n<custom>\n> ```\n> a; b\n> ```", []),
                        ("Title\n-\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [5]),
                        ("> Quote.\n> >\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [5]),
                        # an underline with no paragraph, or as a lazy line, is text
                        ("Intro.\n\n==\n<custom>\n> ```\n> a; b\n> ```", []),
                        ("> Title\n===\n<custom>\n> ```\n> a; b\n> ```", []),
                        ("> > Title\n> lazy\n> ===\n<custom>\n> ```\n> a; b\n> ```", []),
                        # a quoted heading or thematic break is no paragraph line
                        ("> # Note\n> ===\n<custom>\n> ```\n> a; b\n> ```", []),
                        ("> Note\n> ***\n<custom>\n> ```\n> Prose; here.\n> ```\n</custom>", [5]),
                        # the line that ends a quoted fence can start an HTML block
                        ("> ```\n> x\n<custom>\n> ```\n> Prose; here.", [5]),
                        # a type 1 name is no type 7 tag
                        ("<pre/>\n> ```\n> a; b\n> ```", []),
                        ("</pre>\n> ```\n> a; b\n> ```", []),
                        ("<pre-x>\n> ```\n> Prose; here.\n> ```", [3]),
                        # no fence opens in an HTML block, also without ">"
                        ("<pre>\n```\nsample\n</pre>\n\nThe paragraph is here; it must be checked.", [6]),
                        ("<div>\n```\n\nProse; here.", [4]),
                        ("<DIV class=x>text\n> ```\n> Prose; here.\n> ```", [3])):
        findings, _ = lint(text)
        assert [f["line"] for f in findings if f["rule"] == "semicolon"] == lines, (text, findings)
    # a fence at column 0 ends a list item
    findings, _ = lint("- Do this and\n```\nx\n```\n  done")
    assert [(f["rule"], f["line"]) for f in findings] == [("dangling-conjunction", 1)], findings
    # a quoted fence also ends on a line with fewer quote levels that is not blank
    for text, line in (("> ```\n> x\nProse; here.", 3), ("> > ```\n> x; y", 2)):
        findings, _ = lint(text)
        assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", line)], (text, findings)
    # a closing fence up to three columns deeper than the opening fence closes it
    findings, _ = lint("```\nx; y\n   ```\n\nProse; here.")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 5)], findings
    # a tilde fence opens with a backtick in its info string
    findings, _ = lint("~~~ a`b\nx; y\n~~~\n\nProse; here.")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 5)], findings
    # an alert marker after a fence in the same quote is text, as GitHub shows it
    body = " ".join(["word"] * 25) + "."
    findings, _ = lint(f"> ```\n> x\n> ```\n> [!NOTE]\n> {body}")
    assert [f["rule"] for f in findings] == ["long-sentence"], findings
    # a quoted fence after a list item does not join the item
    findings, _ = lint("- Do this and\n\n> ```\n> code\n> ```\n  done")
    assert [f["rule"] for f in findings] == ["dangling-conjunction"], findings
    # all supported list markers, case variants, and trailing whitespace
    findings, _ = lint(
        "- Confirm the target and\n"
        "* Record the result OR  \n"
        "+ Close the panel\n"
        "1. Start the task and\n"
        "2) Stop the task OR"
    )
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert len(dangling) == 4, dangling
    assert [f["line"] for f in dangling] == [1, 2, 4, 5], dangling
    assert [f["col"] for f in dangling] == [1, 1, 1, 1], dangling
    assert all(f["level"] == "advisory-free" for f in dangling), dangling

    # valid continuation lines and standalone four-space code are ignored
    findings, _ = lint("  - Confirm the target and\n    record the result.")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Confirm the target and\n\trecord the result.")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings), findings
    findings, _ = lint("- Confirm the target\n  and")
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert len(dangling) == 1 and dangling[0]["line"] == 2, dangling
    assert dangling[0]["col"] == 3, dangling
    findings, _ = lint("    - code and")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("> - Confirm the target and\n> - Record the result or")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Do this and\n~~~\ncode and\n~~~")
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert len(dangling) == 1 and dangling[0]["line"] == 1, dangling
    findings, _ = lint("```text\n- code and\n```")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)

    # one- and three-space markers and ordered continuation width
    findings, _ = lint(" - Start the task and\n   record the result.")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("-  Start the task and\n   record the result.")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("-\tStart the task and")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("   - Start the task and", filename="fixture.md")
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert len(dangling) == 1 and dangling[0]["col"] == 4, dangling
    assert dangling[0]["file"] == "fixture.md"
    assert dangling[0]["match"].endswith("and")
    assert "Complete the item" in dangling[0]["message"]
    findings, _ = lint("100. Start the task and\n  unrelated text")
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert len(dangling) == 1, dangling
    findings, _ = lint("- Start the task and.\n- Stop the task or,")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Start the task and\n\n  record the result.")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Parent item and\n  - Nested item or")
    dangling = [f for f in findings if f["rule"] == "dangling-conjunction"]
    assert [f["line"] for f in dangling] == [1, 2], dangling

    # ordinary prose, inline code, and fenced code are ignored
    findings, _ = lint("The process may include steps and")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Use `and` as a label")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint("- Combine `left` and `right`")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings), findings
    findings, _ = lint("~~~\n- code and\n~~~")
    assert not any(f["rule"] == "dangling-conjunction" for f in findings)
    findings, _ = lint(("word " * 30).strip() + ".")
    assert any(f["rule"] == "long-sentence" for f in findings)
    # Markdown table syntax is layout, not prose. Each cell stays lintable.
    short_cell = " ".join(f"term{number}" for number in range(1, 25)) + "."
    for table in (
            "| Label | Detail |\n"
            "| --- | --- |\n"
            f"| Clear | {short_cell} |",
            "Label | Detail\n"
            "--- | ---\n"
            f"Clear | {short_cell}"):
        findings, words_total = lint(table)
        assert not any(f["rule"] == "long-sentence" for f in findings), findings
        assert words_total == 27, words_total
    # GFM also accepts one-dash separators, one column, and ragged body rows.
    short_row = " ".join(f"term{number}" for number in range(1, 9))
    for table in (
            "| Label | Detail |\n|-|-|\n" + f"| {short_row} | {short_row} |\n" * 5,
            "| Label |\n| --- |\n" + f"| {short_row} |\n" * 8,
            "| Label | Detail |\n| --- | --- |\n| x |\n"
            + f"| {short_row} | {short_row} | extra |\n" * 2):
        findings, _ = lint(table)
        assert not any(f["rule"] == "long-sentence" for f in findings), (table, findings)
    long_cell = " ".join(f"term{number}" for number in range(1, 27)) + "."
    findings, _ = lint(
        "| Label | Detail |\n"
        "| --- | --- |\n"
        f"| Clear | {long_cell} |"
    )
    long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
    assert len(long_sentences) == 1, long_sentences
    assert long_sentences[0]["match"] == "26 words", long_sentences
    # synonym rotation: second member flagged, first named as the keeper
    findings, _ = lint("Check the config file. Then verify the output. Verify twice.")
    rot = [f for f in findings if f["rule"] == "synonym-rotation"]
    assert len(rot) == 1 and "'verify' and 'check'" in rot[0]["message"], rot
    # single consistent term: no flag
    findings, _ = lint("Check the config. Check the output.")
    assert not any(f["rule"] == "synonym-rotation" for f in findings)
    # character references and link targets are markup, not prose
    findings, _ = lint("Press Ctrl&nbsp;C to stop &rarr; &#8594; &#x2192; now. "
                       "See [the docs](https://x.io/a;b) or <https://x.io/a;b>.")
    assert not any(f["rule"] == "semicolon" for f in findings), findings
    findings, _ = lint('See [a](https://x.io/a;b "Title") and [b](<a b;c>) and [c](a(b;c)).')
    assert not any(f["rule"] == "semicolon" for f in findings), findings
    # a reference GitHub does not read as one, or that renders ";", is prose
    for text in ("We closed the Q&As; then we left.", "Use &unknownentity; here.",
                 "Read this&#59; then stop.", "Read this&#x3b; then stop.", "Read&semi; this."):
        findings, _ = lint(text)
        assert [f["rule"] for f in findings] == ["semicolon"], (text, findings)
    # text in parentheses that is no link destination is prose
    findings, _ = lint("Read [this](seamless; now).")
    assert [f["rule"] for f in findings] == ["marketing-adjective", "semicolon"], findings
    for text in ("See [a](b;c d).", "See [a](b(c;d).", "See [a](<b;c).", "See [a](b;c \"t\" x)."):
        findings, _ = lint(text)
        assert [f["rule"] for f in findings] == ["semicolon"], (text, findings)
    # the link can go on in the next lines of its paragraph, and it must close there
    for text, cols in (("See [docs](https://x.io/a;b\n).", []),
                       ("See [a](b;c \"multi\nline title\") now.", []),
                       ("See [a](b;c\n\"title\") now.", []),
                       ("See [a](b;c (paren\ntitle)) now.", []),
                       ("> See [docs](https://x.io/a;b\n> ).", []),
                       ("See [docs](https://x.io/a;b\n\n).", [(1, 26)]),
                       ("See [a](b;c\n\n\"title\") now.", [(1, 10)]),
                       ("See [a](b;c\nnext line) now.", [(1, 10)]),
                       ("See [a](b(c);d \"oops).", [(1, 13)]),
                       ("See [a](b(c);d \"oops).\n\nNext; para.", [(1, 13), (3, 5)]),
                       ("See [a](b;c (paren (no)) now.", [(1, 10)]),
                       # a block that interrupts the paragraph ends the link
                       ("See [a](b;c \"x\n- y\") z.", [(1, 10)]),
                       ("See [a](b;c \"x\n# y\") z.", [(1, 10)]),
                       ("See [a](b;c \"x\n===\") z.", []),
                       ("See [a](b;c \"x\n===\n\") z.", [(1, 10)]),
                       ("See [a](b;c\n> )", [(1, 10)]),
                       ("> See [a](b;c\n)", []),
                       ("See [a](b;c \"x\n2. y\") z.", []),
                       # a backtick in a destination is text, and what starts first wins
                       ("See [a](https://x.io/a;b`c`tail).", []),
                       ("See [x](a`b;c) and `d` e; f.", [(1, 25)]),
                       ("Run `a [b](c;d` now.", []),
                       ("A `` [a](b;c `` d) e; f", [(1, 21)]),
                       ("| A | B |\n|-|-|\n| [a](b;c`d`e) | x |", []),
                       # a lazy line continues the quoted paragraph of the link
                       ("> First line\nSee [a](b;c\n> ) now.", []),
                       # a backtick in a title is text, a code span after the link is a span
                       ("See [a](b \"x`y\") and `z; w` now.", []),
                       # in a table cell the link starts first, and an HTML block has no links
                       ("| A | B |\n|-|-|\n| [a](b`c) d; e` f | x |", [(3, 13)]),
                       ("<div>\nSee [a](b;c) now.\n</div>", [(2, 10)]),
                       # a heading does not go on in the next line
                       ("# See [a](b;c\n) now.", [(1, 12)]),
                       # a title that goes on in the next line holds its backticks there too
                       ("See [a](b \"x\ny`z\") and `w; v` q.", []),
                       ("> See [a](b \"x\n> y\n> `z\") and `w; v` q.", []),
                       ("See [a](b \"x\ny\") a; `b` c", [(2, 6)]),
                       # a backtick that no code span holds is text, also after a link
                       ("See [a](b \"y`z\") ``c ` d`` text; last `.", [(1, 32)]),
                       ("See [a](b \"x\ny`z\") ``c ` d`` text; last `.", [(2, 21)]),
                       ("Run ```a; b```` now.", [(1, 9)]),
                       # "](" and a space start no destination
                       ("]( ;)", [(1, 4)]),
                       ("]( `);`", []),
                       ("`[`]( ;)", [(1, 7)]),
                       ("<aa:;[]( )>", [(1, 5)]),
                       # an escaped backtick is text, and the rest of its run can open a span
                       ("\\```;``", []),
                       ("\\```;```", [(1, 5)]),
                       ("> \\```;``", []),
                       ("| A |\n|-|\n| \\```;`` |", []),
                       # GitHub shows a link title in no text, so it is not prose
                       ("[a](b \"`;`\")", []),
                       ("[a](b \"`\n`;`\")", []),
                       ("[a](b \"`;\")`", []),
                       ("See [a](b \"x; y\") now; stop.", [(1, 22)]),
                       ("See [a](b \"x\ny; z\nw\") now; stop.", [(3, 8)]),
                       # an escaped "]" starts no link, and an autolink that starts first holds its backticks
                       ("[label\\](url \"visible; prose\")", [(1, 22)]),
                       ("[a\\](b;c) d", [(1, 7)]),
                       ("<https://example.com/\\``> visible; prose `.", [(1, 34)]),
                       ("<https://x.io/`a> b; c `.", [(1, 20)]),
                       ("See <https://x.io/a`b> and `c; d` e.", []),
                       ("`a <https://x` b; c>", [(1, 17)]),
                       # "](" is a link only after a "[" of its paragraph that no "]" closed
                       ("](b \";\")", [(1, 6)]),
                       ("](b;c) d", [(1, 4)]),
                       ("](b \"`;`\")", []),
                       ("\\[a](b \";\")", [(1, 9)]),
                       ("[a] ](b \";\")", [(1, 10)]),
                       ("[a](x) ](b \";\")", [(1, 13)]),
                       ("[a <b>](c \";\") d", []),
                       ("[a\n](b \";\")", []),
                       ("> [a\n> ](b \";\")", []),
                       ("- [a\n  ](b \";\")", []),
                       ("[a\n\n](b \";\")", [(3, 6)]),
                       # an image can be in a link; a link in a link is text
                       ("[![x](y)](z \";\")", []),
                       ("![a [b](c) d](e \";\") f", []),
                       ("[a [b](c) d](e \";\") f", [(1, 17)]),
                       # with no destination, the quoted text is the destination: no title
                       ("[]( \"\n;\")", [(2, 1)]),
                       # an autolink or an inline tag starts first; an escaped "<" starts neither
                       ("\\<aa:`>;`", []),
                       ("<aa:[a](b> \";\")", [(1, 13)]),
                       ("<span title=\"`\"> text; `", [(1, 22)]),
                       ("<span title=\"\\``\"> text; `", [(1, 24)]),
                       ("<b title='`'>`c; d`", []),
                       # GitHub shows no attribute of a tag
                       ("x <b a=\"`;`\">", []),
                       ("<a href=\"](x ';')\"> a; b", [(1, 22)]),
                       ("x <b a=\";<b a=\"</b> y", [(1, 9)]),
                       # GitHub shows a tag that its tagfilter escapes as text
                       ("x <title a=\"x;y\"> b", [(1, 14)]),
                       # a comment, a processing instruction, a declaration and CDATA hold their brackets
                       ("[a <!-- ] --> b](c \"d;\")", []),
                       ("[x <!-- [a](b) --> y](c \"d;\")", []),
                       ("[a <? ] ?> b](c \"d;\")", []),
                       ("[a <!X ] > b](c \"d;\")", []),
                       ("[a <![CDATA[ ] ]]> b](c \"d;\")", []),
                       ("x <!-- <a b=\" --> c; <d e=\"> f", [(1, 20)]),
                       ("x <!-- ](a;b) --> y", []),
                       ("x <? a; b ?> y", []),
                       ("x <? a> b; c ?> d", [(1, 10)]),
                       ("x <![CDATA[ a> b; c ]]> d", [(1, 17)])):
        findings, _ = lint(text)
        assert [(f["line"], f["col"]) for f in findings if f["rule"] == "semicolon"] == cols, (text, findings)
    findings, _ = lint("Press [stop](https://x.io); then wait. Use & ; here.")
    assert [f["col"] for f in findings if f["rule"] == "semicolon"] == [27, 46], findings
    # an indented code block is code, also in a quote and under a list item
    def semicolon_lines(text):
        return [f["line"] for f in lint(text)[0] if f["rule"] == "semicolon"]
    assert semicolon_lines("Intro text.\n\n    x = 1; y = 2\n\tz; w") == []
    assert semicolon_lines("> Intro.\n>\n>     x = 1; y = 2") == []
    assert semicolon_lines("- Item.\n\n      x = 1; y = 2") == []
    # it cannot interrupt a paragraph, and a list item's own indent is prose
    assert semicolon_lines("Intro text\n    goes on; here.") == [2]
    assert semicolon_lines("- Item.\n\n    More; text.") == [3]
    assert semicolon_lines("1. Item.\n\n   - Sub.\n\n     More; text.") == [5]
    # the list ends at a line with less indent
    assert semicolon_lines("- Item.\n\nText.\n\n    x; y") == []
    # a list item that follows a text line, or a nested item in a tight list, still
    # sets the content indent, so its indented continuation paragraph is prose
    assert semicolon_lines("Steps to follow:\n- Open the file.\n\n    Then save it; close it.\n") == [4]
    assert semicolon_lines("- Open the file.\n  - Pick a row.\n\n      Then save it; close it.\n") == [4]
    assert semicolon_lines("- Item\ncontinued\n\n    More; text.") == [4]
    assert semicolon_lines("Intro text.\n\n    x = 1; y = 2\n") == []
    assert semicolon_lines("Steps:\n- Open the file.\n\n      x = 1; y = 2\n") == []
    # in a paragraph, only a bullet or "1." with text starts a list, so its indent
    # does not apply after "2." or an empty bullet
    assert semicolon_lines("Intro\n2. item\n\n    x = 1; y = 2") == []
    assert semicolon_lines("Intro\n*\n\n    x = 1; y = 2") == []
    assert semicolon_lines("Intro\n1. item\n\n    Then save it; close it.") == [4]
    # after a quote, any number starts a list; a thematic break and a number of ten
    # digits start none, and a very long number does not stop the run
    assert semicolon_lines("> Intro\n2. item\n\n    Then save it; close it.") == [4]
    assert semicolon_lines("Intro text.\n* * *\n    x = 1; y = 2") == []
    assert semicolon_lines("Text\n* * *\n\n    x = 1; y = 2") == []
    assert semicolon_lines("* * *\n  cont; `\n2. it; `") == [2]
    assert semicolon_lines("1234567890. item\n\n    x = 1; y = 2") == []
    assert semicolon_lines("Intro\n" + "1" * 5000 + ". digits; here.") == [2]
    # a lazy line keeps the nested item open, so its paragraph after a blank line is prose
    assert semicolon_lines("- outer\n  - nested\n  outer again\n\n      Save it; close it.") == [5]
    # a code span may wrap across lines of one paragraph
    assert semicolon_lines("Run `a;\nb; c` now; then") == [2]
    assert semicolon_lines("Run ``a`;\nb;`` now.") == []
    # a run that nothing closes in the paragraph is literal text
    assert semicolon_lines("A ` mark; here.\n\nAnd ` there; too.") == [1, 3]
    # a code span never crosses a block boundary: a new list item, a heading,
    # a fence, a quote-only line, or a change of quote depth
    assert semicolon_lines("- Press the ` key; it opens.\n- Run `x` now.\n") == [1]
    assert semicolon_lines("Press the ` key; it opens.\n# Run `x` now\n") == [1]
    assert semicolon_lines("Type ` to start; then stop.\n```\ncode\n```\nThe ` mark ends it.\n") == [1]
    assert semicolon_lines("> A ` mark; here.\n>\n> And ` there; too.\n") == [1, 3]
    assert semicolon_lines("# Title ` x\nText; with ` more\n") == [2]
    assert semicolon_lines("A ` mark; here.\n---\nAnd ` there; too.") == [1, 3]
    assert semicolon_lines("> A ` mark; here.\n> > And ` there; too.") == [1, 2]
    # a span still wraps inside a list item and a quote, also with a double run
    assert semicolon_lines("Run `a;\nb` now.\n") == []
    assert semicolon_lines("- Run `a;\n  b` now.\n") == []
    assert semicolon_lines("> Run `a;\n> b` now.\n") == []
    assert semicolon_lines("Run ``a`;\nb;`` now.\n- Next `x;` y.") == []
    # a line ends a span only where it ends the paragraph: "#" with no space is text,
    # a lazy line with fewer ">" continues the quote, "2." cannot start a list in a
    # paragraph, and inline HTML is text
    for text in ("A `foo;\n#bar`; done.", "> Run `code;\ncontinued` text; here.",
                 "Run `code;\n2. continued` text; here.",
                 "Run `code;\n#hashtag continued` text; here.",
                 "Run `code;\n<span>continued` text; here.",
                 "> > Run `code;\n> lazy\n> > continued` text; here."):
        assert semicolon_lines(text) == [text.count("\n") + 1], text
    # a next item of the open list, a setext underline, and an HTML block end the span
    assert semicolon_lines("1. Run `a;\n2. b` now; x") == [1, 2]
    assert semicolon_lines("Run `a;\n===\nb` now; x") == [1, 3]
    assert semicolon_lines("Run `a;\n<div>\n\nb` now; x") == [1, 4]
    assert semicolon_lines("Run `a;\n<div>\nb` now; x") == [1, 3]
    assert semicolon_lines("# Run `a;\nb` x;") == [1, 2]
    # a lazy underline, a fence or an item that is indented code, and a tab after ">"
    assert semicolon_lines("> Run `a;\n===\nb` x;") == [3]
    assert semicolon_lines("- Run `a;\n===\nb` now; x") == [3]
    assert semicolon_lines("1. Press the ` key; it opens.\n===\nUse `x` here.") == []
    assert semicolon_lines("- item; `\n===\ntext; `") == [1]
    # a thematic break is no lazy line: it ends the item, so deeper text after it is code
    assert semicolon_lines("- Item; here.\n* * *\n    x = 1; y = 2") == [1]
    assert semicolon_lines("Run `a;\n    ```\nb` x;") == []
    assert semicolon_lines("Run `a;\n    - b` x;") == [2]
    assert semicolon_lines("> Run `a;\n>\t- b` x;") == [1, 2]
    # any list item after a quote ends the quote: it is no lazy line
    assert semicolon_lines("> Press the ` key; it opens.\n2. Run `x` now; then stop.") == [1, 2]
    assert semicolon_lines("> Run `a;\n*\nb` x;") == [1, 3]
    assert semicolon_lines("> Quote text.\n- Press the ` key; it opens.\n> Run `x` now.") == [2]
    assert semicolon_lines("> > t w1; `\n> - q w2; `\n> > t w3; `") == [1, 2, 3]
    # each paragraph gets its own run index; a span in a quote uses the quote depth
    assert semicolon_lines("Run `a;\nb` x\n\nRun `c;\nd` y") == []
    assert semicolon_lines("> Run `a\n> b; c` now") == []
    # one scan of the paragraph finds the last line of each run length
    assert _paragraph_runs(["x ` y", "a `` b ` c", "", "e ` f"], 0, 0, 0) == (2, {1: 1, 2: 1})
    assert _mask_code_spans("a ` b;", 0, lambda run: False) == ("a ` b;", 0)
    assert _mask_code_spans("a ` b;", 0, lambda run: run == 1) == ("a     ", 1)
    # per-file labels
    findings, _ = lint("a; b", filename="x.md")
    assert findings[0]["file"] == "x.md"
    # inline code is masked, not deleted, so columns match the source
    findings, _ = lint("Run `make all` then spin up the node.")
    phrasal = [f for f in findings if f["rule"] == "phrasal-verb"]
    assert len(phrasal) == 1 and phrasal[0]["col"] == 21, phrasal
    # a sentence ends after closing quotes and brackets
    twenty = " ".join(["word"] * 20)
    findings, _ = lint(f'He asked "{twenty}?" Then {twenty} ended. (It {twenty}.) Next.')
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    # abbreviations do not end a sentence
    findings, _ = lint(f"Use a tool, e.g. the {twenty} linter here now.")
    assert any(f["rule"] == "long-sentence" for f in findings), findings
    findings, _ = lint(f"Compare A vs. B in the {twenty} test.")
    assert any(f["rule"] == "long-sentence" for f in findings), findings
    # a sentence wrapped across lines is counted once, at its start
    findings, _ = lint(f"Intro text here.\nThe {twenty}\nwrapped tail words go here.")
    long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
    assert len(long_sentences) == 1, long_sentences
    assert (long_sentences[0]["line"], long_sentences[0]["col"]) == (2, 1), long_sentences
    findings, _ = lint(f"- Item {twenty}\n  continued in the same item.")
    assert any(f["rule"] == "long-sentence" for f in findings), findings
    # leading front matter is skipped except its description; line numbers after it stay true
    findings, words_total = lint(f"---\nname: x\ndescription: {twenty} {twenty}.\n"
                                 "tags:\n  - a and\n---\nThe job is robust.")
    assert [(f["line"], f["rule"]) for f in findings] == [
        (3, "long-sentence"), (7, "marketing-adjective")], findings
    assert words_total == 44, words_total
    # the description is one paragraph, in a quoted, plain or block scalar
    for text, expected in (
            ("---\nname: x\ndescription: Applies to `thor/` only; the rules are in a file.\n---\n\nText.\n",
             [(3, 37, "semicolon")]),
            ('---\ndescription: "Use it; then stop."\n---\n', [(2, 21, "semicolon")]),
            ("---\ndescription: >-\n    Use it\n    robustly; then stop.\nname: x\n---\n",
             [(4, 5, "marketing-adjective"), (4, 13, "semicolon")]),
            ("---\ndescription: Use `a\n  b; c` now; stop.\n---\n", [(3, 12, "semicolon")]),
            ("---\ndescription: ```\n---\n\nProse; here.\n", [(5, 6, "semicolon")]),
            ("---\n# note\nname: x\n---\n", []),
            ("---\nname: x\n# note; here\nsummary: a; b\n---\n", []),
            # a comment before the first key, and a comment after the value
            ("---\n# metadata\nname: robust-tool\ndescription: Read the file.\n---\n", []),
            ("---\ndescription: Read the file. # robust; note\n---\n", []),
            ("---\ndescription: \"Read the file.\" # robust; note\n---\n", []),
            ("---\ndescription: Use it\n  # robust; note\n---\n", []),
            ("---\ndescription: \"Use it\n  across; lines\" # robust\n---\n", [(3, 9, "semicolon")]),
            # a link title that goes on in the next lines of the description
            ("---\ndescription: See [a](b \"x\n  y`z\") `w; v` q.\n---\n", []),
            ("---\ndescription: See [a](b \"x\n  y\n  z`w\") `p; q` r.\n---\n", []),
            ("---\ndescription: See [a](b \"x\n  y\") c; d.\n---\n", [(3, 8, "semicolon")]),
            ("---\ndescription: See [a](b \"x\n  y`z\") ``c ` d`` text; last `.\n---\n", [(3, 23, "semicolon")]),
            ("---\ndescription: ]( ;)\n---\n", [(2, 17, "semicolon")]),
            ("---\ndescription: See [a\n  ](b \";\") c; d.\n---\n", [(3, 13, "semicolon")]),
            ("---\ndescription: \\```;``\n---\n", []),
            # a "#" in quotes, in a block scalar, or inside a word is text
            ("---\ndescription: \"Read # the; file.\"\n---\n", [(2, 25, "semicolon")]),
            ("---\ndescription: 'It''s robust' # c\n---\n", [(2, 21, "marketing-adjective")]),
            ("---\ndescription: >\n  a # robust; b\n---\n", [(3, 7, "marketing-adjective"), (3, 13, "semicolon")]),
            ("---\ndescription: a#b; c\n---\n", [(2, 17, "semicolon")]),
            # the key "description" in quotes is the same key
            ("---\n\"description\": robust;\n---\n", [(2, 16, "marketing-adjective"), (2, 22, "semicolon")]),
            ("---\n'description' : a; b\n---\n", [(2, 18, "semicolon")]),
            ("---\n\"description\": |\n  a; b\n---\n", [(3, 4, "semicolon")]),
            ("---\n\"descriptions\": a; b\n---\n", []),
            # a later line that starts with the key can be in a quoted value of another key
            ("---\ndescription: robust;\nexample: \"foo\ndescription: plain\"\n---\n",
             [(2, 14, "marketing-adjective"), (2, 20, "semicolon")]),
            # a comment after a block scalar has less indent than its text
            ("---\ndescription: |\n    Use it.\n  # robust; note\n---\n", []),
            # quoted keys, keys with spaces and keys with other characters are YAML
            ("---\n\"robust-kit\": patch\n---\n", []),
            ("---\nallowed-tools: Bash; Read\n---\n", []),
            ("---\n$schema: robust; y\n---\n", []),
            ("---\nrésumé: a; b\n---\n", [])):
        findings, _ = lint(text)
        assert [(f["line"], f["col"], f["rule"]) for f in findings] == expected, (text, findings)
    # a block that is not YAML is Markdown: thematic breaks around prose
    findings, _ = lint("---\n# Instructions\n\nStart; stop.\n\n- First.\n\n---\n")
    assert [(f["line"], f["rule"]) for f in findings] == [(4, "semicolon")], findings
    findings, _ = lint("---\nStart; stop.\n---\n")
    assert [(f["line"], f["rule"]) for f in findings] == [(2, "semicolon")], findings
    # a plain key with a space reads as prose, as in "Step 1: run it"
    findings, _ = lint("---\nStep 1: run it; then: stop.\n---\n")
    assert [(f["line"], f["rule"]) for f in findings] == [(2, "semicolon")], findings
    # a block of comments only is Markdown: a heading between thematic breaks
    findings, _ = lint("---\n# Note\n---\n\nText; here.\n")
    assert [(f["line"], f["rule"]) for f in findings] == [(5, "semicolon")], findings
    # a later --- pair is a thematic break, not front matter
    findings, _ = lint(f"Intro.\n\n---\n{twenty} {twenty}.\n---")
    assert any(f["rule"] == "long-sentence" for f in findings), findings
    # blank lines, headings, rules, list items, and quotes end a prose block
    for sep in ("\n\n", "\n# Heading\n", "\n---\n", "\n- ", "\n> "):
        findings, _ = lint(f"First {twenty} line{sep}Second {twenty} line.")
        assert not any(f["rule"] == "long-sentence" for f in findings), (sep, findings)
    # a GitHub alert marker on the first line of a quote is not a word of the body
    body = " ".join(["word"] * 25) + "."
    for alert in ("> [!NOTE]", "> [!tip]", ">[!Warning]", ">  [!CAUTION]  "):
        findings, _ = lint(f"{alert}\n> {body}")
        assert not any(f["rule"] == "long-sentence" for f in findings), (alert, findings)
    for text in (f"Text.\n\n> [!NOTE]\n> {body}", f"> Text.\n~~~\ncode\n~~~\n> [!NOTE]\n> {body}"):
        findings, _ = lint(text)
        assert not any(f["rule"] == "long-sentence" for f in findings), (text, findings)
    # Inside HTML containers the marker is text: marker plus body is 26 words.
    for opening, closing in (("<details>", "</details>"),
                             ('<DIV class="note">', "</DIV>"),
                             ("<section><details>", "</details></section>")):
        findings, _ = lint(f"{opening}\n\n> [!NOTE]\n> {body}\n\n{closing}")
        long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
        assert [f["match"] for f in long_sentences] == ["26 words"], (opening, findings)
        findings, _ = lint(f"{opening}\n{closing}\n\n> [!NOTE]\n> {body}")
        assert not any(f["rule"] == "long-sentence" for f in findings), (opening, findings)
    findings, _ = lint(f"> [!NOTE]\n> {body}")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    # An inner close or a fenced closing tag must not close the outer container.
    for content in ("<details>\n<div>\n</div>",
                    "<details>\n\n~~~\n</details>\n~~~"):
        findings, _ = lint(f"{content}\n\n> [!NOTE]\n> {body}\n\n</details>")
        long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
        assert [f["match"] for f in long_sentences] == ["26 words"], (content, findings)
    # Directly after <details>, ~~~ is HTML text, not a fence. So the </details> line after
    # it closes the container, and the alert after it is outside, as GitHub shows it.
    findings, _ = lint(f"<details>\n~~~\n</details>\n~~~\n\n> [!NOTE]\n> {body}\n\n</details>")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    # Fenced, commented, inline, void, and self-closing tags do not open containers.
    for content in ("```html\n<details>\n```", "<!-- <details> -->",
                    "<span>Text.</span>", "<hr>", "<div />",
                    "<details></details>", "</details>"):
        findings, _ = lint(f"{content}\n\n> [!NOTE]\n> {body}")
        assert not any(f["rule"] == "long-sentence" for f in findings), (content, findings)
    # GitHub shows these markers as text, so they stay words. GitHub shows the
    # last two as alerts, but no blank line or fence proves that a quote starts.
    for text in (f"> [!FOO]\n> {body}", f"> [!NOTE] {body}", f"> Intro.\n> [!NOTE]\n> {body}",
                 f"> > [!NOTE]\n> > {body}", f"> Intro.\ncontinuation.\n> [!NOTE]\n> {body}",
                 f"- Item.\n\n  > [!NOTE]\n  > {body}",
                 f"Text.\n> [!NOTE]\n> {body}", f"   > [!NOTE]\n   > {body}"):
        findings, _ = lint(text)
        long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
        assert [f["match"] for f in long_sentences] == ["26 words"], (text, long_sentences)
    # a bold or italic lead sentence ends at its closing emphasis marker
    findings, _ = lint(f"**Lead.** The {twenty} more words here now.")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    findings, _ = lint(f"_Note._ The {twenty} more words here now.")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    findings, _ = lint(f"See **e.g.** the {twenty} linter here now.")
    assert any(f["rule"] == "long-sentence" for f in findings), findings
    # the closing marker ends the sentence also when the run opens before a code
    # span, in an earlier sentence, or after punctuation, when runs nest, when the
    # rule of 3 skips a run in between, and after an escaped marker; an entity or a
    # comment after it is no run, and a "*" or "_" in a link, an autolink or a tag
    # opens nothing; GitHub starts no www or http link after an open "[", after a
    # quote, or with "_" (also an escaped "_") in the last parts of the domain; a
    # "~~" in code and a "~~~" close no strikethrough
    for lead in ("**`make test` passes.**", "**Step 2. Run the tests.**", "**Smith, J. R. (2021).**",
                 "~~**Old rule.**", "«**Rule.**", "Note:**Rule.**", "***Lead.***", "**Bold *lead.***",
                 "*Lead.*", "__Lead.__", "_A `code` lead._", "**2*3 a*b.**", "\\***Lead.**",
                 "**Ready.**&nbsp;", "**Ready.**<!-- done -->", "_Read <https://example.com/a_> first._",
                 "_See [the docs](https://a.b/_x_) first._", "_A <span title=\"a_b\">x</span> lead._",
                 "_Read <span data_>the guide</span> now._", "[See <?x > ] ?> https://example.com/*a now.*",
                 "See <?a > www.example.com/?>*draft now.*",
                 "_Mail <ci_bot_@example.com>._", "*See https://web.archive.org/web/*/x.com first.*",
                 "[See https://example.com/*a] now.*", "[See the\nhttps://example.com/*a] now.*",
                 "See \"www.example.com/*draft\" now.*", "Open www.my_site.com/*draft now.*",
                 "Open www.my\\_site.com/*draft now.*",
                 "~~*Old `~~` rule.*", "See ~~~*old~~~ now.*"):
        findings, _ = lint(f"{lead} The {twenty} more words here now.")
        assert not any(f["rule"] == "long-sentence" for f in findings), (lead, findings)
    # GitHub reads the emphasis of a paragraph as a whole: a lazy line after a
    # quote line and a list marker that starts no item are in the paragraph,
    # and a tag or a comment can go on in the next line; after a list item that
    # holds an HTML block, a heading or a block quote, and after an indented line
    # that the main loop reads as the end of the list (a line of an outer item,
    # or a block quote with an indent), GitHub can read the lines in other
    # paragraphs than the main loop does, so there each run counts as used
    for lead in ("> *Read the\nguide here now.*", "*Read the\n2. guide here now.*",
                 "_Read <span\ntitle=\"a_\">the guide</span> now._", "_Read <span class=\"x\" title=\n\"a_\">the guide</span> now._",
                 "_Read the guide <!-- a\nb_ --> now._", "- <!-- note -->\n**Read the\n2. guide now.**",
                 "- <img src=\"x\">\n**Read the\n2. guide now.**", "- a\n    # b\n**Read the\n2. guide now.**",
                 "- a\n  <!DOCTYPE\nx> __Read the\nguide now.__", "- > *Read the\n  > guide here now.*",
                 "- a\n  > *see\n> b*Read the guide now.*", "- a *see\n    > b*Read the guide now.*",
                 "- a\n\n  > *see\n> b*Read the guide now.*", "> - a\n>\n>   > *see\n> > b*Read the guide now.*",
                 "- a\n  - b\n\n  *see\n    # c*Read the guide now.*",
                 "- a\n  - b\n\n  c\n\n  > *see\n> b*Read the guide now.*"):
        findings, _ = lint(f"{lead} The {twenty} more words here now.")
        assert not any(f["rule"] == "long-sentence" for f in findings), (lead, findings)
    # the description in the front matter is one paragraph, also for a tag or a
    # comment that goes on in the next line
    for lead in ("_Read <span\n  title=\"a_\">the guide</span> now._", "_Read the guide <!-- a\n  b_ --> now._"):
        findings, _ = lint(f"---\ndescription: |\n  {lead} The {twenty} more words here now.\n---\n")
        assert not any(f["rule"] == "long-sentence" for f in findings), (lead, findings)
    # a run after the stop that opens emphasis ends the sentence too, and one that
    # closes it with a marker left over
    for text in (f"It ran.*) The {twenty} more words* here now.",
                 f"*The {twenty} words end?** Then go on."):
        findings, _ = lint(text)
        assert not any(f["rule"] == "long-sentence" for f in findings), (text, findings)
    # a "*" or "_" that emphasis does not use is no sentence end: a glob, a closed
    # run, a word, a link, a run after a link or a strikethrough that closed its
    # opener (a link leaves out a ")" with no "(", a character reference and the
    # "_" before them; an escaped "[" does not stop a link; GitHub reads no
    # domain after its first character that is not ASCII), a run
    # that GitHub reads as no run (a "→" is no punctuation there, and a "~" next
    # to a run is skipped), and a run after a closer that GitHub stops at an
    # earlier failed closer
    for text in (f"The {twenty} words match file.* against the list.",
                 f"**Note:** the {twenty} words match file.* here.",
                 f"*Note* the {twenty} words match file.* here.",
                 f"\\*Note: the {twenty} words match file.* here.",
                 f"Read **.md files and {twenty} end.*) then go.",
                 f"«**`code` six.* and the {twenty} more words end.**",
                 f"{twenty} name snake_case and end._ then go on and on.",
                 f"{twenty} name __init__ and end.__ then go on and on.",
                 f"The {twenty} words <https://example.com/a_b>._ then go on and on.",
                 f"See <https://example.com/_notes> file._ then the {twenty} words go on.",
                 f"See [it](https://a.b/_x) file._ then the {twenty} words go on.",
                 f"See <span title=\"_a\">x</span> file._ then the {twenty} words go on.",
                 f"See <span _data>x</span> file._ then the {twenty} words go on.",
                 f"See <?a > _b ?> file._ then the {twenty} words go on.",
                 f"See <_build@example.com> file._ then the {twenty} words go on.",
                 f"See https://example.com/*.txt file.* then the {twenty} words go on.",
                 f"See www.example.com/_notes file._ then the {twenty} words go on.",
                 f"(See www.example.com/*a) file.* then the {twenty} words go on.",
                 f"_Read https://example.com/a_ first._ then the {twenty} words go on.",
                 f"~~*Old~~ rule.* then the {twenty} words go on.",
                 f"_See (https://example.com/a_) now._ then the {twenty} words go on.",
                 f"_See https://example.com/a_&amp; now._ then the {twenty} words go on.",
                 f"\\[See https://example.com/*a file.* then the {twenty} words go on.",
                 f"See https://éditions.my_site.fr/*a file.* then the {twenty} words go on.",
                 f"See →**(beta).** then the {twenty} words go on.",
                 f"Use ~~old~~**(new).** then the {twenty} words go on.",
                 f"__a._, b_, end._ then the {twenty} words go on."):
        findings, _ = lint(text)
        long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
        assert len(long_sentences) == 1, (text, long_sentences)
    # a paragraph ends at a blank line, also in a quote and after a list item
    # that holds an HTML block, and a table cell is a paragraph, also the last
    # one before a line that GitHub reads as a row; a tag at the end of the
    # paragraph, an escaped "<", a "<" in a code span, in an attribute value
    # or in the shown text of a processing instruction go on in no line, and a
    # tag in indented text is no HTML block; a list in a block quote, and a line
    # without indent after a blank line, are read as usual
    for text in (f"*See the\n\nlist now.* then the {twenty} words go on.",
                 f"> - See the {twenty} file.* then words go on.",
                 f"- a\n\n  > b\n\nSee the {twenty} file.* then words go on.",
                 f"- a\n  - b\n\n  c\n\n> See the {twenty} file.* then words go on.",
                 f"> *See the\n\nlist now.* then the {twenty} words go on.",
                 f"- <!-- note -->\n\nSee file.* then the {twenty} words go on.",
                 f"| a | b |\n| - | - |\n| *See the | list now.* then the {twenty} words go on. |",
                 f"| a | b |\n| - | - |\n| x | *See the |\nlist now.* then the {twenty} words go on.",
                 f"See the {twenty} file.* then words go on <span",
                 f"See the {twenty} file.* then \\<span\nwords go on.",
                 f"See the {twenty} file.* then `<!--`\nwords go on.",
                 f"See the {twenty} file.* <b title=\"<!--\">x</b> then\nwords go on.",
                 f"See the {twenty} file.* <?a > <!-- ?> then\nwords go on.",
                 f"- See the {twenty} file.* then\n      <div> words go on."):
        findings, _ = lint(text)
        long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
        assert len(long_sentences) == 1, (text, long_sentences)
    # many open runs and many closers that find no opener stay linear
    findings, _ = lint("*a " * 30000 + "c_ " * 30000 + "end.*")
    assert [f["match"] for f in findings if f["rule"] == "long-sentence"] == ["60001 words"], findings
    # a dotted abbreviation ends a sentence before a capitalized word
    findings, _ = lint(f"The team shipped it in the U.S. Then {twenty} today.")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    # nested list items, quoted list items, and HTML lines end a prose block
    for text in (f"- First item\n    - First {twenty} line\n      - Second {twenty} line",
                 f"> - First {twenty} line\n> - Second {twenty} line",
                 f"<!-- First {twenty} line -->\nSecond {twenty} line.",
                 f"> First {twenty} line.\n>\n> Second {twenty} line."):
        findings, _ = lint(text)
        assert not any(f["rule"] == "long-sentence" for f in findings), (text, findings)
    # a blockquote prefix is not a word in a wrapped quoted sentence
    findings, _ = lint("> " + "\n> ".join(["word word word word word"] * 5) + ".")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    # a list marker is not a word either, in every marker style
    twenty_five = " ".join(f"term{number}" for number in range(1, 26)) + "."
    for marker in ("-", "*", "+", "1.", "1)", "  -", "> -"):
        findings, _ = lint(f"{marker} {twenty_five}")
        assert not any(f["rule"] == "long-sentence" for f in findings), (marker, findings)
    findings, _ = lint(f"- term0 {twenty_five}")
    long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
    assert [(f["match"], f["col"]) for f in long_sentences] == [("26 words", 3)], long_sentences
    # a code span at the line start does not turn the next token into a list marker
    findings, _ = lint(f"`label` 1) {twenty_five}")
    long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
    assert [f["match"] for f in long_sentences] == ["26 words"], long_sentences
    # bare punctuation is not a word: code-span separators and spaced dashes
    for separator in (", ", " ", " / "):
        names = separator.join(f"`a{number}`" for number in range(30))
        findings, _ = lint(f"The adapters are {names}.")
        assert not any(f["rule"] == "long-sentence" for f in findings), (separator, findings)
    findings, _ = lint(" ".join(f"term{number}" for number in range(1, 25)) + " — term25.")
    assert not any(f["rule"] == "long-sentence" for f in findings), findings
    findings, _ = lint(f"Use `make` — {twenty_five}")
    long_sentences = [f for f in findings if f["rule"] == "long-sentence"]
    assert [f["match"] for f in long_sentences] == ["26 words"], long_sentences
    # a long block stays linear: one short sentence per line, no blank lines
    findings, _ = lint("The agent read the log.\n" * 20000)
    assert not any(f["rule"] == "long-sentence" for f in findings)
    # a long line with many code spans, and many links that go on in the next line, stay linear
    findings, _ = lint("`x` " * 60000 + "c; d.")
    assert [(f["rule"], f["col"]) for f in findings] == [("semicolon", 240002)], findings
    findings, _ = lint("[a](x;y\n)\n" * 5000)
    assert not any(f["rule"] == "semicolon" for f in findings), findings
    # flags may appear between file paths
    with tempfile.TemporaryDirectory() as tmp:
        paths = [os.path.join(tmp, name) for name in ("a.md", "b.md")]
        for path in paths:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("Short line here.\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main([paths[0], "--json", paths[1]]) == 0
        assert json.loads(out.getvalue())["words"] == 6, out.getvalue()
        # repeated --disable flags add up instead of replacing each other
        with open(paths[0], "w", encoding="utf-8") as fh:
            fh.write("a; b. " + " ".join(["word"] * 30) + ".\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main([paths[0], "--json", "--disable", "semicolon",
                         "--disable", "long-sentence"]) == 0
        assert json.loads(out.getvalue())["count"] == 0, out.getvalue()
    # command-line parsing rejects typos and bad values
    for bad in (["--basline", "3"], ["--baseline"], ["--baseline", "x"],
                ["--baseline", "-1"], ["--disable", "passive"], ["--base", "3"]):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                main(bad)
        except SystemExit as e:
            assert e.code == 2, (bad, e.code)
        else:
            raise AssertionError(bad)
    assert _rule_list("passive-voice,present-perfect") == {"passive-voice", "present-perfect"}
    # an HTML block in a block quote holds text, and it ends with its quote
    findings, _ = lint("> <div>\n> ```\n> This is prose; keep it.\n> ```\n> </div>")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 3)], findings
    findings, _ = lint("> <div>\n\n```\nx; y\n```\n\nProse; here.")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 7)], findings
    # a ">" line in an open HTML block is its text, not a quote end
    findings, _ = lint("<div>\n> Note.\n>\n> ```\n> a; b\n> ```\n</div>")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 5)], findings
    findings, _ = lint("<div>\n>\n```\nText; here.\n```")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 4)], findings
    # a quote after a paragraph starts a block quote, so a type 7 tag in it starts a block
    findings, _ = lint("Paragraph.\n> <widget>\n> ```\n> Text; here.\n> ```")
    assert [(f["rule"], f["line"]) for f in findings] == [("semicolon", 4)], findings
    print("selftest OK")


RULE_IDS = {rule_id for rule_id, *_ in RULES} | {
    "long-sentence", "synonym-rotation", "dangling-conjunction"}


def _rule_list(value):
    rules = {r for r in value.split(",") if r}
    unknown = rules - RULE_IDS
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown rule(s): {', '.join(sorted(unknown))}. "
            f"Known rules: {', '.join(sorted(RULE_IDS))}")
    return rules


def _non_negative_int(value):
    try:
        n = int(value)
    except ValueError:
        n = -1
    if n < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}")
    return n


def main(argv):
    parser = argparse.ArgumentParser(
        prog="ste-lint.py", allow_abbrev=False,
        description="Deterministic linter for the structural STE rules. "
                    "Reads stdin when no FILE is given.")
    parser.add_argument("paths", nargs="*", metavar="FILE")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--baseline", type=_non_negative_int, default=0, metavar="N",
                        help="pass unless hard violations exceed N (default 0)")
    parser.add_argument("--disable", type=_rule_list, action="append", default=[],
                        metavar="RULES",
                        help="comma-separated rule IDs to silence; may be repeated")
    parser.add_argument("--selftest", action="store_true", help="run the built-in tests")
    # intermixed parsing keeps flags valid between file paths
    args = parser.parse_intermixed_args(argv)
    if args.selftest:
        selftest()
        return 0
    as_json, baseline, paths = args.json, args.baseline, args.paths
    disabled = set().union(*args.disable)

    findings, words_total = [], 0
    if paths:
        for p in paths:
            try:
                with open(p, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as e:
                parser.error(f"cannot read {p}: {e.strerror}")
            f, w = lint(text, filename=p)
            findings.extend(f)
            words_total += w
    else:
        findings, words_total = lint(sys.stdin.read())

    findings = [f for f in findings if f["rule"] not in disabled]
    hard_count = sum(1 for f in findings if f["level"] == "advisory-free")
    report(findings, words_total, as_json, hard_count, baseline)
    return 1 if hard_count > baseline else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
