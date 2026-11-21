import apiClient from './client'

/** Mirrors `app/services/activity.py`. */

export type ActivitySource = 'api' | 'playground' | 'workflow'
export type RankBy = 'requests' | 'tokens' | 'cost'

export interface ActivityQuery {
  from: string
  to: string
  tz: string
  api_key_id?: string
  agent_id?: string
  source?: ActivitySource
  model?: string
  status?: string
}

export interface CacheMetrics {
  reported: boolean
  read_tokens: number | null
  creation_tokens: number | null
  input_tokens: number | null
  hit_rate: number | null
}

export interface Metrics {
  requests: number
  completed: number
  failed: number
  cancelled: number
  success_rate: number | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  avg_latency_ms: number | null
  avg_ttft_ms: number | null
  cache: CacheMetrics
  reasoning: { reported: boolean; tokens: number | null }
}

export type SeriesPoint = Metrics & { bucket: string }

export interface ModelUsage {
  key: string
  provider: string
  model_id: string
  totals: Metrics
  series: SeriesPoint[]
}

export interface TopAgent extends Metrics {
  agent_id: string
  name: string
  model: string | null
}

export interface AgentSeries {
  agent_id: string
  name: string
  series: SeriesPoint[]
}

export interface TopKey extends Metrics {
  api_key_id: string
  name: string
  prefix: string
}

export interface ActivitySummary {
  range: { from: string; to: string; tz: string; bucket: 'hour' | 'day' | 'week' | 'month' }
  workspace_has_activity: boolean
  agent_count: number
  totals: Metrics
  previous: Metrics | null
  series: SeriesPoint[]
  by_model: ModelUsage[]
  top_agents: TopAgent[]
  agent_series: AgentSeries[]
  top_keys: TopKey[]
}

export interface LogRow {
  id: string
  created_at: string
  status: string
  source: ActivitySource
  agent_id: string | null
  agent_name: string | null
  api_key_id: string | null
  api_key_name: string | null
  api_key_prefix: string | null
  provider: string | null
  model_id: string | null
  model_is_current: boolean
  input_tokens: number | null
  output_tokens: number | null
  cached_tokens: number | null
  reasoning_tokens: number | null
  cost_usd: number | null
  latency_ms: number | null
  ttft_ms: number | null
  error: string | null
}

export interface LogDetail extends LogRow {
  conversation_id: string | null
  input: unknown
  output: unknown
  reasoning: string | null
  activity: Array<Record<string, unknown>> | null
  usage: Record<string, unknown> | null
  trace: unknown
}

export interface SessionRow {
  id: string
  title: string
  agent_id: string
  agent_name: string | null
  api_key_id: string | null
  api_key_name: string | null
  api_key_prefix: string | null
  source: ActivitySource
  started_at: string
  last_activity_at: string
  requests: number
  total_tokens: number
  cost_usd: number
  model: string | null
}

export interface Page<T> {
  total: number
  page: number
  limit: number
  rows: T[]
}

function clean(query: object): Record<string, string | number> {
  const entries = Object.entries(query as Record<string, unknown>).filter(
    ([, value]) => value !== undefined && value !== null && value !== ''
  )
  return Object.fromEntries(entries) as Record<string, string | number>
}

const base = (workspaceId: string) => `/api/workspaces/${workspaceId}/activity`

export async function getActivitySummary(
  workspaceId: string,
  query: ActivityQuery,
  extra: { rank?: RankBy; top?: number } = {}
): Promise<ActivitySummary> {
  const response = await apiClient.get<ActivitySummary>(`${base(workspaceId)}/summary`, {
    params: clean({ ...query, ...extra }),
  })
  return response.data
}

export async function getActivityLogs(
  workspaceId: string,
  query: ActivityQuery,
  paging: { page: number; limit: number }
): Promise<Page<LogRow>> {
  const response = await apiClient.get<Page<LogRow>>(`${base(workspaceId)}/logs`, {
    params: clean({ ...query, ...paging }),
  })
  return response.data
}

export async function getActivityLog(workspaceId: string, executionId: string): Promise<LogDetail> {
  const response = await apiClient.get<LogDetail>(`${base(workspaceId)}/logs/${executionId}`)
  return response.data
}

export async function getActivitySessions(
  workspaceId: string,
  query: ActivityQuery,
  paging: { page: number; limit: number }
): Promise<Page<SessionRow>> {
  const response = await apiClient.get<Page<SessionRow>>(`${base(workspaceId)}/sessions`, {
    params: clean({ ...query, ...paging }),
  })
  return response.data
}
