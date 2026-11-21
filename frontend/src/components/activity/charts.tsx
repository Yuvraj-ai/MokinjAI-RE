import { useState } from 'react'
import { bucketLabel } from '../../lib/format'
import { cn } from '../../lib/utils'

import type { ChartSeries } from '../../lib/chartColors'

type Unit = 'hour' | 'day' | 'week' | 'month'

/** Round the axis maximum up to a tidy number so the gridlines read cleanly. */
function niceMax(value: number): number {
  if (value <= 0) return 1
  const exponent = Math.pow(10, Math.floor(Math.log10(value)))
  const fraction = value / exponent
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10
  return nice * exponent
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-[11.5px] text-ink-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: item.color }} aria-hidden />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

/**
 * Stacked columns over time. Plain HTML so it follows the theme, scales with
 * its container and needs no chart dependency (the key spend chart does the
 * same). Hovering a column shows every series for that bucket.
 */
export function StackedBars({
  buckets,
  unit,
  series,
  format,
  height = 176,
  empty = 'No data in this range',
  integer = false,
}: {
  buckets: string[]
  unit: Unit
  series: ChartSeries[]
  format: (value: number) => string
  height?: number
  empty?: string
  /** Counts: keep every axis tick a whole number (4, 3, 2, 1, 0). */
  integer?: boolean
}) {
  const [hover, setHover] = useState<number | null>(null)
  const totals = buckets.map((_, index) => series.reduce((sum, s) => sum + (s.values[index] ?? 0), 0))
  const peak = Math.max(...totals, 0)
  const axisMax = integer && peak <= 20 ? Math.max(4, Math.ceil(peak / 4) * 4) : niceMax(peak)
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((fraction) => axisMax * fraction)
  const labelEvery = Math.max(1, Math.ceil(buckets.length / 8))

  return (
    <div>
      <div className="flex" style={{ height }}>
        <div className="flex w-12 shrink-0 flex-col justify-between pr-2 text-right text-[10.5px] text-ink-subtle">
          {ticks.map((tick) => (
            <span key={tick}>{format(tick)}</span>
          ))}
        </div>
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-0 flex flex-col justify-between" aria-hidden>
            {ticks.map((tick) => (
              <div key={tick} className="border-t border-dashed border-line" />
            ))}
          </div>
          {peak === 0 && (
            <p className="absolute inset-0 flex items-center justify-center text-[12.5px] text-ink-subtle">
              {empty}
            </p>
          )}
          <div className="absolute inset-0 flex items-end gap-[3px]">
            {buckets.map((bucket, index) => (
              <div
                key={bucket}
                className="relative flex h-full flex-1 flex-col-reverse"
                onMouseEnter={() => setHover(index)}
                onMouseLeave={() => setHover(null)}
              >
                {series.map((s) => {
                  const value = s.values[index] ?? 0
                  return value > 0 ? (
                    <div
                      key={s.key}
                      style={{ height: `${(value / axisMax) * 100}%`, background: s.color }}
                      className="min-h-px first:rounded-t-none last:rounded-t-sm"
                    />
                  ) : null
                })}
                {hover === index && peak > 0 && (
                  <div
                    role="tooltip"
                    className={cn(
                      'pointer-events-none absolute bottom-full z-10 mb-1 w-max min-w-32 rounded-lg border border-line bg-surface-raised px-3 py-2 text-[11.5px] shadow-menu',
                      index > buckets.length / 2 ? 'right-0' : 'left-0'
                    )}
                  >
                    <p className="mb-1 font-medium text-ink">{bucketLabel(bucket, unit)}</p>
                    {series.map((s) => (
                      <p key={s.key} className="flex items-center justify-between gap-4 text-ink-muted">
                        <span className="flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
                          {s.label}
                        </span>
                        <span className="font-mono text-ink">{format(s.values[index] ?? 0)}</span>
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="ml-12 mt-1 flex gap-[3px]">
        {buckets.map((bucket, index) => (
          <span key={bucket} className="flex-1 overflow-visible whitespace-nowrap text-[10.5px] text-ink-subtle">
            {index % labelEvery === 0 ? bucketLabel(bucket, unit) : ''}
          </span>
        ))}
      </div>
    </div>
  )
}

/** A tiny trend line for the KPI cards. */
export function Sparkline({ values, color = '#10B981' }: { values: number[]; color?: string }) {
  if (values.length < 2 || Math.max(...values) === 0) {
    return <div className="h-8 w-24 border-b border-line" aria-hidden />
  }
  const max = Math.max(...values)
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * 100},${30 - (value / max) * 28}`)
    .join(' ')
  return (
    <svg viewBox="0 0 100 32" className="h-8 w-24" preserveAspectRatio="none" aria-hidden>
      <polyline fill="none" stroke={color} strokeWidth="1.6" points={points} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
