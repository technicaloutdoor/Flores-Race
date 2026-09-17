// A tiny, deliberately narrow markdown renderer for section/POI `story` text (ARCHITECTURE.md
// §7.3). It supports exactly: paragraphs, **bold**, *italic*/_italic_, [links](url), and `- `/`1. `
// lists. Everything else is left as literal text.
//
// Safety comes from never building HTML strings: `parseMarkdown` produces a plain data tree (no
// DOM, so it's unit-testable in a Node test environment with no DOM available), and `renderMarkdown`
// turns that tree into DOM nodes using `createElement`/`createTextNode` only — there is no `innerHTML`
// anywhere in this file, so unrecognised syntax (including something that looks like a tag, e.g.
// "<script>") can only ever end up as inert text content, never as markup.

export type MdInline =
  | { type: 'text'; value: string }
  | { type: 'strong'; children: MdInline[] }
  | { type: 'em'; children: MdInline[] }
  | { type: 'link'; href: string; children: MdInline[] };

export type MdBlock =
  | { type: 'paragraph'; children: MdInline[] }
  | { type: 'list'; ordered: boolean; items: MdInline[][] };

const BULLET_RE = /^[-*]\s+(.*)$/;
const ORDERED_RE = /^\d+[.)]\s+(.*)$/;

/** Only http(s)/mailto links render as clickable anchors; anything else (in particular
 * `javascript:`) renders as its plain text instead. */
function isSafeHref(href: string): boolean {
  return /^(https?:|mailto:)/i.test(href.trim());
}

const INLINE_RE =
  /\*\*([^*]+)\*\*|\*([^*]+)\*|_([^_]+)_|\[([^\]]+)\]\(([^)\s]+)\)/g;

/** Splits one line/item of text into inline nodes. Recurses into matched spans, so a link's visible
 * text can itself contain bold/italic, and a bold/italic span can itself contain a link — each
 * recursive call only ever sees a strictly shorter string, so this always terminates. (Star-delimited
 * spans can't nest inside each other — `**bold *and* italic**` — because both share the `*`
 * delimiter and the content class excludes it; an acceptable limit for a *tiny* renderer.)
 *
 * Uses `matchAll` rather than a manual `exec` loop deliberately: `matchAll` clones the regex
 * internally, so a recursive call (which shares the same module-level `INLINE_RE` constant) can't
 * clobber an outer call's iteration position the way reusing one `/g` regex's mutable `lastIndex`
 * across reentrant calls would. */
export function parseInline(text: string): MdInline[] {
  const nodes: MdInline[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(INLINE_RE)) {
    if (match.index > lastIndex) {
      nodes.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    const [, bold, italicStar, italicUnderscore, linkText, linkHref] = match;
    if (bold !== undefined) {
      nodes.push({ type: 'strong', children: parseInline(bold) });
    } else if (italicStar !== undefined) {
      nodes.push({ type: 'em', children: parseInline(italicStar) });
    } else if (italicUnderscore !== undefined) {
      nodes.push({ type: 'em', children: parseInline(italicUnderscore) });
    } else if (linkText !== undefined && linkHref !== undefined) {
      if (isSafeHref(linkHref)) {
        nodes.push({ type: 'link', href: linkHref, children: parseInline(linkText) });
      } else {
        // Unsafe scheme: keep the visible text, drop the link wrapper entirely.
        nodes.push(...parseInline(linkText));
      }
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    nodes.push({ type: 'text', value: text.slice(lastIndex) });
  }
  return nodes;
}

/** Splits markdown source into blocks (blank-line-separated), classifying each as a bullet list,
 * an ordered list, or a paragraph. A block is a list only when *every* non-empty line matches the
 * same list marker; otherwise (including a block that mixes bullets and prose) it is one paragraph
 * with internal line breaks folded to spaces. */
export function parseMarkdown(source: string): MdBlock[] {
  const trimmed = source.trim();
  if (!trimmed) return [];

  const blocks = trimmed.split(/\n{2,}/);
  const result: MdBlock[] = [];

  for (const rawBlock of blocks) {
    const lines = rawBlock
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) continue;

    const bulletMatches = lines.map((l) => BULLET_RE.exec(l));
    if (bulletMatches.every((m): m is RegExpExecArray => m !== null)) {
      result.push({
        type: 'list',
        ordered: false,
        items: bulletMatches.map((m) => parseInline(m[1] ?? '')),
      });
      continue;
    }

    const orderedMatches = lines.map((l) => ORDERED_RE.exec(l));
    if (orderedMatches.every((m): m is RegExpExecArray => m !== null)) {
      result.push({
        type: 'list',
        ordered: true,
        items: orderedMatches.map((m) => parseInline(m[1] ?? '')),
      });
      continue;
    }

    result.push({ type: 'paragraph', children: parseInline(lines.join(' ')) });
  }

  return result;
}

function inlineToDom(nodes: MdInline[]): DocumentFragment {
  const frag = document.createDocumentFragment();
  for (const node of nodes) {
    switch (node.type) {
      case 'text':
        frag.appendChild(document.createTextNode(node.value));
        break;
      case 'strong': {
        const el = document.createElement('strong');
        el.appendChild(inlineToDom(node.children));
        frag.appendChild(el);
        break;
      }
      case 'em': {
        const el = document.createElement('em');
        el.appendChild(inlineToDom(node.children));
        frag.appendChild(el);
        break;
      }
      case 'link': {
        const a = document.createElement('a');
        a.href = node.href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.appendChild(inlineToDom(node.children));
        frag.appendChild(a);
        break;
      }
    }
  }
  return frag;
}

function blockToDom(block: MdBlock): HTMLElement {
  if (block.type === 'paragraph') {
    const p = document.createElement('p');
    p.appendChild(inlineToDom(block.children));
    return p;
  }
  const list = document.createElement(block.ordered ? 'ol' : 'ul');
  for (const item of block.items) {
    const li = document.createElement('li');
    li.appendChild(inlineToDom(item));
    list.appendChild(li);
  }
  return list;
}

/** Renders markdown source into a `DocumentFragment` ready to append to a `.story` container. */
export function renderMarkdown(source: string): DocumentFragment {
  const frag = document.createDocumentFragment();
  for (const block of parseMarkdown(source)) frag.appendChild(blockToDom(block));
  return frag;
}
