import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, Filter, Globe, Plus, RefreshCw, X } from 'lucide-react'
import { listAgents } from '../../api/agents'
import { listApiKeys } from '../../api/apiKeys'
import type { ActivitySource } from '../../api/activity'
import Menu, { MenuItem } from '../ui/Menu'
import {
  CALENDAR_PRESETS,
  ROLLING_PRESETS,
  rangeLabel,
  rangeShort,
  type ActivityFilterState,
} from '../../lib/activityFilters'
import { cn } from '../../lib/utils'

type Dimension = 'apiKeyId' | 'agentId' | 'source' | 'model' | 'status'

const DIMENSION_LABEL: Record<Dimension, string> = {
  apiKeyId: 'API key',
  agentId: 'Agent',
  source: 'Source',
  model: 'Model',
  status: 'Status',
}

const SOURCE_LABEL: Record<ActivitySource, string> = {
  api: 'API',
  playground: 'Playground',
  workflow: 'Workflow',
}

const STATUS_OPTIONS = ['completed', 'failed', 'cancelled']

interface Option {
  value: string
  label: string
}

/** `datetime-local` wants "YYYY-MM-DDTHH:mm" in local time. */
function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function FilterBar({
  workspaceId,
  filters,
  activeCount,
  onChange,
  onClear,
  onRefresh,
  modelOptions,
  showStatus = false,
  refreshing = false,
}: {
  workspaceId: string | null
  filters: ActivityFilterState
  activeCount: number
  onChange: (patch: Partial<ActivityFilterState>) => void
  onClear: () => void
  onRefresh: () => void
  modelOptions: string[]
  showStatus?: boolean
  refreshing?: boolean
}) {
  const [keys, setKeys] = useState<Option[]>([])
  const [agents, setAgents] = useState<Option[]>([])
  const [pending, setPending] = useState<Dimension | null>(null)
  const [customOpen, setCustomOpen] = useState(filters.range === 'custom')
  const [customFrom, setCustomFrom] = useState(toLocalInput(filters.from))
  const [customTo, setCustomTo] = useState(toLocalInput(filters.to))

  useEffect(() => {
    if (!workspaceId) return
    listApiKeys(workspaceId)
      .then((rows) => setKeys(rows.map((key) => ({ value: key.id, label: `${key.name} (${key.prefix.slice(-3)})` }))))
      .catch(() => {})
    listAgents(workspaceId)
      .then((rows) => setAgents(rows.map((agent) => ({ value: agent.id, label: agent.name }))))
      .catch(() => {})
  }, [workspaceId])

  const optionsFor = useMemo<Record<Dimension, Option[]>>(() => {
    // A filter that came in through the URL may name a key or model the lists
    // above do not hold (revoked key, model outside the top few). Keep its
    // value selectable so the chip never renders blank.
    const withCurrent = (options: Option[], current: string | null, label?: string) =>
      current && !options.some((option) => option.value === current)
        ? [...options, { value: current, label: label ?? current }]
        : options
    return {
      apiKeyId: withCurrent(keys, filters.apiKeyId, 'Unknown key'),
      agentId: withCurrent(agents, filters.agentId, 'Unknown agent'),
      source: (Object.keys(SOURCE_LABEL) as ActivitySource[]).map((value) => ({
        value,
        label: SOURCE_LABEL[value],
      })),
      model: withCurrent(
        modelOptions.map((value) => ({ value, label: value })),
        filters.model
      ),
      status: STATUS_OPTIONS.map((value) => ({ value, label: value })),
    }
  }, [keys, agents, modelOptions, filters.apiKeyId, filters.agentId, filters.model])

  const available: Dimension[] = (
    ['apiKeyId', 'agentId', 'source', 'model', ...(showStatus ? ['status'] : [])] as Dimension[]
  ).filter((dimension) => !filters[dimension] && pending !== dimension)

  const active = (['apiKeyId', 'agentId', 'source', 'model', 'status'] as Dimension[]).filter(
    (dimension) => filters[dimension] && (dimension !== 'status' || showStatus)
  )
  const chips: Dimension[] = pending ? [...active, pending] : active

  const applyCustom = () => {
    if (!customFrom || !customTo) return
    const from = new Date(customFrom)
    const to = new Date(customTo)
    if (!(from < to)) return
    onChange({ range: 'custom', from: from.toISOString(), to: to.toISOString() })
    setCustomOpen(false)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button
          onClick={onRefresh}
          aria-label="Refresh"
          title="Refresh"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line text-ink-muted hover:text-ink"
        >
          <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} aria-hidden />
        </button>

        <button
          onClick={() => onChange({ tz: filters.tz === 'utc' ? 'local' : 'utc' })}
          title="Switch timezone"
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-[13px] text-ink-muted hover:text-ink"
        >
          <Globe className="h-4 w-4" aria-hidden />
          {filters.tz === 'utc' ? 'UTC' : 'Local time'}
        </button>

        <Menu
          trigger={
            <button
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-[13px] text-ink-muted hover:text-ink"
              aria-label="Filters"
            >
              <Filter className="h-4 w-4" aria-hidden />
              {activeCount > 0 && (
                <span className="rounded-full bg-surface-muted px-1.5 font-mono text-[11px] text-ink">
                  {activeCount}
                </span>
              )}
            </button>
          }
        >
          {available.length === 0 && (
            <p className="px-3 py-2 text-[12.5px] text-ink-subtle">All filters in use</p>
          )}
          {available.map((dimension) => (
            <MenuItem key={dimension} onClick={() => setPending(dimension)}>
              {DIMENSION_LABEL[dimension]}
            </MenuItem>
          ))}
        </Menu>

        <Menu
          trigger={
            <button
              className="inline-flex h-9 min-w-52 items-center gap-2 rounded-lg border border-line px-3 text-[13px] text-ink"
              aria-label="Time range"
            >
              <span className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                {rangeShort(filters.range)}
              </span>
              <span className="flex-1 text-left">{rangeLabel(filters.range)}</span>
              <ChevronDown className="h-4 w-4 text-ink-subtle" aria-hidden />
            </button>
          }
          className="w-72"
        >
          {ROLLING_PRESETS.map((preset) => (
            <MenuItem key={preset.id} onClick={() => onChange({ range: preset.id })}>
              <span className="w-9 rounded bg-surface-muted px-1.5 py-0.5 text-center font-mono text-[11px] text-ink-muted">
                {preset.short}
              </span>
              <span className="flex-1">{preset.label}</span>
              {filters.range === preset.id && <Check className="h-4 w-4 text-ink" aria-hidden />}
            </MenuItem>
          ))}
          <div className="my-1 border-t border-line" />
          <div className="grid grid-cols-2">
            {CALENDAR_PRESETS.map((preset) => (
              <MenuItem key={preset.id} onClick={() => onChange({ range: preset.id })}>
                <span className="flex-1">{preset.label}</span>
                {filters.range === preset.id && <Check className="h-4 w-4 text-ink" aria-hidden />}
              </MenuItem>
            ))}
          </div>
          <div className="my-1 border-t border-line" />
          <MenuItem onClick={() => setCustomOpen(true)}>Custom range…</MenuItem>
        </Menu>
      </div>

      {customOpen && (
        <div className="flex flex-wrap items-end justify-end gap-2 rounded-xl border border-line bg-surface p-3">
          <label className="text-[12px] text-ink-muted">
            From
            <input
              type="datetime-local"
              value={customFrom}
              onChange={(event) => setCustomFrom(event.target.value)}
              className="ml-2 rounded-lg border border-line bg-surface-muted px-2 py-1.5 text-[13px] text-ink"
            />
          </label>
          <label className="text-[12px] text-ink-muted">
            To
            <input
              type="datetime-local"
              value={customTo}
              onChange={(event) => setCustomTo(event.target.value)}
              className="ml-2 rounded-lg border border-line bg-surface-muted px-2 py-1.5 text-[13px] text-ink"
            />
          </label>
          <button
            onClick={applyCustom}
            disabled={!customFrom || !customTo || !(new Date(customFrom) < new Date(customTo))}
            className="h-8 rounded-lg bg-primary px-3 text-[13px] font-medium text-primary-fg disabled:opacity-50"
          >
            Apply
          </button>
          <button onClick={() => setCustomOpen(false)} className="h-8 px-2 text-[13px] text-ink-muted hover:text-ink">
            Cancel
          </button>
        </div>
      )}

      <div
        className="flex min-h-11 flex-wrap items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2"
        data-testid="filter-row"
      >
        {chips.length === 0 && <span className="text-[12.5px] text-ink-subtle">No filters applied</span>}
        {chips.map((dimension) => {
          const value = filters[dimension] ?? ''
          const options = optionsFor[dimension]
          return (
            <span
              key={dimension}
              className="inline-flex items-center overflow-hidden rounded-md border border-line bg-surface-muted text-[12.5px]"
              data-testid={`chip-${dimension}`}
            >
              <span className="px-2 py-1 text-ink-muted">{DIMENSION_LABEL[dimension]}</span>
              <span className="border-x border-line px-1.5 py-1 text-ink-subtle">is</span>
              <select
                value={value}
                autoFocus={pending === dimension}
                aria-label={`${DIMENSION_LABEL[dimension]} filter`}
                onChange={(event) => {
                  const next = event.target.value || null
                  setPending(null)
                  onChange({ [dimension]: next } as Partial<ActivityFilterState>)
                }}
                className="max-w-56 bg-transparent px-2 py-1 text-ink focus:outline-none"
              >
                {!value && <option value="">Select…</option>}
                {options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button
                aria-label={`Clear ${DIMENSION_LABEL[dimension]} filter`}
                onClick={() => {
                  if (pending === dimension) setPending(null)
                  onChange({ [dimension]: null } as Partial<ActivityFilterState>)
                }}
                className="px-1.5 py-1 text-ink-subtle hover:text-ink"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </span>
          )
        })}
        {available.length > 0 && (
          <Menu
            align="left"
            trigger={
              <button
                aria-label="Add filter"
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[12.5px] text-ink-muted hover:text-ink"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden /> Filter
              </button>
            }
          >
            {available.map((dimension) => (
              <MenuItem key={dimension} onClick={() => setPending(dimension)}>
                {DIMENSION_LABEL[dimension]}
              </MenuItem>
            ))}
          </Menu>
        )}
        {(activeCount > 0 || pending) && (
          <button
            onClick={() => {
              setPending(null)
              onClear()
            }}
            className="ml-auto text-[12.5px] text-ink-muted hover:text-ink"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
