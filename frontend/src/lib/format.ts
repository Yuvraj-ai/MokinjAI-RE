export function compact(value: number | null | undefined): string {
  if (value == null) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${trim(value / 1e9)}B`
  if (abs >= 1e6) return `${trim(value / 1e6)}M`
  if (abs >= 1e3) return `${trim(value / 1e3)}K`
  return String(Math.round(value))
}

function trim(value: number): string {
  return value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toFixed(2)
}

export function tokens(value: number | null | undefined): string {
  return value == null ? '—' : `${compact(value)} tok`
}

export function usd(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value === 0) return '$0.00'
  if (Math.abs(value) < 0.01) return `$${value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '.0')}`
  if (Math.abs(value) < 100) return `$${value.toFixed(2)}`
  return `$${Math.round(value).toLocaleString()}`
}

export function percent(value: number | null | undefined, digits = 1): string {
  return value == null ? '—' : `${(value * 100).toFixed(digits)}%`
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}

/** Chart axis label for a bucket start such as "2026-06-13T00:00:00". */
export function bucketLabel(bucket: string, unit: 'hour' | 'day' | 'week' | 'month'): string {
  const date = new Date(bucket)
  if (unit === 'hour') return date.toLocaleTimeString([], { hour: 'numeric' })
  if (unit === 'month') return date.toLocaleDateString([], { month: 'short', year: '2-digit' })
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

/** "-12.3%" style change versus the previous period. */
export function delta(current: number, previous: number | null | undefined): { text: string; tone: 'up' | 'down' | 'flat' } | null {
  if (previous == null) return null
  if (previous === 0) return current === 0 ? { text: '0%', tone: 'flat' } : { text: 'New', tone: 'up' }
  const change = ((current - previous) / previous) * 100
  if (Math.abs(change) < 0.05) return { text: '0%', tone: 'flat' }
  return { text: `${Math.abs(change).toFixed(1)}%`, tone: change > 0 ? 'up' : 'down' }
}
