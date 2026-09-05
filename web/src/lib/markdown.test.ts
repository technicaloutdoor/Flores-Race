import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from './markdown.ts';

describe('parseInline', () => {
  it('parses plain text as a single text node', () => {
    expect(parseInline('hello world')).toEqual([{ type: 'text', value: 'hello world' }]);
  });

  it('parses **bold** spans', () => {
    expect(parseInline('a **bold** word')).toEqual([
      { type: 'text', value: 'a ' },
      { type: 'strong', children: [{ type: 'text', value: 'bold' }] },
      { type: 'text', value: ' word' },
    ]);
  });

  it('parses *italic* and _italic_ spans', () => {
    expect(parseInline('*one* and _two_')).toEqual([
      { type: 'em', children: [{ type: 'text', value: 'one' }] },
      { type: 'text', value: ' and ' },
      { type: 'em', children: [{ type: 'text', value: 'two' }] },
    ]);
  });

  it('parses [text](url) links', () => {
    expect(parseInline('see [Wae Rebo](https://example.org/wae-rebo) here')).toEqual([
      { type: 'text', value: 'see ' },
      {
        type: 'link',
        href: 'https://example.org/wae-rebo',
        children: [{ type: 'text', value: 'Wae Rebo' }],
      },
      { type: 'text', value: ' here' },
    ]);
  });

  it('drops the link wrapper for an unsafe href scheme, keeping the visible text', () => {
    expect(parseInline('[click me](javascript:doEvil)')).toEqual([
      { type: 'text', value: 'click me' },
    ]);
  });

  it('leaves unmatched/unclosed markers as literal text', () => {
    expect(parseInline('a **unclosed bold')).toEqual([
      { type: 'text', value: 'a **unclosed bold' },
    ]);
  });

  it('never interprets stray angle brackets as markup (no HTML string building at all)', () => {
    expect(parseInline('<script>alert(1)</script>')).toEqual([
      { type: 'text', value: '<script>alert(1)</script>' },
    ]);
  });

  it('recurses into a bold span so a link nested inside bold still works', () => {
    expect(parseInline('**see [Wae Rebo](https://example.org) here**')).toEqual([
      {
        type: 'strong',
        children: [
          { type: 'text', value: 'see ' },
          {
            type: 'link',
            href: 'https://example.org',
            children: [{ type: 'text', value: 'Wae Rebo' }],
          },
          { type: 'text', value: ' here' },
        ],
      },
    ]);
  });

  it('recurses into link text so bold inside a link still works', () => {
    expect(parseInline('[**Wae Rebo**](https://example.org)')).toEqual([
      {
        type: 'link',
        href: 'https://example.org',
        children: [{ type: 'strong', children: [{ type: 'text', value: 'Wae Rebo' }] }],
      },
    ]);
  });
});

describe('parseMarkdown', () => {
  it('parses a single line as one paragraph', () => {
    expect(parseMarkdown('Hello world.')).toEqual([
      { type: 'paragraph', children: [{ type: 'text', value: 'Hello world.' }] },
    ]);
  });

  it('splits blank-line-separated text into separate paragraphs', () => {
    const blocks = parseMarkdown('First paragraph.\n\nSecond paragraph.');
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toEqual({
      type: 'paragraph',
      children: [{ type: 'text', value: 'First paragraph.' }],
    });
    expect(blocks[1]).toEqual({
      type: 'paragraph',
      children: [{ type: 'text', value: 'Second paragraph.' }],
    });
  });

  it('folds internal line breaks within one paragraph into spaces', () => {
    const blocks = parseMarkdown('Line one\nline two');
    expect(blocks).toEqual([
      { type: 'paragraph', children: [{ type: 'text', value: 'Line one line two' }] },
    ]);
  });

  it('parses a block of "- " lines as an unordered list', () => {
    const blocks = parseMarkdown('- first\n- second\n- third');
    expect(blocks).toEqual([
      {
        type: 'list',
        ordered: false,
        items: [
          [{ type: 'text', value: 'first' }],
          [{ type: 'text', value: 'second' }],
          [{ type: 'text', value: 'third' }],
        ],
      },
    ]);
  });

  it('parses a block of "1. " lines as an ordered list', () => {
    const blocks = parseMarkdown('1. first\n2. second');
    expect(blocks).toEqual([
      {
        type: 'list',
        ordered: true,
        items: [[{ type: 'text', value: 'first' }], [{ type: 'text', value: 'second' }]],
      },
    ]);
  });

  it('treats a block with mixed bullet and plain lines as one paragraph, not a list', () => {
    const blocks = parseMarkdown('- almost a list\nbut not quite');
    expect(blocks).toHaveLength(1);
    expect(blocks[0]!.type).toBe('paragraph');
  });

  it('runs inline parsing inside list items', () => {
    const blocks = parseMarkdown('- **go** water at km 12\n- *no-go* rockfall');
    expect(blocks).toEqual([
      {
        type: 'list',
        ordered: false,
        items: [
          [
            { type: 'strong', children: [{ type: 'text', value: 'go' }] },
            { type: 'text', value: ' water at km 12' },
          ],
          [
            { type: 'em', children: [{ type: 'text', value: 'no-go' }] },
            { type: 'text', value: ' rockfall' },
          ],
        ],
      },
    ]);
  });

  it('returns [] for empty or whitespace-only input', () => {
    expect(parseMarkdown('')).toEqual([]);
    expect(parseMarkdown('   \n  \n ')).toEqual([]);
  });

  it('ignores an unsupported block construct (e.g. a heading) as plain paragraph text', () => {
    const blocks = parseMarkdown('# Not a heading here');
    expect(blocks).toEqual([
      { type: 'paragraph', children: [{ type: 'text', value: '# Not a heading here' }] },
    ]);
  });
});
