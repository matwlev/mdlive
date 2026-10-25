import html
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import quote

import nh3
from markdown_it import MarkdownIt

from .config import remote

MARKDOWN = MarkdownIt('commonmark', {'html': True})


def slug(text, level):
    cleaned = ''.join(c for c in text.lower() if c.isalnum() or c.isspace())
    return re.sub(r'\s+', '-', cleaned).strip('-') or 'section'


class Tree(HTMLParser):
    """Parse the sanitizer's balanced HTML without interpreting it as XML."""
    void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = ET.Element('div')
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = ET.SubElement(self.stack[-1], tag, dict(attrs))
        if tag not in self.void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        parent = self.stack[-1]
        if len(parent):
            parent[-1].tail = (parent[-1].tail or '') + data
        else:
            parent.text = (parent.text or '') + data


def render(source, generator=None):
    attrs = {tag: set(names) for tag, names in nh3.ALLOWED_ATTRIBUTES.items()}
    attrs['*'] = {'id'}
    safe = nh3.clean(MARKDOWN.render(source), attributes=attrs)
    root = Tree(safe).root
    headings = []
    heading_nodes = [n for n in root.iter() if n.tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}]
    used = {'mdlive-content'}
    for node in root.iter():
        if node not in heading_nodes and 'id' in node.attrib:
            candidate = node.attrib['id']
            if candidate in used:
                del node.attrib['id']
            else:
                used.add(candidate)
    for node in heading_nodes:
        text = ''.join(node.itertext())
        level = int(node.tag[1])
        base = (generator or slug)(text, level)
        if not isinstance(base, str) or not base or any(c.isspace() for c in base):
            raise ValueError('Heading generator must return a nonempty string without whitespace')
        candidate, count = base, 0
        while candidate in used:
            count += 1
            candidate = f'{base}-{count}'
        used.add(candidate)
        node.set('id', candidate)
        headings.append(dict(id=candidate, text=text, level=level))
    output = html.escape(root.text or '') + ''.join(ET.tostring(n, encoding='unicode', method='html') for n in root)
    return output, headings


def json_script(value):
    return json.dumps(value, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def url_path(path, root):
    return '/' + quote(path.relative_to(root).as_posix(), safe='/')


def page(content, data, config, mapping, revision):
    def link(item):
        return item if remote(item) else mapping[item]
    styles, scripts = '', ''
    for layer in config.layers:
        styles += ''.join(f'<link rel="stylesheet" href="{html.escape(link(x), quote=True)}">' for x in layer['style_links'])
        styles += ''.join(f'<style>{x}</style>' for x in layer['styles'])
        scripts += ''.join(f'<script>{x}</script>' for x in layer['scripts'])
        scripts += ''.join(f'<script src="{html.escape(link(x), quote=True)}" onerror="console.error(\'Theme script failed\',this.src)"></script>' for x in layer['script_links'])
    # A document-relative base also handles a nested entry displayed at /.
    base = html.escape(data['currentPath'], quote=True)
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<base href="{base}"><title>mdlive</title>{styles}</head><body>'
            f'<main id="mdlive-content">{content}</main><script>window.mdlive={json_script(data)};'
            f'window.__mdliveRevision={json_script(revision)};</script>{scripts}'
            '<script src="/__mdlive/client.js"></script></body></html>')
