import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ActivityQuery, ActivitySource } from '../api/activity'
import { listWorkspaces } from '../api/workspaces'

/**
 * Filter state shared by the Activity dashboard and Activity Logs. It lives in
 * the URL query string, so the API key page links straight to either with the
 * key already applied, and a filter set survives reload and sharing.
 */

export interface RangePreset {
  id: string
  short: string
  label: string
}

export const ROLLING_PRESETS: RangePreset[] = [
  { id: '15m', short: '15m', label: 'Past 15 Minutes' },
  { id: '30m', short: '30m', label: 'Past 30 Minutes' },
  { id: '1h', short: '1h', label: 'Past 1 Hour' },
  { id: '3h', short: '3h', label: 'Past 3 Hours' },
  { id: '1d', short: '1d', label: 'Past 24 Hours' },
  { id: '2d', short: '2d', label: 'Past 48 Hours' },
  { id: '1w', short: '1w', label: 'Past 1 Week' },
  { id: '1mo', short: '1mo', label: 'Past 1 Month' },
  { id: '1y', short: '1y', label: 'Past 1 Year' },
]

export const CALENDAR_PRESETS: RangePreset[] = [
  { id: 'today', short: 'td', label: 'Today' },
  { id: 'yesterday', short: 'yd', label: 'Yesterday' },
  { id: 'this-week', short: 'tw', label: 'This Week' },
  { id: 'prev-week', short: 'pw', label: 'Prev Week' },
  { id: 'this-month', short: 'tm', label: 'This Month' },
  { id: 'prev-month', short: 'pm', label: 'Prev Month' },
  { id: 'this-year', short: 'ty', label: 'This Year' },
  { id: 'prev-year', short: 'py', label: 'Prev Year' },
]

export const DEFAULT_RANGE = '1mo'
const MINUTE = 60_000

const ROLLING_MS: Record<string, number> = {
  '15m': 15 * MINUTE,
  '30m': 30 * MINUTE,
  '1h': 60 * MINUTE,
  '3h': 180 * MINUTE,
  '1d': 24 * 60 * MINUTE,
  '2d': 48 * 60 * MINUTE,
  '1w': 7 * 24 * 60 * MINUTE,
  '1mo': 30 * 24 * 60 * MINUTE,
  '1y': 365 * 24 * 60 * MINUTE,
}

export type TzMode = 'local' | 'utc'

/** Calendar parts of `date` in the chosen timezone mode. */
function parts(date: Date, tz: TzMode) {
  return tz === 'utc'
    ? { y: date.getUTCFullYear(), m: date.getUTCMonth(), d: date.getUTCDate(), wd: date.getUTCDay() }
    : { y: date.getFullYear(), m: date.getMonth(), d: date.getDate(), wd: date.getDay() }
}

function make(y: number, m: number, d: number, tz: TzMode): Date {
  return tz === 'utc' ? new Date(Date.UTC(y, m, d)) : new Date(y, m, d)
}

export function resolveRange(
  range: string,
  tz: TzMode,
  custom: { from?: string | null; to?: string | null } = {},
  now: Date = new Date()
): { from: Date; to: Date } {
  if (range === 'custom' && custom.from && custom.to) {
    return { from: new Date(custom.from), to: new Date(custom.to) }
  }
  if (range in ROLLING_MS) {
    return { from: new Date(now.getTime() - ROLLING_MS[range]), to: now }
  }
  const { y, m, d, wd } = parts(now, tz)
  const mondayOffset = (wd + 6) % 7
  switch (range) {
    case 'today':
      return { from: make(y, m, d, tz), to: now }
    case 'yesterday':
      return { from: make(y, m, d - 1, tz), to: make(y, m, d, tz) }
    case 'this-week':
      return { from: make(y, m, d - mondayOffset, tz), to: now }
    case 'prev-week':
      return { from: make(y, m, d - mondayOffset - 7, tz), to: make(y, m, d - mondayOffset, tz) }
    case 'this-month':
      return { from: make(y, m, 1, tz), to: now }
    case 'prev-month':
      return { from: make(y, m - 1, 1, tz), to: make(y, m, 1, tz) }
    case 'this-year':
      return { from: make(y, 0, 1, tz), to: now }
    case 'prev-year':
      return { from: make(y - 1, 0, 1, tz), to: make(y, 0, 1, tz) }
    default:
      return resolveRange(DEFAULT_RANGE, tz, {}, now)
  }
}

export function rangeLabel(range: string): string {
  if (range === 'custom') return 'Custom range'
  return [...ROLLING_PRESETS, ...CALENDAR_PRESETS].find((p) => p.id === range)?.label ?? 'Past 1 Month'
}

export function rangeShort(range: string): string {
  if (range === 'custom') return '…'
  return [...ROLLING_PRESETS, ...CALENDAR_PRESETS].find((p) => p.id === range)?.short ?? '1mo'
}

export interface ActivityFilterState {
  range: string
  from: string | null
  to: string | null
  tz: TzMode
  apiKeyId: string | null
  agentId: string | null
  source: ActivitySource | null
  model: string | null
  status: string | null
}

const SOURCES: ActivitySource[] = ['api', 'playground', 'workflow']

export function parseFilters(params: URLSearchParams): ActivityFilterState {
  const source = params.get('source')
  return {
    range: params.get('range') || DEFAULT_RANGE,
    from: params.get('from'),
    to: params.get('to'),
    tz: params.get('tz') === 'utc' ? 'utc' : 'local',
    apiKeyId: params.get('api_key_id'),
    agentId: params.get('agent_id'),
    source: SOURCES.includes(source as ActivitySource) ? (source as ActivitySource) : null,
    model: params.get('model'),
    status: params.get('status'),
  }
}

export function localZoneName(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/** The request the backend understands. Recomputed when the filters change. */
export function toQuery(filters: ActivityFilterState, now: Date = new Date()): ActivityQuery {
  const { from, to } = resolveRange(filters.range, filters.tz, { from: filters.from, to: filters.to }, now)
  return {
    from: from.toISOString(),
    to: to.toISOString(),
    tz: filters.tz === 'utc' ? 'UTC' : localZoneName(),
    api_key_id: filters.apiKeyId ?? undefined,
    agent_id: filters.agentId ?? undefined,
    source: filters.source ?? undefined,
    model: filters.model ?? undefined,
    status: filters.status ?? undefined,
  }
}

const QUERY_KEYS = {
  range: 'range',
  from: 'from',
  to: 'to',
  tz: 'tz',
  apiKeyId: 'api_key_id',
  agentId: 'agent_id',
  source: 'source',
  model: 'model',
  status: 'status',
} as const

/** A link to another activity page that keeps the filters in `filters`. */
export function withFilters(path: string, filters: Partial<ActivityFilterState>): string {
  const params = new URLSearchParams()
  for (const [field, key] of Object.entries(QUERY_KEYS) as [keyof ActivityFilterState, string][]) {
    const value = filters[field]
    if (!value) continue
    if (field === 'tz' && value === 'local') continue
    if (field === 'range' && value === DEFAULT_RANGE) continue
    params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `${path}?${query}` : path
}

export function useActivityFilters() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => parseFilters(params), [params])

  // Rolling ranges ("past hour") move; the window is re-anchored when the user
  // acts, not on a timer, so charts do not shift under the cursor.
  const [anchor, setAnchor] = useState(() => Date.now())

  const update = useCallback(
    (patch: Partial<ActivityFilterState>) => {
      setAnchor(Date.now())
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          for (const [field, value] of Object.entries(patch) as [keyof ActivityFilterState, string | null][]) {
            const key = QUERY_KEYS[field]
            // The default range and local time are not worth a URL parameter.
            const isDefault =
              (field === 'range' && value === DEFAULT_RANGE) || (field === 'tz' && value === 'local')
            if (!value || isDefault) next.delete(key)
            else next.set(key, value)
          }
          if (patch.range && patch.range !== 'custom') {
            next.delete('from')
            next.delete('to')
          }
          next.delete('page')
          return next
        },
        { replace: true }
      )
    },
    [setParams]
  )

  const clear = useCallback(() => {
    update({ apiKeyId: null, agentId: null, source: null, model: null, status: null })
  }, [update])

  const activeCount = [filters.apiKeyId, filters.agentId, filters.source, filters.model, filters.status].filter(
    Boolean
  ).length

  const query = useMemo(() => toQuery(filters, new Date(anchor)), [filters, anchor])
  const refresh = useCallback(() => setAnchor(Date.now()), [])

  return { filters, query, update, clear, activeCount, refresh, params, setParams }
}

/** The first workspace, as every other page in the app uses. */
export function useWorkspaceId(): string | null {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    listWorkspaces()
      .then((workspaces) => {
        if (live && workspaces.length > 0) setWorkspaceId(workspaces[0].id)
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [])
  return workspaceId
}
