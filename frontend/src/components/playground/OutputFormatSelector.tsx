import type { AgentCapabilities, OutputFormat } from '../../api/agents'
import { cn } from '../../lib/utils'
import { OUTPUT_FORMAT_LABELS, openUiUnavailableReason } from '../../lib/outputFormat'

interface OutputFormatSelectorProps {
  value: OutputFormat
  available: OutputFormat[]
  capabilities: AgentCapabilities | null
  disabled?: boolean
  onChange: (format: OutputFormat) => void
}

const ALL: OutputFormat[] = ['markdown', 'openui']

/**
 * What the model is asked to generate for the next message. Separate from the
 * per-reply Raw/Rendered toggle, which only changes how a reply is displayed.
 */
export default function OutputFormatSelector({
  value,
  available,
  capabilities,
  disabled,
  onChange,
}: OutputFormatSelectorProps) {
  const openUiBlocked = !available.includes('openui')
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div
        role="radiogroup"
        aria-label="Output format for the next message"
        className="inline-flex w-fit overflow-hidden rounded-md border border-line text-[11.5px]"
      >
        {ALL.map((format) => {
          const allowed = available.includes(format)
          const selected = value === format
          return (
            <button
              key={format}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled || !allowed}
              title={!allowed && format === 'openui' ? openUiUnavailableReason(capabilities) : undefined}
              onClick={() => onChange(format)}
              className={cn(
                'px-2.5 py-1 transition-colors',
                selected
                  ? 'bg-primary text-primary-fg'
                  : allowed
                    ? 'bg-surface text-ink-muted hover:bg-surface-muted hover:text-ink'
                    : 'cursor-not-allowed bg-surface-muted text-ink-subtle line-through',
                disabled && allowed && !selected && 'opacity-60'
              )}
            >
              {OUTPUT_FORMAT_LABELS[format]}
            </button>
          )
        })}
      </div>
      {openUiBlocked && (
        <p className="text-[11px] text-status-warning">{openUiUnavailableReason(capabilities)}</p>
      )}
    </div>
  )
}
