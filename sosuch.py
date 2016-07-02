#!/usr/bin/env python3.3
# -*- coding: utf-8 -*-
from __future__ import print_function

import certifi
from urllib3 import PoolManager
from urllib.parse import urlencode
from json import loads
from colorama import init, Fore, Back, Style
from subprocess import check_output, call
import sys
import os
from argparse import ArgumentParser, FileType
import re
import cgi
import yaml
from tempfile import mkstemp
try:
    import htmlentitydefs
    import urlparse
    import HTMLParser
except ImportError:  # Python3
    import html.entities as htmlentitydefs
    import urllib.parse as urlparse
    import html.parser as HTMLParser
try:  # Python3
    import urllib.request as urllib
except ImportError:
    import urllib

BASE_URL = 'https://2ch.hk'
STYLE_NUM = Fore.CYAN
STYLE_SUBJ = Fore.WHITE + Style.BRIGHT
STYLE_NAME = Fore.BLUE + Style.DIM
STYLE_EMAIL = Fore.BLUE + Style.BRIGHT
STYLE_DATE = Fore.CYAN
STYLE_BANNED = Fore.RED
STYLE_STICKY = Fore.YELLOW
STYLE_CLOSED = Fore.GREEN
STYLE_IMGS = Fore.MAGENTA
STYLE_SUMMARY = Style.DIM + Fore.GREEN
STYLE_RESET = Style.RESET_ALL
CAPTCHA_RESOLVE_SCRIPT = '2chaptcha_resolve.py'
EDITOR = os.environ.get('EDITOR','vim')

POST_TEMPLATE = """---
postready: no
name:
subject:
email:
image1:
image2:
image3:
image4:
...
"""

http = PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())

# -----------------
# --- HTML2Text ---
# -----------------

# Use Unicode characters instead of their ascii psuedo-replacements
UNICODE_SNOB = 1

# Escape all special characters.  Output is less readable, but avoids
# corner case formatting issues.
ESCAPE_SNOB = 0

# Put the links after each paragraph instead of at the end.
LINKS_EACH_PARAGRAPH = 0

# Wrap long lines at position. 0 for no wrapping. (Requires Python 2.3.)
BODY_WIDTH = 0

# Don't show internal links (href="#local-anchor") -- corresponding link
# targets won't be visible in the plain text file anyway.
SKIP_INTERNAL_LINKS = True

# Use inline, rather than reference, formatting for images and links
INLINE_LINKS = True

# Protect links from line breaks surrounding them with angle brackets (in
# addition to their square brackets)
PROTECT_LINKS = False

# Number of pixels Google indents nested lists
GOOGLE_LIST_INDENT = 36

IGNORE_ANCHORS = True
IGNORE_IMAGES = False
IMAGES_TO_ALT = False
IMAGES_WITH_SIZE = False
IGNORE_EMPHASIS = False

# For checking space-only lines on line 771
RE_SPACE = re.compile(r'\s\+')

RE_UNESCAPE = re.compile(r"&(#?[xX]?(?:[0-9a-fA-F]+|\w{1,8}));")
RE_ORDERED_LIST_MATCHER = re.compile(r'\d+\.\s')
RE_UNORDERED_LIST_MATCHER = re.compile(r'[-\*\+]\s')
RE_MD_CHARS_MATCHER = re.compile(r"([\\\[\]\(\)])")
RE_MD_CHARS_MATCHER_ALL = re.compile(r"([`\*_{}\[\]\(\)#!])")
RE_MD_DOT_MATCHER = re.compile(r"""
    ^             # start of line
    (\s*\d+)      # optional whitespace and a number
    (\.)          # dot
    (?=\s)        # lookahead assert whitespace
    """, re.MULTILINE | re.VERBOSE)
RE_MD_PLUS_MATCHER = re.compile(r"""
    ^
    (\s*)
    (\+)
    (?=\s)
    """, flags=re.MULTILINE | re.VERBOSE)
RE_MD_DASH_MATCHER = re.compile(r"""
    ^
    (\s*)
    (-)
    (?=\s|\-)     # followed by whitespace (bullet list, or spaced out hr)
                  # or another dash (header or hr)
    """, flags=re.MULTILINE | re.VERBOSE)
RE_SLASH_CHARS = r'\`*_{}[]()#+-.!'
RE_MD_BACKSLASH_MATCHER = re.compile(r'''
    (\\)          # match one slash
    (?=[%s])      # followed by a char that requires escaping
    ''' % re.escape(RE_SLASH_CHARS),
    flags=re.VERBOSE)

UNIFIABLE = {
    'rsquo': "'",
    'lsquo': "'",
    'rdquo': '"',
    'ldquo': '"',
    'copy': '(C)',
    'mdash': '--',
    'nbsp': ' ',
    'rarr': '->',
    'larr': '<-',
    'middot': '*',
    'ndash': '-',
    'oelig': 'oe',
    'aelig': 'ae',
    'agrave': 'a',
    'aacute': 'a',
    'acirc': 'a',
    'atilde': 'a',
    'auml': 'a',
    'aring': 'a',
    'egrave': 'e',
    'eacute': 'e',
    'ecirc': 'e',
    'euml': 'e',
    'igrave': 'i',
    'iacute': 'i',
    'icirc': 'i',
    'iuml': 'i',
    'ograve': 'o',
    'oacute': 'o',
    'ocirc': 'o',
    'otilde': 'o',
    'ouml': 'o',
    'ugrave': 'u',
    'uacute': 'u',
    'ucirc': 'u',
    'uuml': 'u',
    'lrm': '',
    'rlm': ''
}

BYPASS_TABLES = False

# Use a single line break after a block element rather an two line breaks.
# NOTE: Requires body width setting to be 0.
SINGLE_LINE_BREAK = False

def name2cp(k):
    if k == 'apos':
        return ord("'")
    return htmlentitydefs.name2codepoint[k]


unifiable_n = {}

for k in UNIFIABLE.keys():
    unifiable_n[name2cp(k)] = UNIFIABLE[k]


def hn(tag):
    if tag[0] == 'h' and len(tag) == 2:
        try:
            n = int(tag[1])
            if n in range(1, 10):
                return n
        except ValueError:
            return 0


def dumb_property_dict(style):
    """
    :returns: A hash of css attributes
    """
    out = dict([(x.strip(), y.strip()) for x, y in
                [z.split(':', 1) for z in
                 style.split(';') if ':' in z]])

    return out


def dumb_css_parser(data):
    """
    :type data: str

    :returns: A hash of css selectors, each of which contains a hash of
    css attributes.
    :rtype: dict
    """
    # remove @import sentences
    data += ';'
    importIndex = data.find('@import')
    while importIndex != -1:
        data = data[0:importIndex] + data[data.find(';', importIndex) + 1:]
        importIndex = data.find('@import')

    # parse the css. reverted from dictionary comprehension in order to
    # support older pythons
    elements = [x.split('{') for x in data.split('}') if '{' in x.strip()]
    try:
        elements = dict([(a.strip(), dumb_property_dict(b))
                         for a, b in elements])
    except ValueError:
        elements = {}  # not that important

    return elements


def element_style(attrs, style_def, parent_style):
    """
    :type attrs: dict
    :type style_def: dict
    :type style_def: dict

    :returns: A hash of the 'final' style attributes of the element
    :rtype: dict
    """
    style = parent_style.copy()
    if 'class' in attrs:
        for css_class in attrs['class'].split():
            css_style = style_def['.' + css_class]
            style.update(css_style)
    if 'style' in attrs:
        immediate_style = dumb_property_dict(attrs['style'])
        style.update(immediate_style)

    return style


def google_list_style(style):
    """
    Finds out whether this is an ordered or unordered list

    :type style: dict

    :rtype: str
    """
    if 'list-style-type' in style:
        list_style = style['list-style-type']
        if list_style in ['disc', 'circle', 'square', 'none']:
            return 'ul'

    return 'ol'


def google_has_height(style):
    """
    Check if the style of the element has the 'height' attribute
    explicitly defined

    :type style: dict

    :rtype: bool
    """
    if 'height' in style:
        return True

    return False


def google_text_emphasis(style):
    """
    :type style: dict

    :returns: A list of all emphasis modifiers of the element
    :rtype: list
    """
    emphasis = []
    if 'text-decoration' in style:
        emphasis.append(style['text-decoration'])
    if 'font-style' in style:
        emphasis.append(style['font-style'])
    if 'font-weight' in style:
        emphasis.append(style['font-weight'])
    if 'spoiler' in style:
        emphasis.append(style['spoiler'])
    if 'quote' in style:
        emphasis.append(style['quote'])

    return emphasis


def google_fixed_width_font(style):
    """
    Check if the css of the current element defines a fixed width font

    :type style: dict

    :rtype: bool
    """
    font_family = ''
    if 'font-family' in style:
        font_family = style['font-family']
    if 'Courier New' == font_family or 'Consolas' == font_family:
        return True

    return False


def list_numbering_start(attrs):
    """
    Extract numbering from list element attributes

    :type attrs: dict

    :rtype: int or None
    """
    if 'start' in attrs:
        try:
            return int(attrs['start']) - 1
        except ValueError:
            pass

    return 0


def skipwrap(para):
    # If the text begins with four spaces or one tab, it's a code block;
    # don't wrap
    if para[0:4] == '    ' or para[0] == '\t':
        return True

    # If the text begins with only two "--", possibly preceded by
    # whitespace, that's an emdash; so wrap.
    stripped = para.lstrip()
    if stripped[0:2] == "--" and len(stripped) > 2 and stripped[2] != "-":
        return False

    # I'm not sure what this is for; I thought it was to detect lists,
    # but there's a <br>-inside-<span> case in one of the tests that
    # also depends upon it.
    if stripped[0:1] == '-' or stripped[0:1] == '*':
        return True

    # If the text begins with a single -, *, or +, followed by a space,
    # or an integer, followed by a ., followed by a space (in either
    # case optionally proceeded by whitespace), it's a list; don't wrap.
    if RE_ORDERED_LIST_MATCHER.match(stripped) or \
            RE_UNORDERED_LIST_MATCHER.match(stripped):
        return True

    return False


def wrapwrite(text):
    text = text.encode('utf-8')
    try:  # Python3
        sys.stdout.buffer.write(text)
    except AttributeError:
        sys.stdout.write(text)


def wrap_read():
    """
    :rtype: str
    """
    try:
        return sys.stdin.read()
    except AttributeError:
        return sys.stdin.buffer.read()


def escape_md(text):
    """
    Escapes markdown-sensitive characters within other markdown
    constructs.
    """
    return RE_MD_CHARS_MATCHER.sub(r"\\\1", text)


def escape_md_section(text, snob=False):
    """
    Escapes markdown-sensitive characters across whole document sections.
    """
    text = RE_MD_BACKSLASH_MATCHER.sub(r"\\\1", text)

    if snob:
        text = RE_MD_CHARS_MATCHER_ALL.sub(r"\\\1", text)

    text = RE_MD_DOT_MATCHER.sub(r"\1\\\2", text)
    text = RE_MD_PLUS_MATCHER.sub(r"\1\\\2", text)
    text = RE_MD_DASH_MATCHER.sub(r"\1\\\2", text)

    return text

class HTML2Text(HTMLParser.HTMLParser):
    def __init__(self, out=None, baseurl='', bodywidth=BODY_WIDTH):
        """
        Input parameters:
            out: possible custom replacement for self.outtextf (which
                 appends lines of text).
            baseurl: base URL of the document we process
        """
        HTMLParser.HTMLParser.__init__(self)

        # Config options
        self.split_next_td = False
        self.td_count = 0
        self.table_start = False
        self.unicode_snob = UNICODE_SNOB
        self.escape_snob = ESCAPE_SNOB
        self.links_each_paragraph = LINKS_EACH_PARAGRAPH
        self.body_width = bodywidth
        self.skip_internal_links = SKIP_INTERNAL_LINKS
        self.inline_links = INLINE_LINKS
        self.protect_links = PROTECT_LINKS
        self.google_list_indent = GOOGLE_LIST_INDENT
        self.ignore_links = IGNORE_ANCHORS
        self.ignore_images = IGNORE_IMAGES
        self.images_to_alt = IMAGES_TO_ALT
        self.images_with_size = IMAGES_WITH_SIZE
        self.ignore_emphasis = IGNORE_EMPHASIS
        self.bypass_tables = BYPASS_TABLES
        self.google_doc = True
        self.ul_item_mark = '*'
        self.emphasis_start_mark = Fore.LIGHTGREEN_EX
        self.emphasis_stop_mark = Style.RESET_ALL
        self.strong_start_mark = Fore.LIGHTCYAN_EX + Style.BRIGHT
        self.strong_stop_mark = Style.RESET_ALL
        self.spoiler_start_mark = Fore.WHITE + Back.WHITE + Style.DIM
        self.spoiler_stop_mark = Style.RESET_ALL
        self.quote_start_mark = Fore.GREEN + Style.DIM
        self.quote_stop_mark = Style.RESET_ALL
        self.single_line_break = SINGLE_LINE_BREAK

        if out is None:
            self.out = self.outtextf
        else:
            self.out = out

        # empty list to store output characters before they are "joined"
        self.outtextlist = []

        self.quiet = 0
        self.p_p = 0  # number of newline character to print before next output
        self.outcount = 0
        self.start = 1
        self.space = 0
        self.a = []
        self.astack = []
        self.maybe_automatic_link = None
        self.empty_link = False
        self.absolute_url_matcher = re.compile(r'^[a-zA-Z+]+://')
        self.acount = 0
        self.list = []
        self.blockquote = 0
        self.pre = 0
        self.startpre = 0
        self.code = False
        self.br_toggle = ''
        self.lastWasNL = 0
        self.lastWasList = False
        self.style = 0
        self.style_def = {'.post-reply-link': {'quote': 'quote'},
                          '.unkfunc': {'quote': 'quote'},
                          '.o': {},
                          '.u': {},
                          '.s': {},
                          '.spoiler': {'spoiler': 'spoiler'}}
        self.tag_stack = []
        self.emphasis = 0
        self.drop_white_space = 0
        self.inheader = False
        self.abbr_title = None  # current abbreviation definition
        self.abbr_data = None  # last inner HTML (for abbr being defined)
        self.abbr_list = {}  # stack of abbreviations to write later
        self.baseurl = baseurl

        try:
            del unifiable_n[name2cp('nbsp')]
        except KeyError:
            pass
        UNIFIABLE['nbsp'] = '&nbsp_place_holder;'

    def feed(self, data):
        data = data.replace("</' + 'script>", "</ignore>")
        HTMLParser.HTMLParser.feed(self, data)

    def handle(self, data):
        self.feed(data)
        self.feed("")
        return self.optwrap(self.close())

    def outtextf(self, s):
        self.outtextlist.append(s)
        if s:
            self.lastWasNL = s[-1] == '\n'

    def close(self):
        HTMLParser.HTMLParser.close(self)

        try:
            nochr = unicode('')
        except NameError:
            nochr = str('')

        self.pbr()
        self.o('', 0, 'end')

        outtext = nochr.join(self.outtextlist)
        if self.unicode_snob:
            try:
                nbsp = unichr(name2cp('nbsp'))
            except NameError:
                nbsp = chr(name2cp('nbsp'))
        else:
            try:
                nbsp = unichr(32)
            except NameError:
                nbsp = chr(32)
        try:
            outtext = outtext.replace(unicode('&nbsp_place_holder;'), nbsp)
        except NameError:
            outtext = outtext.replace('&nbsp_place_holder;', nbsp)

        # Clear self.outtextlist to avoid memory leak of its content to
        # the next handling.
        self.outtextlist = []

        return outtext

    def handle_charref(self, c):
        charref = self.charref(c)
        if not self.code and not self.pre:
            charref = cgi.escape(charref)
        self.o(charref, 1)

    def handle_entityref(self, c):
        entityref = self.entityref(c)
        if not self.code and not self.pre and entityref != '&nbsp_place_holder;':
            entityref = cgi.escape(entityref)
        self.o(entityref, 1)

    def handle_starttag(self, tag, attrs):
        self.handle_tag(tag, attrs, 1)

    def handle_endtag(self, tag):
        self.handle_tag(tag, None, 0)

    def previousIndex(self, attrs):
        """
        :type attrs: dict

        :returns: The index of certain set of attributes (of a link) in the
        self.a list. If the set of attributes is not found, returns None
        :rtype: int
        """
        if 'href' not in attrs:
            return None

        i = -1
        for a in self.a:
            i += 1
            match = 0

            if ('href' in a) and a['href'] == attrs['href']:
                if ('title' in a) or ('title' in attrs):
                    if (('title' in a) and ('title' in attrs) and
                                a['title'] == attrs['title']):
                        match = True
                else:
                    match = True

            if match:
                return i

    def handle_emphasis(self, start, tag_style, parent_style):
        """
        Handles various text emphases
        """
        tag_emphasis = google_text_emphasis(tag_style)
        parent_emphasis = google_text_emphasis(parent_style)

        # handle Google's text emphasis
        strikethrough = 'line-through' in \
                        tag_emphasis and self.hide_strikethrough
        bold = 'bold' in tag_emphasis and not 'bold' in parent_emphasis
        italic = 'italic' in tag_emphasis and not 'italic' in parent_emphasis
        fixed = google_fixed_width_font(tag_style) and not \
            google_fixed_width_font(parent_style) and not self.pre
        spoiler = 'spoiler' in tag_emphasis and not 'spoiler' in parent_emphasis
        quote = 'quote' in tag_emphasis and not 'quote' in parent_emphasis

        if start:
            # crossed-out text must be handled before other attributes
            # in order not to output qualifiers unnecessarily
            if bold or italic or fixed:
                self.emphasis += 1
            if strikethrough:
                self.quiet += 1
            if italic:
                self.o(self.emphasis_start_mark)
                self.drop_white_space += 1
            if bold:
                self.o(self.strong_start_mark)
                self.drop_white_space += 1
            if fixed:
                self.o('`')
                self.drop_white_space += 1
                self.code = True
            if spoiler:
                self.o(self.spoiler_start_mark)
            if quote:
                self.o(self.quote_start_mark)
        else:
            if bold or italic or fixed:
                # there must not be whitespace before closing emphasis mark
                self.emphasis -= 1
                self.space = 0
            if fixed:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o('`')
                self.code = False
            if bold:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.strong_stop_mark)
            if italic:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.emphasis_stop_mark)
            if spoiler:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.spoiler_stop_mark)
            if quote:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.quote_stop_mark)
            # space is only allowed after *all* emphasis marks
            if (bold or italic) and not self.emphasis:
                self.o(" ")
            if strikethrough:
                self.quiet -= 1

    def handle_tag(self, tag, attrs, start):
        # attrs is None for endtags
        if attrs is None:
            attrs = {}
        else:
            attrs = dict(attrs)

        if self.google_doc:
            # the attrs parameter is empty for a closing tag. in addition, we
            # need the attributes of the parent nodes in order to get a
            # complete style description for the current element. we assume
            # that google docs export well formed html.
            parent_style = {}
            if start:
                if self.tag_stack:
                    parent_style = self.tag_stack[-1][2]
                tag_style = element_style(attrs, self.style_def, parent_style)
                self.tag_stack.append((tag, attrs, tag_style))
            else:
                dummy, attrs, tag_style = self.tag_stack.pop()
                if self.tag_stack:
                    parent_style = self.tag_stack[-1][2]

        if hn(tag):
            self.p()
            if start:
                self.inheader = True
                self.o(hn(tag) * "#" + ' ')
            else:
                self.inheader = False
                return  # prevent redundant emphasis marks on headers

        if tag in ['p', 'div']:
            if self.google_doc:
                if start and google_has_height(tag_style):
                    self.p()
                else:
                    self.soft_br()
            else:
                self.p()

        if tag == "br" and start:
            self.o("  \n")

        if tag == "hr" and start:
            self.p()
            self.o("* * *")
            self.p()

        if tag in ["head", "style", 'script']:
            if start:
                self.quiet += 1
            else:
                self.quiet -= 1

        if tag == "style":
            if start:
                self.style += 1
            else:
                self.style -= 1

        if tag in ["body"]:
            self.quiet = 0  # sites like 9rules.com never close <head>

        if tag == "blockquote":
            if start:
                self.p()
                self.o('> ', 0, 1)
                self.start = 1
                self.blockquote += 1
            else:
                self.blockquote -= 1
                self.p()

        if tag in ['em', 'i', 'u'] and not self.ignore_emphasis:
            self.o(self.emphasis_start_mark) if start else self.o(self.emphasis_stop_mark)
        if tag in ['strong', 'b'] and not self.ignore_emphasis:
            self.o(self.strong_start_mark) if start else self.o(self.strong_stop_mark)
        if tag in ['del', 'strike', 's']:
            if start:
                self.o("<" + tag + ">")
            else:
                self.o("</" + tag + ">")

        if self.google_doc:
            if not self.inheader:
                # handle some font attributes, but leave headers clean
                self.handle_emphasis(start, tag_style, parent_style)

        if tag in ["code", "tt"] and not self.pre:
            self.o('`')  # TODO: `` `this` ``
            self.code = not self.code
        if tag == "abbr":
            if start:
                self.abbr_title = None
                self.abbr_data = ''
                if ('title' in attrs):
                    self.abbr_title = attrs['title']
            else:
                if self.abbr_title is not None:
                    self.abbr_list[self.abbr_data] = self.abbr_title
                    self.abbr_title = None
                self.abbr_data = ''

        if tag == "a" and not self.ignore_links:
            if start:
                if ('href' in attrs) and \
                        (attrs['href'] is not None) and \
                        not (self.skip_internal_links and
                                 attrs['href'].startswith('#')):
                    self.astack.append(attrs)
                    self.maybe_automatic_link = attrs['href']
                    self.empty_link = True
                    if self.protect_links:
                        attrs['href'] = '<'+attrs['href']+'>'
                else:
                    self.astack.append(None)
            else:
                if self.astack:
                    a = self.astack.pop()
                    if self.maybe_automatic_link and not self.empty_link:
                        self.maybe_automatic_link = None
                    elif a:
                        if self.empty_link:
                            self.o("[")
                            self.empty_link = False
                            self.maybe_automatic_link = None
                        if self.inline_links:
                            self.o("](" + escape_md(a['href']) + ")")
                        else:
                            i = self.previousIndex(a)
                            if i is not None:
                                a = self.a[i]
                            else:
                                self.acount += 1
                                a['count'] = self.acount
                                a['outcount'] = self.outcount
                                self.a.append(a)
                            self.o("][" + str(a['count']) + "]")

        if tag == "img" and start and not self.ignore_images:
            if 'src' in attrs:
                if not self.images_to_alt:
                    attrs['href'] = attrs['src']
                alt = attrs.get('alt') or ''

                # If we have images_with_size, write raw html including width,
                # height, and alt attributes
                if self.images_with_size and \
                        ("width" in attrs or "height" in attrs):
                    self.o("<img src='" + attrs["src"] + "' ")
                    if "width" in attrs:
                        self.o("width='" + attrs["width"] + "' ")
                    if "height" in attrs:
                        self.o("height='" + attrs["height"] + "' ")
                    if alt:
                        self.o("alt='" + alt + "' ")
                    self.o("/>")
                    return

                # If we have a link to create, output the start
                if not self.maybe_automatic_link is None:
                    href = self.maybe_automatic_link
                    if self.images_to_alt and escape_md(alt) == href and \
                            self.absolute_url_matcher.match(href):
                        self.o("<" + escape_md(alt) + ">")
                        self.empty_link = False
                        return
                    else:
                        self.o("[")
                        self.maybe_automatic_link = None
                        self.empty_link = False

                # If we have images_to_alt, we discard the image itself,
                # considering only the alt text.
                if self.images_to_alt:
                    self.o(escape_md(alt))
                else:
                    self.o("![" + escape_md(alt) + "]")
                    if self.inline_links:
                        href = attrs.get('href') or ''
                        self.o("(" + escape_md(href) + ")")
                    else:
                        i = self.previousIndex(attrs)
                        if i is not None:
                            attrs = self.a[i]
                        else:
                            self.acount += 1
                            attrs['count'] = self.acount
                            attrs['outcount'] = self.outcount
                            self.a.append(attrs)
                        self.o("[" + str(attrs['count']) + "]")

        if tag == 'dl' and start:
            self.p()
        if tag == 'dt' and not start:
            self.pbr()
        if tag == 'dd' and start:
            self.o('    ')
        if tag == 'dd' and not start:
            self.pbr()

        if tag in ["ol", "ul"]:
            # Google Docs create sub lists as top level lists
            if (not self.list) and (not self.lastWasList):
                self.p()
            if start:
                if self.google_doc:
                    list_style = google_list_style(tag_style)
                else:
                    list_style = tag
                numbering_start = list_numbering_start(attrs)
                self.list.append({
                    'name': list_style,
                    'num': numbering_start
                })
            else:
                if self.list:
                    self.list.pop()
            self.lastWasList = True
        else:
            self.lastWasList = False

        if tag == 'li':
            self.pbr()
            if start:
                if self.list:
                    li = self.list[-1]
                else:
                    li = {'name': 'ul', 'num': 0}
                if self.google_doc:
                    nest_count = self.google_nest_count(tag_style)
                else:
                    nest_count = len(self.list)
                # TODO: line up <ol><li>s > 9 correctly.
                self.o("  " * nest_count)
                if li['name'] == "ul":
                    self.o(self.ul_item_mark + " ")
                elif li['name'] == "ol":
                    li['num'] += 1
                    self.o(str(li['num']) + ". ")
                self.start = 1

        if tag in ["table", "tr", "td", "th"]:
            if self.bypass_tables:
                if start:
                    self.soft_br()
                if tag in ["td", "th"]:
                    if start:
                        self.o('<{0}>\n\n'.format(tag))
                    else:
                        self.o('\n</{0}>'.format(tag))
                else:
                    if start:
                        self.o('<{0}>'.format(tag))
                    else:
                        self.o('</{0}>'.format(tag))

            else:
                if tag == "table" and start:
                    self.table_start = True
                if tag in ["td", "th"] and start:
                    if self.split_next_td:
                        self.o("| ")
                    self.split_next_td = True

                if tag == "tr" and start:
                    self.td_count = 0
                if tag == "tr" and not start:
                    self.split_next_td = False
                    self.soft_br()
                if tag == "tr" and not start and self.table_start:
                    # Underline table header
                    self.o("|".join(["---"] * self.td_count))
                    self.soft_br()
                    self.table_start = False
                if tag in ["td", "th"] and start:
                    self.td_count += 1

        if tag == "pre":
            if start:
                self.startpre = 1
                self.pre = 1
            else:
                self.pre = 0
            self.p()

    def pbr(self):
        if self.p_p == 0:
            self.p_p = 1

    def p(self):
        self.p_p = 1 if self.single_line_break else 2

    def soft_br(self):
        self.pbr()
        self.br_toggle = '  '

    def o(self, data, puredata=0, force=0):
        """
        Deal with indentation and whitespace
        """
        if self.abbr_data is not None:
            self.abbr_data += data

        if not self.quiet:
            if self.google_doc:
                # prevent white space immediately after 'begin emphasis'
                # marks ('**' and '_')
                lstripped_data = data.lstrip()
                if self.drop_white_space and not (self.pre or self.code):
                    data = lstripped_data
                if lstripped_data != '':
                    self.drop_white_space = 0

            if puredata and not self.pre:
                # This is a very dangerous call ... it could mess up
                # all handling of &nbsp; when not handled properly
                # (see entityref)
                data = re.sub(r'\s+', r' ', data)
                if data and data[0] == ' ':
                    self.space = 1
                    data = data[1:]
            if not data and not force:
                return

            if self.startpre:
                #self.out(" :") #TODO: not output when already one there
                if not data.startswith("\n"):  # <pre>stuff...
                    data = "\n" + data

            bq = (">" * self.blockquote)
            if not (force and data and data[0] == ">") and self.blockquote:
                bq += " "

            if self.pre:
                if not self.list:
                    bq += "    "
                #else: list content is already partially indented
                for i in range(len(self.list)):
                    bq += "    "
                data = data.replace("\n", "\n" + bq)

            if self.startpre:
                self.startpre = 0
                if self.list:
                    # use existing initial indentation
                    data = data.lstrip("\n")

            if self.start:
                self.space = 0
                self.p_p = 0
                self.start = 0

            if force == 'end':
                # It's the end.
                self.p_p = 0
                self.out("\n")
                self.space = 0

            if self.p_p:
                self.out((self.br_toggle + '\n' + bq) * self.p_p)
                self.space = 0
                self.br_toggle = ''

            if self.space:
                if not self.lastWasNL:
                    self.out(' ')
                self.space = 0

            if self.a and ((self.p_p == 2 and self.links_each_paragraph)
                           or force == "end"):
                if force == "end":
                    self.out("\n")

                newa = []
                for link in self.a:
                    if self.outcount > link['outcount']:
                        self.out("   [" + str(link['count']) + "]: " +
                                 urlparse.urljoin(self.baseurl, link['href']))
                        if 'title' in link:
                            self.out(" (" + link['title'] + ")")
                        self.out("\n")
                    else:
                        newa.append(link)

                # Don't need an extra line when nothing was done.
                if self.a != newa:
                    self.out("\n")

                self.a = newa

            if self.abbr_list and force == "end":
                for abbr, definition in self.abbr_list.items():
                    self.out("  *[" + abbr + "]: " + definition + "\n")

            self.p_p = 0
            self.out(data)
            self.outcount += 1

    def handle_data(self, data):
        if r'\/script>' in data:
            self.quiet -= 1

        if self.style:
            self.style_def.update(dumb_css_parser(data))

        if not self.maybe_automatic_link is None:
            href = self.maybe_automatic_link
            if href == data and self.absolute_url_matcher.match(href):
                self.o("<" + data + ">")
                self.empty_link = False
                return
            else:
                self.o("[")
                self.maybe_automatic_link = None
                self.empty_link = False

        if not self.code and not self.pre:
            data = escape_md_section(data, snob=self.escape_snob)
        self.o(data, 1)

    def unknown_decl(self, data):
        pass

    def charref(self, name):
        if name[0] in ['x', 'X']:
            c = int(name[1:], 16)
        else:
            c = int(name)

        if not self.unicode_snob and c in unifiable_n.keys():
            return unifiable_n[c]
        else:
            try:
                return unichr(c)
            except NameError:  # Python3
                return chr(c)

    def entityref(self, c):
        if not self.unicode_snob and c in UNIFIABLE.keys():
            return UNIFIABLE[c]
        else:
            try:
                name2cp(c)
            except KeyError:
                return "&" + c + ';'
            else:
                if c == 'nbsp':
                    return UNIFIABLE[c]
                else:
                    try:
                        return unichr(name2cp(c))
                    except NameError:  # Python3
                        return chr(name2cp(c))

    def replaceEntities(self, s):
        s = s.group(1)
        if s[0] == "#":
            return self.charref(s[1:])
        else:
            return self.entityref(s)

    def unescape(self, s):
        return RE_UNESCAPE.sub(self.replaceEntities, s)

    def google_nest_count(self, style):
        """
        Calculate the nesting count of google doc lists

        :type style: dict

        :rtype: int
        """
        nest_count = 0
        if 'margin-left' in style:
            nest_count = int(style['margin-left'][:-2]) \
                         // self.google_list_indent

        return nest_count

    def optwrap(self, text):
        """
        Wrap all paragraphs in the provided text.

        :type text: str

        :rtype: str
        """
        if not self.body_width:
            return text

        assert wrap, "Requires Python 2.3."
        result = ''
        newlines = 0
        for para in text.split("\n"):
            if len(para) > 0:
                if not skipwrap(para):
                    result += "\n".join(wrap(para, self.body_width))
                    if para.endswith('  '):
                        result += "  \n"
                        newlines = 1
                    else:
                        result += "\n\n"
                        newlines = 2
                else:
                    # Warning for the tempted!!!
                    # Be aware that obvious replacement of this with
                    # line.isspace()
                    # DOES NOT work! Explanations are welcome.
                    if not RE_SPACE.match(para):
                        result += para + "\n"
                        newlines = 1
            else:
                if newlines < 2:
                    result += "\n"
                    newlines += 1
        return result

def html2text(s):
    h2t = HTML2Text(baseurl=BASE_URL)
    h2t.body_width=0
    return h2t.unescape(h2t.handle(s))

# ---------------------
# --- Sosuch parser ---
# ---------------------
def print_post(p, board):
    banned = STYLE_BANNED + ("[banned]" if p["banned"] == 1 else "") + STYLE_RESET
    sticky = STYLE_STICKY + ("[sticky]" if p["sticky"] == 1 else "") + STYLE_RESET
    closed = STYLE_CLOSED + ("[closed]" if p["closed"] == 1 else "") + STYLE_RESET
    num = STYLE_NUM + ">>" + str(p["num"]) + STYLE_RESET
    subj = STYLE_SUBJ + (html2text(p["subject"]) + " " if p["subject"] != "" else "") + STYLE_RESET
    name = STYLE_NAME + p["name"] + " " + STYLE_RESET
    email = (STYLE_EMAIL + "<" + p["email"] + "> " + STYLE_RESET) if p["email"] else ""
    date = STYLE_DATE + p["date"] + STYLE_RESET
    print ("%s%s%s%s %s %s%s%s" % (subj, name, email, date, num, banned, sticky, closed))
    for f in p["files"]:
        print ((STYLE_IMGS + "%s/%s/%s" + STYLE_RESET) % (BASE_URL, board, f["path"]))
    print(html2text(p["comment"]))

def resolve_captcha():
    CAPTCHA_URL = '%s/makaba/captcha.fcgi' % BASE_URL
    resp = http.request('GET', CAPTCHA_URL, fields={'type': '2chaptcha', 'action': 'thread'})
    if resp.status == 200:
        data = resp.data.decode('utf-8')
        _, captcha_id = data.split('\n')
        CAPTCHA_IMG_URL = '%s/makaba/captcha.fcgi' % BASE_URL
        resp = http.request('GET', CAPTCHA_IMG_URL, fields={'type': '2chaptcha', 'action': 'image', 'id': captcha_id})
        img = resp.data
        _, fn = mkstemp(suffix='png')
        with open(fn, 'wb') as f:
            f.write(img)
        p = check_output([CAPTCHA_RESOLVE_SCRIPT, captcha_id, fn]).decode('utf-8')
        os.remove(fn)
        return (p.strip(), captcha_id)
    return None

def threads(board):
    URL = '%s/%s/catalog.json' % (BASE_URL, board)
    resp = http.request('GET', URL)
    if resp.status == 200:
        data = loads(resp.data.decode('utf-8'))
        threads = data["threads"]
        for t in threads:
            summary = STYLE_SUMMARY + (("Пропущено постов %d из них %d с картинками" % (t["posts_count"], t["files_count"])) if t["posts_count"] != 0 else "")  + STYLE_RESET
            print_post(t, board)
            print(summary)
            print("-" * 80)
    else:
        print("Error %d" % resp.status)
    
def posts(board, thread):
    URL = '%s/%s/res/%s.json' % (BASE_URL, board, thread)
    resp = http.request('GET', URL)
    if resp.status == 200:
        data = loads(resp.data.decode('utf-8'))
        posts = data["threads"][0]["posts"]
        for p in posts:
            print_post(p, board)
            print("-" * 80)
    else:
        print("Error %d" % (resp.status))

def post(board, thread, comment, captcha_id, captcha_value, subject=None, name=None, email=None, images=None):
    query_fields = {'json': '1',
                    'task': 'post',
                    'captcha_type': '2chaptcha',
                    'board': board,
                    'thread': thread,
                    '2chaptcha_id': captcha_id,
                    '2chaptcha_value': captcha_value}
    encoded_fields = urlencode(query_fields)
    URL = '%s/makaba/posting.fcgi?%s' % (BASE_URL, encoded_fields)
    fields = {'comment': comment}
    if email:
        fields['email'] = email
    if name:
        fields['name'] = name
    if subject:
        fields['subject'] = subject
    if images:
        for i in range(min(len(images),4)):
            fields['image%d' % i] = ('yourmom%d.png' % i, images[i])
    resp = http.request('POST', URL, fields=fields)
    data = loads(resp.data.decode('utf-8'))
    if ('Status' in data) and (data['Status'] == 'OK' or data['Status'] == 'Redirect'):
        print('OK: %s' % data['Num'])
        return True
    else:
        print('Error: %d %s' % (data['Error'], data['Reason']))
        return False

def parse_post(f):
    parsed = yaml.load_all(f)
    post_header = next(parsed)
    if 'postready' in post_header and (not post_header['postready']):
        print("Post not ready")
        return None
    f.seek(0)
    l = f.readline()
    while (l != '...\n') and (l != ''):
        l = f.readline()
    if l == '':
        return None
    comment = f.read()
    post_header['comment'] = comment
    imgs = []
    if 'image1' in post_header and post_header['image1']:
        with open(post_header['image1'], 'rb') as f:
            imgs += [f.read()]
    if 'image2' in post_header and post_header['image2']:
        with open(post_header['image2'], 'rb') as f:
            imgs += [f.read()]
    if 'image3' in post_header and post_header['image3']:
        with open(post_header['image3'], 'rb') as f:
            imgs += [f.read()]
    if 'image4' in post_header and post_header['image4']:
        with open(post_header['image4'], 'rb') as f:
            imgs += [f.read()]
    post_header['imgs'] = imgs
    return post_header

init(wrap=False)

parser = ArgumentParser(add_help=True, description='Sosacheeque command-line client')
parser.add_argument('board', action='store', help='specify board')
board_parsers = parser.add_subparsers(help='board commands', dest='board_action')
thread_parser = board_parsers.add_parser('thread', help='list posts in thread')
thread_parser.add_argument('thread_num', action='store', help='specify thread')
thread_actions=thread_parser.add_subparsers(help='thread commands', dest='thread_action')
post_thread_parser = thread_actions.add_parser('post', help='post from command-line')
post_thread_parser.add_argument('-c', '--comment', action='store', help='your comment', required=True)
post_thread_parser.add_argument('-n', '--name', action='store', help="your mom's name")
post_thread_parser.add_argument('-s', '--subject', action='store', help='subject of the comment')
post_thread_parser.add_argument('-m', '--email', action='store', help='specify your e-mail')
post_thread_parser.add_argument('-i', '--image', action='append', type=FileType('rb'), help='attach an image')
post_thread_parser.add_argument('-q', '--quote', action='store', help='answer to', default=None)
file_thread_parser = thread_actions.add_parser('file', help='post from file')
file_thread_parser.add_argument('file_name', action='store', type=FileType('rt'), help='file name with post content')
editor_thread_parser = thread_actions.add_parser('editor', help='post using external editor')
editor_thread_parser.add_argument('-q', '--quote', action='store', help='answer to', default=None)
                   
args = parser.parse_args()

if args.board_action == 'thread':
    if args.thread_action == 'file':
        p = parse_post(args.file_name)
        if p:
            (captcha_value, captcha_id) = resolve_captcha()
            res = post(args.board, args.thread_num, p['comment'], captcha_id, captcha_value, subject=p['subject'], name=p['name'], email=p['email'], images=p['imgs'])
            sys.exit(0) if res else sys.exit(1)
        else:
            print("Error parsing post file")
            sys.exit(1)
    elif args.thread_action == 'editor':
        _, fn = mkstemp(prefix='sosuch')
        with open(fn, 'wt') as f:
            f.write(POST_TEMPLATE)
            if args.quote:
                f.write('>>' + args.quote + '\n')
        res = call([EDITOR, fn]) 
        if res == 0:
            with open(fn, 'rt') as f:
                p = parse_post(f)
                if p:
                    if p['comment'].strip() == '' and p['imgs'] == []:
                        print('Post is empty, draft saved to %s' % fn)
                        sys.exit(1)
                    (captcha_value, captcha_id) = resolve_captcha()
                    res = post(args.board, args.thread_num, p['comment'], captcha_id, captcha_value, subject=p['subject'], name=p['name'], email=p['email'], images=p['imgs'])
                    if res:
                        os.remove(fn)
                    else:
                        print('Error posting file, draft saved to %s' % fn)
                        sys.exit(1)
                else:
                    print('Error parsing post file, draft saved to %s' % fn)
                    sys.exit(1)
        else:
            print('Aborting post, draft saved to %s' % fn)
            sys.exit(res)
    elif args.thread_action == 'post':
        imgs = [i.read() for i in args.image] if args.image else None
        (captcha_value, captcha_id) = resolve_captcha()
        comment += '>>' + args.quote + '\n' + args.comment
        res = post(args.board, args.thread_num, comment, captcha_id, captcha_value, subject=args.subject, name=args.name, email=args.email, images=imgs)
        sys.exit(0) if res else sys.exit(1)
    else:
        posts(args.board, args.thread_num)
else:
    threads(args.board)
