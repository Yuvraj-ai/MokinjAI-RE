import { lazy, Suspense, useState } from 'react'
import { CircleAlert } from 'lucide-react'
import type { OutputFormat } from '../../api/agents'
import { OUTPUT_FORMAT_LABELS } from '../../lib/outputFormat'
import { cn } from '../../lib/utils'
import MarkdownRenderer from './MarkdownRenderer'
import RenderBoundary from './RenderBoundary'

// OpenUI ships about 1 MB gzipped, so it loads only when a reply needs it.
const OpenUIRenderer = lazy(() => import('./openui/OpenUIRenderer'))

interface AgentResponseRendererProps {
  format: OutputFormat
  content: string
  streaming: boolean
  onFollowUp?: (message: string) => void
}

function RawText({ content }: { content: string }) {
  return (
    <pre className="whitespace-pre-wrap break-words rounded-lg border border-line bg-surface-muted px-3 py-2 font-mono text-[11.5px] text-ink">
      {content}
    </pre>
  )
}

/**
 * One assistant reply. `format` is how the reply was generated; Raw/Rendered
 * only changes how it is displayed here and never re-runs the model. The raw
 * text is always the stored reply, so nothing is lost when rendering fails.
 */
export default function AgentResponseRenderer({
  format,
  content,
  streaming,
  onFollowUp,
}: AgentResponseRendererProps) {
  const [raw, setRaw] = useState(false)
  const [asMarkdown, setAsMarkdown] = useState(false)

  const failure = (reason: string) => (
    <div className="rounded-lg border border-status-warning/40 bg-status-warning-soft px-3 py-2 text-[12.5px]">
      <p className="flex items-center gap-1.5 font-medium text-status-warning">
        <CircleAlert className="h-3.5 w-3.5" aria-hidden /> Couldn't render this as UI
      </p>
      <p className="mt-0.5 text-ink-muted">{reason} The original reply is kept.</p>
      <div className="mt-1.5 flex gap-3 text-[11.5px]">
        <button type="button" className="text-ink underline underline-offset-2" onClick={() => setRaw(true)}>
          Show raw reply
        </button>
        <button type="button" className="text-ink underline underline-offset-2" onClick={() => setAsMarkdown(true)}>
          Show as Markdown
        </button>
      </div>
    </div>
  )

  let body: React.ReactNode
  if (raw) {
    body = <RawText content={content} />
  } else if (format === 'openui' && !asMarkdown) {
    body = (
      <RenderBoundary fallback={failure('The UI renderer failed on this reply.')}>
        <Suspense fallback={<p className="px-1 py-1 text-[12px] text-ink-subtle">Loading UI renderer…</p>}>
          <OpenUIRenderer
            content={content}
            streaming={streaming}
            onFollowUp={onFollowUp}
            onInvalid={failure}
          />
        </Suspense>
      </RenderBoundary>
    )
  } else {
    body = <MarkdownRenderer content={content} streaming={streaming} />
  }

  return (
    <div className="min-w-0">
      {body}
      {!streaming && (
        <div className="mx-1 mt-0.5 flex items-center gap-2 text-[10.5px] text-ink-subtle">
          <div role="group" aria-label="Display" className="inline-flex gap-1">
            {(['rendered', 'raw'] as const).map((mode) => {
              const active = (mode === 'raw') === raw
              return (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setRaw(mode === 'raw')}
                  className={cn('hover:text-ink', active && 'font-semibold text-ink')}
                >
                  {mode === 'raw' ? 'Raw' : 'Rendered'}
                </button>
              )
            })}
          </div>
          <span aria-hidden>·</span>
          <span>{OUTPUT_FORMAT_LABELS[format]}</span>
          {asMarkdown && !raw && (
            <button type="button" className="hover:text-ink" onClick={() => setAsMarkdown(false)}>
              · back to UI
            </button>
          )}
        </div>
      )}
    </div>
  )
}
