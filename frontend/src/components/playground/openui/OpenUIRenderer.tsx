import './noDevtools'
import { useMemo } from 'react'
import { Renderer, type ActionEvent } from '@openuidev/react-lang'
import { ThemeProvider } from '@openuidev/react-ui'
import '@openuidev/react-ui/components.css'
import { useThemeStore } from '../../../store/themeStore'
import { playgroundLibrary } from './library'
import { inspectOpenUI } from './inspect'

export interface OpenUIRendererProps {
  content: string
  streaming: boolean
  /** Sends a follow-up message, as if the user typed it. Absent when chatting is not allowed. */
  onFollowUp?: (message: string) => void
  /** Shown instead of the UI when the reply cannot be rendered. */
  onInvalid: (reason: string) => React.ReactNode
}

const SCOPE = 'mk-openui'

function safeHttpUrl(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  try {
    const url = new URL(raw)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

function flattenFormState(state: Record<string, unknown> | undefined): Record<string, unknown> | null {
  // OpenUI keys form state as { formName: { field: { value } } }; the model
  // only needs field -> value.
  if (!state) return null
  const values: Record<string, unknown> = {}
  for (const fields of Object.values(state)) {
    if (!fields || typeof fields !== 'object') continue
    for (const [name, field] of Object.entries(fields as Record<string, unknown>)) {
      values[name] =
        field && typeof field === 'object' && 'value' in field ? (field as { value: unknown }).value : field
    }
  }
  return Object.keys(values).length > 0 ? values : null
}

/**
 * Renders an OpenUI reply with Mokinjay's trimmed component library.
 *
 * The generated UI gets no tools, data access or credentials: there is no
 * `toolProvider`, so Query/Mutation statements stay inert. Of the actions,
 * only two reach the app and both are re-checked here, not trusted from the
 * model: a follow-up message (sent through the normal chat path, and only
 * when idle) and opening an http(s) link after the user confirms it.
 */
export default function OpenUIRenderer({ content, streaming, onFollowUp, onInvalid }: OpenUIRendererProps) {
  const dark = useThemeStore((state) => state.dark)
  const inspection = useMemo(() => inspectOpenUI(content, streaming), [content, streaming])

  if (inspection.status === 'invalid') return <>{onInvalid(inspection.reason ?? 'Invalid OpenUI.')}</>

  const handleAction = (event: ActionEvent) => {
    if (event.type === 'continue_conversation') {
      const label = (event.humanFriendlyMessage ?? '').trim()
      const values = flattenFormState(event.formState)
      // Form answers travel as plain text in the user's turn; the model never
      // sees OpenUI's stored-message markers.
      const message = values ? `${label}\n\nForm values: ${JSON.stringify(values)}` : label
      if (message && onFollowUp && !streaming) onFollowUp(message)
      return
    }
    if (event.type === 'open_url') {
      const url = safeHttpUrl((event.params as { url?: unknown } | undefined)?.url)
      if (url && window.confirm(`Open this link in a new tab?\n\n${url}`)) {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    }
    // Anything else (custom actions) is ignored: the library defines none.
  }

  return (
    <div className={SCOPE}>
      <ThemeProvider mode={dark ? 'dark' : 'light'} cssSelector={`.${SCOPE}`}>
        <Renderer
          library={playgroundLibrary}
          response={content}
          isStreaming={streaming}
          onAction={handleAction}
          onError={() => {}}
        />
      </ThemeProvider>
      {inspection.issues.length > 0 && (
        <details className="mt-1 text-[11px] text-status-warning">
          <summary className="cursor-pointer">
            {inspection.issues.length === 1
              ? '1 part was skipped'
              : `${inspection.issues.length} parts were skipped`}
          </summary>
          <ul className="mt-1 list-disc pl-4 text-ink-muted">
            {inspection.issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
