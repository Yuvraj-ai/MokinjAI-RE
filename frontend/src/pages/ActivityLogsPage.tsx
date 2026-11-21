import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, ScrollText, X } from 'lucide-react'
import {
  getActivityLog,
  getActivityLogs,
  getActivitySessions,
  getActivitySummary,
  type ActivitySummary,
  type LogDetail,
  type LogRow,
  type Page,
  type SessionRow,
} from '../api/activity'
import FilterBar from '../components/activity/FilterBar'
import { StackedBars } from '../components/activity/charts'
import type { ChartSeries } from '../lib/chartColors'
import Badge, { type BadgeTone } from '../components/ui/Badge'
import { EmptyState, Spinner } from '../components/ui/Feedback'
import { Table, TableFrame, Td, Th, Tr } from '../components/ui/Table'
import { Tabs } from '../components/ui/Tabs'
import { useActivityFilters, useWorkspaceId } from '../lib/activityFilters'
import { compact, duration, usd } from '../lib/format'
import { cn } from '../lib/utils'

const PAGE_SIZE = 25

const STATUS_TONE: Record<string, BadgeTone> = {
  completed: 'success',
  failed: 'danger',
  cancelled: 'neutral',
  running: 'info',
  pending: 'warning',
}

const SOURCE_LABEL: Record<string, string> = { api: 'API', playground: 'Playground', workflow: 'Workflow' }

function when(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function modelLabel(row: Pick<LogRow, 'provider' | 'model_id' | 'model_is_current'>): string {
  if (!row.model_id) return '—'
  return `${row.model_id}${row.model_is_current ? ' *' : ''}`
}

function asText(value: unknown): string {
  if (value == null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-ink-subtle">{label}</p>
      <p className="mt-0.5 break-words font-mono text-[13px] text-ink">{value}</p>
    </div>
  )
}

function Block({ title, text }: { title: string; text: string }) {
  if (!text) return null
  return (
    <div>
      <p className="mb-1 text-[12px] font-medium text-ink-muted">{title}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-surface-muted p-3 font-mono text-[12px] text-ink">
        {text}
      </pre>
    </div>
  )
}

function DetailDrawer({
  workspaceId,
  executionId,
  onClose,
}: {
  workspaceId: string
  executionId: string
  onClose: () => void
}) {
  // The parent keys this component by execution id, so state starts fresh
  // for every request opened.
  const [detail, setDetail] = useState<LogDetail | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let live = true
    getActivityLog(workspaceId, executionId)
      .then((result) => live && setDetail(result))
      .catch(() => live && setError(true))
    return () => {
      live = false
    }
  }, [workspaceId, executionId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const tools = (detail?.activity ?? []).filter((event) => event.type === 'tool_end')

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-label="Request details"
        className="relative flex h-full w-full max-w-xl flex-col border-l border-line bg-surface shadow-drawer"
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Request details</h2>
            <p className="font-mono text-[11.5px] text-ink-subtle">{executionId}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-ink-subtle hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {!detail && !error && (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          )}
          {error && <p className="text-[13px] text-status-error">Could not load this request.</p>}
          {detail && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <Field
                  label="Status"
                  value={
                    <Badge tone={STATUS_TONE[detail.status] ?? 'neutral'} dot>
                      {detail.status}
                    </Badge>
                  }
                />
                <Field label="When" value={new Date(detail.created_at).toLocaleString()} />
                <Field label="Agent" value={detail.agent_name ?? '—'} />
                <Field
                  label="API key"
                  value={detail.api_key_name ? `${detail.api_key_name} (${detail.api_key_prefix?.slice(-3)})` : '—'}
                />
                <Field label="Source" value={SOURCE_LABEL[detail.source]} />
                <Field
                  label="Model"
                  value={detail.model_id ? `${detail.provider ?? ''}/${detail.model_id}` : '—'}
                />
                <Field label="Input tokens" value={detail.input_tokens ?? '—'} />
                <Field label="Output tokens" value={detail.output_tokens ?? '—'} />
                <Field label="Cached input" value={detail.cached_tokens ?? 'not reported'} />
                <Field label="Reasoning" value={detail.reasoning_tokens ?? 'not reported'} />
                <Field label="Cost" value={usd(detail.cost_usd)} />
                <Field label="Latency" value={duration(detail.latency_ms)} />
                <Field label="Time to first token" value={duration(detail.ttft_ms)} />
              </div>
              {detail.model_is_current && (
                <p className="text-[11.5px] text-ink-subtle">
                  * No model was recorded for this run, so the agent&apos;s current model is shown.
                </p>
              )}
              {detail.error && (
                <div className="rounded-lg border border-status-error/30 bg-status-error-soft p-3 text-[12.5px] text-status-error">
                  {detail.error}
                </div>
              )}
              <Block title="Input" text={asText(detail.input)} />
              <Block title="Output" text={asText(detail.output)} />
              <Block title="Reasoning" text={detail.reasoning ?? ''} />
              {tools.length > 0 && (
                <div>
                  <p className="mb-1 text-[12px] font-medium text-ink-muted">Tool calls ({tools.length})</p>
                  <ul className="divide-y divide-line rounded-lg border border-line">
                    {tools.map((tool, index) => (
                      <li key={index} className="flex items-center justify-between px-3 py-2 text-[12.5px]">
                        <span className="font-mono text-ink">{String(tool.name)}</span>
                        <span className="text-ink-subtle">
                          {tool.error ? 'failed' : duration(tool.duration_ms as number | null)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {detail.trace != null && <Block title="Execution trace" text={asText(detail.trace)} />}
            </>
          )}
        </div>
      </aside>
    </div>
  )
}

function Pager({
  page,
  total,
  limit,
  onPage,
}: {
  page: number
  total: number
  limit: number
  onPage: (next: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / limit))
  const first = total === 0 ? 0 : (page - 1) * limit + 1
  const last = Math.min(total, page * limit)
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[13px] text-ink-muted">
      <span>
        {first}–{last} of {total.toLocaleString()}
      </span>
      <span className="flex items-center gap-2">
        <button
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          className="rounded-md border border-line p-1 disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= pages}
          aria-label="Next page"
          className="rounded-md border border-line p-1 disabled:opacity-40"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </span>
    </div>
  )
}

export default function ActivityLogsPage() {
  const workspaceId = useWorkspaceId()
  const { filters, query, update, clear, activeCount, refresh, params, setParams } = useActivityFilters()
  const tab = params.get('tab') === 'sessions' ? 'sessions' : 'requests'
  const page = Math.max(1, Number(params.get('page')) || 1)

  const [summary, setSummary] = useState<ActivitySummary | null>(null)
  const [logs, setLogs] = useState<Page<LogRow> | null>(null)
  const [sessions, setSessions] = useState<Page<SessionRow> | null>(null)
  // Which request the table on screen was loaded for (see ActivityPage).
  const [loadedKey, setLoadedKey] = useState<string | null>(null)
  const [failedKey, setFailedKey] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const setPage = (next: number) =>
    setParams(
      (previous) => {
        const copy = new URLSearchParams(previous)
        if (next <= 1) copy.delete('page')
        else copy.set('page', String(next))
        return copy
      },
      { replace: true }
    )

  const setTab = (next: string) =>
    setParams(
      (previous) => {
        const copy = new URLSearchParams(previous)
        if (next === 'requests') copy.delete('tab')
        else copy.set('tab', next)
        copy.delete('page')
        return copy
      },
      { replace: true }
    )

  // The histogram above the table and the model filter options come from the
  // summary, which shares its filters with the table.
  useEffect(() => {
    if (!workspaceId) return
    let live = true
    getActivitySummary(workspaceId, query, { top: 1 })
      .then((result) => live && setSummary(result))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [workspaceId, query])

  const requestKey = JSON.stringify([workspaceId, query, tab, page])
  useEffect(() => {
    if (!workspaceId) return
    let live = true
    const request =
      tab === 'requests'
        ? getActivityLogs(workspaceId, query, { page, limit: PAGE_SIZE }).then((result) => {
            if (live) setLogs(result)
          })
        : getActivitySessions(workspaceId, query, { page, limit: PAGE_SIZE }).then((result) => {
            if (live) setSessions(result)
          })
    request
      .then(() => live && setLoadedKey(requestKey))
      .catch(() => live && setFailedKey(requestKey))
    return () => {
      live = false
    }
  }, [workspaceId, query, tab, page, requestKey])
  const loading = loadedKey !== requestKey && failedKey !== requestKey
  const error = failedKey === requestKey ? 'Could not load the logs.' : null

  const histogram: ChartSeries[] = useMemo(
    () => [
      { key: 'completed', label: 'Completed', color: '#10B981', values: summary?.series.map((p) => p.completed) ?? [] },
      { key: 'failed', label: 'Failed', color: '#EF4444', values: summary?.series.map((p) => p.failed) ?? [] },
      { key: 'cancelled', label: 'Cancelled', color: '#9CA3AF', values: summary?.series.map((p) => p.cancelled) ?? [] },
    ],
    [summary]
  )
  const modelOptions = useMemo(() => summary?.by_model.map((model) => model.key) ?? [], [summary])

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="mx-auto max-w-[88rem] space-y-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Activity Logs</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Every agent run, newest first: API calls, Playground chats and workflow runs.
          </p>
        </div>

        <FilterBar
          workspaceId={workspaceId}
          filters={filters}
          activeCount={activeCount}
          onChange={update}
          onClear={clear}
          onRefresh={refresh}
          modelOptions={modelOptions}
          showStatus
          refreshing={loading}
        />

        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'requests', label: 'Requests', count: tab === 'requests' ? logs?.total : undefined },
            { id: 'sessions', label: 'Sessions', count: tab === 'sessions' ? sessions?.total : undefined },
          ]}
        />

        {tab === 'requests' && summary && summary.series.length > 0 && (
          <div className="rounded-xl border border-line bg-surface p-4">
            <StackedBars
              buckets={summary.series.map((p) => p.bucket)}
              unit={summary.range.bucket}
              series={histogram}
              format={compact}
              height={96}
              integer
              empty="No requests in this range"
            />
          </div>
        )}

        {error && (
          <p role="alert" className="text-[13px] text-status-error">
            {error}
          </p>
        )}

        {tab === 'requests' && (
          <TableFrame className={cn(loading && 'opacity-60 transition-opacity')}>
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>Date</Th>
                    <Th>Agent</Th>
                    <Th>API key</Th>
                    <Th>Source</Th>
                    <Th>Model</Th>
                    <Th>Status</Th>
                    <Th numeric>Input</Th>
                    <Th numeric>Output</Th>
                    <Th numeric>Cost</Th>
                    <Th numeric>Latency</Th>
                    <Th numeric>TTFT</Th>
                  </tr>
                </thead>
                <tbody>
                  {(logs?.rows ?? []).map((row) => (
                    <Tr key={row.id} onClick={() => setSelected(row.id)}>
                      <Td className="whitespace-nowrap text-ink-muted">{when(row.created_at)}</Td>
                      <Td className="whitespace-nowrap">{row.agent_name ?? '—'}</Td>
                      <Td className="whitespace-nowrap text-ink-muted">
                        {row.api_key_name ?? '—'}
                      </Td>
                      <Td className="text-ink-muted">{SOURCE_LABEL[row.source]}</Td>
                      <Td mono className="whitespace-nowrap text-ink-muted">
                        <span
                          title={
                            row.model_is_current
                              ? 'No model was recorded for this run; showing the agent’s current model'
                              : undefined
                          }
                        >
                          {modelLabel(row)}
                        </span>
                      </Td>
                      <Td>
                        <Badge tone={STATUS_TONE[row.status] ?? 'neutral'} dot>
                          {row.status}
                        </Badge>
                      </Td>
                      <Td numeric className="text-ink-muted">
                        {row.input_tokens != null ? compact(row.input_tokens) : '—'}
                      </Td>
                      <Td numeric className="text-ink-muted">
                        {row.output_tokens != null ? compact(row.output_tokens) : '—'}
                      </Td>
                      <Td numeric className="text-ink-muted">
                        {usd(row.cost_usd)}
                      </Td>
                      <Td numeric className="text-ink-muted">
                        {duration(row.latency_ms)}
                      </Td>
                      <Td numeric className="text-ink-muted">
                        {duration(row.ttft_ms)}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </div>
            {logs && logs.rows.length === 0 && !loading && (
              <EmptyState
                icon={ScrollText}
                title="No transactions found"
                description="Try adjusting the date range or filters to see more data."
              />
            )}
            {logs && logs.total > 0 && (
              <Pager page={page} total={logs.total} limit={PAGE_SIZE} onPage={setPage} />
            )}
          </TableFrame>
        )}

        {tab === 'sessions' && (
          <TableFrame className={cn(loading && 'opacity-60 transition-opacity')}>
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>Last activity</Th>
                    <Th>Session</Th>
                    <Th>Agent</Th>
                    <Th>API key</Th>
                    <Th>Source</Th>
                    <Th>Model</Th>
                    <Th numeric>Requests</Th>
                    <Th numeric>Tokens</Th>
                    <Th numeric>Cost</Th>
                  </tr>
                </thead>
                <tbody>
                  {(sessions?.rows ?? []).map((row) => (
                    <Tr key={row.id}>
                      <Td className="whitespace-nowrap text-ink-muted">{when(row.last_activity_at)}</Td>
                      <Td className="max-w-64 truncate">{row.title}</Td>
                      <Td className="whitespace-nowrap">{row.agent_name ?? '—'}</Td>
                      <Td className="whitespace-nowrap text-ink-muted">{row.api_key_name ?? '—'}</Td>
                      <Td className="text-ink-muted">{SOURCE_LABEL[row.source]}</Td>
                      <Td mono className="whitespace-nowrap text-ink-muted">
                        {row.model?.split('/').slice(1).join('/') || '—'}
                      </Td>
                      <Td numeric className="text-ink-muted">{row.requests}</Td>
                      <Td numeric className="text-ink-muted">{compact(row.total_tokens)}</Td>
                      <Td numeric className="text-ink-muted">{usd(row.cost_usd)}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </div>
            {sessions && sessions.rows.length === 0 && !loading && (
              <EmptyState
                icon={ScrollText}
                title="No sessions found"
                description="Try adjusting the date range or filters to see more data."
              />
            )}
            {sessions && sessions.total > 0 && (
              <Pager page={page} total={sessions.total} limit={PAGE_SIZE} onPage={setPage} />
            )}
          </TableFrame>
        )}
      </div>

      {selected && workspaceId && (
        <DetailDrawer key={selected} workspaceId={workspaceId} executionId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
