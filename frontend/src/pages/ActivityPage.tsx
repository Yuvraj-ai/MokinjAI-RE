import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, Bot, Check, Cpu, KeyRound, MessagesSquare } from 'lucide-react'
import {
  getActivitySummary,
  type ActivitySummary,
  type Metrics,
  type RankBy,
  type SeriesPoint,
} from '../api/activity'
import FilterBar from '../components/activity/FilterBar'
import { Legend, Sparkline, StackedBars } from '../components/activity/charts'
import { colorAt, type ChartSeries } from '../lib/chartColors'
import { Spinner } from '../components/ui/Feedback'
import { useActivityFilters, useWorkspaceId, withFilters } from '../lib/activityFilters'
import { compact, delta, duration, percent, tokens as tokensLabel, usd } from '../lib/format'
import { cn } from '../lib/utils'

type ModelMetric = 'requests' | 'tokens' | 'cost'

const METRIC_LABEL: Record<ModelMetric, string> = {
  requests: 'Requests',
  tokens: 'Tokens',
  cost: 'Cost',
}

const metricValue = (point: Metrics, metric: ModelMetric) =>
  metric === 'requests' ? point.requests : metric === 'tokens' ? point.total_tokens : point.cost_usd

const metricFormat = (metric: ModelMetric) => (value: number) =>
  metric === 'cost' ? usd(value) : compact(value)

function Panel({
  title,
  children,
  right,
  className,
  testId,
}: {
  title: string
  children: React.ReactNode
  right?: React.ReactNode
  className?: string
  testId?: string
}) {
  return (
    <section className={cn('rounded-xl border border-line bg-surface p-5', className)} data-testid={testId}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { id: T; label: string }[]
  onChange: (next: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-line p-0.5">
      {options.map((option) => (
        <button
          key={option.id}
          onClick={() => onChange(option.id)}
          aria-pressed={value === option.id}
          className={cn(
            'rounded-md px-2.5 py-1 text-[12px] transition-colors',
            value === option.id ? 'bg-surface-muted font-medium text-ink' : 'text-ink-muted hover:text-ink'
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function KpiTile({
  label,
  value,
  series,
  change,
  better = 'up',
  testId,
}: {
  label: string
  value: string
  series: number[]
  change: { text: string; tone: 'up' | 'down' | 'flat' } | null
  better?: 'up' | 'down'
  testId: string
}) {
  const good = change && change.tone !== 'flat' && change.tone === better
  const bad = change && change.tone !== 'flat' && change.tone !== better
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5" data-testid={testId}>
      <p className="text-[12.5px] text-ink-muted">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <p className="font-mono text-2xl font-medium leading-tight text-ink">{value}</p>
        <Sparkline values={series} color={bad ? '#EF4444' : '#10B981'} />
      </div>
      <p
        className={cn(
          'mt-1.5 flex items-center gap-1 text-[12px]',
          good ? 'text-status-success' : bad ? 'text-status-error' : 'text-ink-subtle'
        )}
      >
        {change ? (
          <>
            {change.tone === 'up' && <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />}
            {change.tone === 'down' && <ArrowDownRight className="h-3.5 w-3.5" aria-hidden />}
            {change.text} <span className="text-ink-subtle">vs prev period</span>
          </>
        ) : (
          'No prior data'
        )}
      </p>
    </div>
  )
}

function FirstRun({ hasAgents }: { hasAgents: boolean }) {
  const steps = [
    { done: false, label: 'Add an LLM profile', hint: 'Connect a model provider and verify it.', to: '/llms', icon: Cpu },
    { done: hasAgents, label: 'Build an agent', hint: 'Combine a prompt, tools and data into an agent.', to: '/agents', icon: Bot },
    { done: false, label: 'Create an API key', hint: 'Pick which agents the key may call.', to: '/keys', icon: KeyRound },
    { done: false, label: 'Try it in the Playground', hint: 'Chat with the agent, then call it from your app.', to: '/playground', icon: MessagesSquare },
  ]
  return (
    <section
      className="rounded-xl border border-line bg-surface p-6"
      data-testid="first-run"
    >
      <h2 className="text-[16px] font-semibold text-ink">No activity yet</h2>
      <p className="mt-1 max-w-xl text-[13px] text-ink-muted">
        This dashboard fills in once your agents handle requests. Four steps get you from nothing to a
        live endpoint.
      </p>
      <ol className="mt-5 grid gap-3 md:grid-cols-2">
        {steps.map((step, index) => (
          <li key={step.to}>
            <Link
              to={step.to}
              className="flex items-start gap-3 rounded-lg border border-line p-3 transition-colors hover:bg-surface-muted"
            >
              <span
                className={cn(
                  'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px]',
                  step.done
                    ? 'border-status-success bg-status-success-soft text-status-success'
                    : 'border-line text-ink-muted'
                )}
              >
                {step.done ? <Check className="h-3.5 w-3.5" aria-hidden /> : index + 1}
              </span>
              <span>
                <span className="block text-[13px] font-medium text-ink">{step.label}</span>
                <span className="block text-[12px] text-ink-muted">{step.hint}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}

function TopRow({
  rank,
  title,
  subtitle,
  main,
  detail,
  to,
}: {
  rank: number
  title: string
  subtitle?: string | null
  main: string
  detail?: string
  to: string
}) {
  return (
    <li>
      <Link
        to={to}
        className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-muted"
      >
        <span className="w-4 text-right font-mono text-[12px] text-ink-subtle">{rank}</span>
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colorAt(rank - 1) }} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] text-ink">{title}</span>
          {subtitle && <span className="block truncate font-mono text-[11.5px] text-ink-subtle">{subtitle}</span>}
        </span>
        <span className="text-right">
          <span className="block font-mono text-[13px] text-ink">{main}</span>
          {detail && <span className="block text-[11.5px] text-ink-subtle">{detail}</span>}
        </span>
      </Link>
    </li>
  )
}

export default function ActivityPage() {
  const workspaceId = useWorkspaceId()
  const { filters, query, update, clear, activeCount, refresh } = useActivityFilters()
  const [result, setResult] = useState<{ key: string; summary: ActivitySummary | null; error: string | null } | null>(null)
  const [rank, setRank] = useState<RankBy>('requests')
  const [modelMetric, setModelMetric] = useState<ModelMetric>('requests')

  // The data on screen belongs to one request; while a newer one is in flight
  // the old data stays visible (dimmed) instead of flashing a spinner.
  const requestKey = JSON.stringify([workspaceId, query, rank])
  useEffect(() => {
    if (!workspaceId) return
    let live = true
    getActivitySummary(workspaceId, query, { rank, top: 5 })
      .then((summary) => live && setResult({ key: requestKey, summary, error: null }))
      .catch(() => live && setResult((prev) => ({ key: requestKey, summary: prev?.summary ?? null, error: 'Could not load activity.' })))
    return () => {
      live = false
    }
  }, [workspaceId, query, rank, requestKey])
  const summary = result?.summary ?? null
  const error = result?.error ?? null
  const loading = !result || result.key !== requestKey

  const buckets = useMemo(() => summary?.series.map((point) => point.bucket) ?? [], [summary])
  const unit = summary?.range.bucket ?? 'day'
  const modelOptions = useMemo(() => summary?.by_model.map((model) => model.key) ?? [], [summary])
  const totals = summary?.totals
  const previous = summary?.previous ?? null
  const spark = (pick: (point: SeriesPoint) => number) => summary?.series.map(pick) ?? []

  const modelSeries: ChartSeries[] = (summary?.by_model ?? []).map((model, index) => ({
    key: model.key,
    label: model.model_id,
    color: colorAt(index),
    values: model.series.map((point) => metricValue(point, modelMetric)),
  }))
  const agentSeries: ChartSeries[] = (summary?.agent_series ?? []).map((agent, index) => ({
    key: agent.agent_id,
    label: agent.name,
    color: colorAt(index),
    values: agent.series.map((point) => point.requests),
  }))
  const outcomeSeries: ChartSeries[] = [
    { key: 'completed', label: 'Completed', color: '#10B981', values: summary?.series.map((p) => p.completed) ?? [] },
    { key: 'failed', label: 'Failed', color: '#EF4444', values: summary?.series.map((p) => p.failed) ?? [] },
    { key: 'cancelled', label: 'Cancelled', color: '#9CA3AF', values: summary?.series.map((p) => p.cancelled) ?? [] },
  ]
  const tokenSeries: ChartSeries[] = [
    { key: 'input', label: 'Input', color: '#3B82F6', values: summary?.series.map((p) => p.input_tokens) ?? [] },
    {
      key: 'output',
      label: totals?.reasoning.reported ? 'Output (excl. reasoning)' : 'Output',
      color: '#8B5CF6',
      values:
        summary?.series.map((p) =>
          Math.max(0, p.output_tokens - (p.reasoning.reported ? p.reasoning.tokens ?? 0 : 0))
        ) ?? [],
    },
    ...(totals?.reasoning.reported
      ? [
          {
            key: 'reasoning',
            label: 'Reasoning',
            color: '#EF4444',
            values: summary?.series.map((p) => p.reasoning.tokens ?? 0) ?? [],
          },
        ]
      : []),
  ]
  const cacheSeries: ChartSeries[] = [
    {
      key: 'uncached',
      label: 'Uncached input',
      color: '#9CA3AF',
      values:
        summary?.series.map((p) =>
          p.cache.reported ? Math.max(0, (p.cache.input_tokens ?? 0) - (p.cache.read_tokens ?? 0)) : 0
        ) ?? [],
    },
    {
      key: 'cached',
      label: 'Cached input',
      color: '#F59E0B',
      values: summary?.series.map((p) => (p.cache.reported ? p.cache.read_tokens ?? 0 : 0)) ?? [],
    },
  ]

  const rankMain = (agent: Metrics) =>
    rank === 'requests'
      ? `${compact(agent.requests)} req`
      : rank === 'tokens'
        ? tokensLabel(agent.total_tokens)
        : usd(agent.cost_usd)

  const exploreAll = withFilters('/logs', {
    range: filters.range,
    from: filters.from,
    to: filters.to,
    tz: filters.tz,
    apiKeyId: filters.apiKeyId,
    agentId: filters.agentId,
    source: filters.source,
    model: filters.model,
  })

  const empty = !loading && summary && !summary.workspace_has_activity

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="mx-auto max-w-6xl space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Activity</h1>
            <p className="mt-1 text-sm text-ink-muted">
              How your deployed agents are being used
              {summary && summary.agent_count > 0 && (
                <>
                  {' '}
                  — {summary.top_agents.length === 0 ? 'no' : summary.top_agents.length} of {summary.agent_count}{' '}
                  agent{summary.agent_count === 1 ? '' : 's'} active in this range
                </>
              )}
              .
            </p>
          </div>
        </div>

        <FilterBar
          workspaceId={workspaceId}
          filters={filters}
          activeCount={activeCount}
          onChange={update}
          onClear={clear}
          onRefresh={refresh}
          modelOptions={modelOptions}
          refreshing={loading}
        />

        {error && (
          <p role="alert" className="text-[13px] text-status-error">
            {error}
          </p>
        )}

        {loading && !summary && (
          <div className="flex h-64 items-center justify-center">
            <Spinner className="h-6 w-6" />
          </div>
        )}

        {summary && totals && (
          <div className={cn('space-y-5', loading && 'opacity-60 transition-opacity')}>
            {empty && <FirstRun hasAgents={summary.agent_count > 0} />}

            <div
              className={cn(
                'grid gap-3 sm:grid-cols-2',
                totals.cache.reported ? 'xl:grid-cols-6' : 'xl:grid-cols-5'
              )}
            >
              <KpiTile
                testId="kpi-requests"
                label="Requests"
                value={compact(totals.requests)}
                series={spark((p) => p.requests)}
                change={delta(totals.requests, previous?.requests)}
              />
              <KpiTile
                testId="kpi-tokens"
                label="Token volume"
                value={compact(totals.total_tokens)}
                series={spark((p) => p.total_tokens)}
                change={delta(totals.total_tokens, previous?.total_tokens)}
              />
              <KpiTile
                testId="kpi-success"
                label="Success rate"
                value={percent(totals.success_rate)}
                series={spark((p) => p.completed)}
                change={
                  previous && totals.success_rate != null && previous.success_rate != null
                    ? delta(totals.success_rate, previous.success_rate)
                    : null
                }
              />
              <KpiTile
                testId="kpi-cost"
                label="Total spend"
                value={usd(totals.cost_usd)}
                series={spark((p) => p.cost_usd)}
                change={delta(totals.cost_usd, previous?.cost_usd)}
                better="down"
              />
              <KpiTile
                testId="kpi-latency"
                label="Avg latency"
                value={duration(totals.avg_latency_ms)}
                series={spark((p) => p.avg_latency_ms ?? 0)}
                change={
                  previous && totals.avg_latency_ms != null && previous.avg_latency_ms != null
                    ? delta(totals.avg_latency_ms, previous.avg_latency_ms)
                    : null
                }
                better="down"
              />
              {totals.cache.reported && (
                <KpiTile
                  testId="kpi-cache"
                  label="Cache hit rate"
                  value={percent(totals.cache.hit_rate)}
                  series={spark((p) => p.cache.hit_rate ?? 0)}
                  change={
                    previous?.cache.reported && totals.cache.hit_rate != null && previous.cache.hit_rate != null
                      ? delta(totals.cache.hit_rate, previous.cache.hit_rate)
                      : null
                  }
                />
              )}
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <Panel
                title="Top agents"
                testId="top-agents"
                right={
                  <div className="flex items-center gap-3">
                    <Segmented
                      label="Rank agents by"
                      value={rank}
                      onChange={setRank}
                      options={[
                        { id: 'requests', label: 'Requests' },
                        { id: 'tokens', label: 'Tokens' },
                        { id: 'cost', label: 'Cost' },
                      ]}
                    />
                    <Link to={exploreAll} className="text-[12.5px] text-ink-muted underline hover:text-ink">
                      Logs ›
                    </Link>
                  </div>
                }
              >
                {summary.top_agents.length === 0 ? (
                  <p className="py-6 text-center text-[13px] text-ink-subtle">No agent traffic in this range.</p>
                ) : (
                  <ul>
                    {summary.top_agents.map((agent, index) => (
                      <TopRow
                        key={agent.agent_id}
                        rank={index + 1}
                        title={agent.name}
                        subtitle={agent.model}
                        main={rankMain(agent)}
                        detail={`${percent(agent.success_rate, 0)} success · ${tokensLabel(agent.total_tokens)}`}
                        to={withFilters('/logs', { ...filters, agentId: agent.agent_id })}
                      />
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel
                title="Top API keys"
                testId="top-keys"
                right={
                  <Link to="/keys" className="text-[12.5px] text-ink-muted underline hover:text-ink">
                    Manage ›
                  </Link>
                }
              >
                {summary.top_keys.length === 0 ? (
                  <p className="py-6 text-center text-[13px] text-ink-subtle">
                    No API calls in this range. Calls made in the Playground are not tied to a key.
                  </p>
                ) : (
                  <ul>
                    {summary.top_keys.map((key, index) => (
                      <TopRow
                        key={key.api_key_id}
                        rank={index + 1}
                        title={key.name}
                        subtitle={`${key.prefix}…`}
                        main={rankMain(key)}
                        detail={`${percent(key.success_rate, 0)} success`}
                        to={withFilters('/dashboard', { ...filters, apiKeyId: key.api_key_id })}
                      />
                    ))}
                  </ul>
                )}
              </Panel>
            </div>

            <Panel
              title="Usage by model"
              testId="usage-by-model"
              right={
                <Segmented
                  label="Usage by model metric"
                  value={modelMetric}
                  onChange={setModelMetric}
                  options={(['requests', 'tokens', 'cost'] as ModelMetric[]).map((id) => ({
                    id,
                    label: METRIC_LABEL[id],
                  }))}
                />
              }
            >
              <StackedBars
                buckets={buckets}
                unit={unit}
                series={modelSeries}
                format={metricFormat(modelMetric)}
                integer={modelMetric === 'requests'}
              />
              {modelSeries.length > 0 && <Legend items={modelSeries.map((s) => ({ label: s.label, color: s.color }))} />}
            </Panel>

            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Requests by agent" testId="requests-by-agent">
                <StackedBars buckets={buckets} unit={unit} series={agentSeries} format={compact} integer />
                {agentSeries.length > 0 && <Legend items={agentSeries.map((s) => ({ label: s.label, color: s.color }))} />}
              </Panel>
              <Panel title="Requests by outcome" testId="requests-by-outcome">
                <StackedBars buckets={buckets} unit={unit} series={outcomeSeries} format={compact} integer />
                <Legend items={outcomeSeries.map((s) => ({ label: s.label, color: s.color }))} />
              </Panel>
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Token breakdown" testId="token-breakdown">
                <StackedBars buckets={buckets} unit={unit} series={tokenSeries} format={compact} />
                <Legend items={tokenSeries.map((s) => ({ label: s.label, color: s.color }))} />
                {!totals.reasoning.reported && (
                  <p className="mt-2 text-[11.5px] text-ink-subtle">
                    Reasoning tokens appear when a model reports them.
                  </p>
                )}
              </Panel>
              <Panel title="Prompt token caching" testId="prompt-caching">
                {totals.cache.reported ? (
                  <>
                    <StackedBars buckets={buckets} unit={unit} series={cacheSeries} format={compact} />
                    <Legend items={cacheSeries.map((s) => ({ label: s.label, color: s.color }))} />
                    <p className="mt-2 text-[11.5px] text-ink-subtle">
                      Counts only requests whose provider reported cache usage.
                    </p>
                  </>
                ) : (
                  <p className="flex h-44 items-center justify-center px-6 text-center text-[13px] text-ink-subtle">
                    None of the models used in this range report prompt caching, so there is nothing to
                    chart.
                  </p>
                )}
              </Panel>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
