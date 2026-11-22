import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, X } from 'lucide-react'
import type { AgentListItem } from '../../api/agents'
import type { AgentAccess } from '../../api/apiKeys'
import { StatusBadge } from '../ui/Badge'
import { cn } from '../../lib/utils'

/**
 * Chooses which agents an API key may call: every agent (now and later), or an
 * explicit set. `value` is null until the user chooses, so a new key never gets
 * a silent default.
 */
export default function AgentAccessPicker({
  value,
  onChange,
  agents,
  loading = false,
}: {
  value: AgentAccess | null
  onChange: (next: AgentAccess) => void
  agents: AgentListItem[]
  loading?: boolean
}) {
  const [search, setSearch] = useState('')
  const selected = useMemo(() => new Set(value?.mode === 'selected' ? value.agent_ids : []), [value])
  const byId = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents])

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase()
    return term ? agents.filter((agent) => agent.name.toLowerCase().includes(term)) : agents
  }, [agents, search])

  const setSelected = (ids: Set<string>) => onChange({ mode: 'selected', agent_ids: [...ids] })
  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  // Ids the key still holds that no longer match a listed agent (deleted since).
  const unknown = [...selected].filter((id) => !byId.has(id))
  const count = selected.size

  return (
    <fieldset className="rounded-lg border border-line p-3" data-testid="agent-access">
      <legend className="px-1 text-[12.5px] font-medium text-ink">Agent access *</legend>

      <div role="radiogroup" aria-label="Agent access" className="grid grid-cols-2 gap-2">
        {(
          [
            { mode: 'all', title: 'All agents', hint: 'Including agents you create later' },
            { mode: 'selected', title: 'Selected agents', hint: 'Only the agents you pick' },
          ] as const
        ).map((option) => {
          const active = value?.mode === option.mode
          return (
            <button
              key={option.mode}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() =>
                onChange(
                  option.mode === 'all'
                    ? { mode: 'all', agent_ids: [] }
                    : { mode: 'selected', agent_ids: value?.mode === 'selected' ? value.agent_ids : [] }
                )
              }
              className={cn(
                'rounded-lg border px-3 py-2 text-left transition-colors',
                active ? 'border-ink bg-surface-muted' : 'border-line hover:border-line-strong'
              )}
            >
              <span className="block text-[13px] font-medium text-ink">{option.title}</span>
              <span className="block text-[11.5px] text-ink-muted">{option.hint}</span>
            </button>
          )
        })}
      </div>

      {value?.mode === 'selected' && (
        <div className="mt-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span
              className="rounded-full border border-line px-2 py-0.5 font-mono text-[11.5px] text-ink"
              data-testid="agent-access-count"
            >
              {count} of {agents.length} agent{agents.length === 1 ? '' : 's'} selected
            </span>
            <span className="flex gap-3 text-[12px]">
              <button
                type="button"
                className="text-ink-muted hover:text-ink"
                onClick={() => setSelected(new Set(agents.map((agent) => agent.id)))}
                disabled={agents.length === 0}
              >
                Select all
              </button>
              <button
                type="button"
                className="text-ink-muted hover:text-ink"
                onClick={() => setSelected(new Set())}
                disabled={count === 0}
              >
                Clear
              </button>
            </span>
          </div>

          {count > 0 && (
            <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Selected agents">
              {[...selected].map((id) => (
                <li
                  key={id}
                  className="inline-flex items-center gap-1 rounded-md border border-line bg-surface-muted py-0.5 pl-2 pr-1 text-[12px] text-ink"
                >
                  {byId.get(id)?.name ?? 'Deleted agent'}
                  <button
                    type="button"
                    aria-label={`Remove ${byId.get(id)?.name ?? 'agent'}`}
                    onClick={() => toggle(id)}
                    className="rounded p-0.5 text-ink-subtle hover:text-ink"
                  >
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-ink-subtle" aria-hidden />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search agents"
              aria-label="Search agents"
              className="w-full rounded-lg border border-line bg-surface-muted py-2 pl-8 pr-3 text-[13px] text-ink placeholder:text-ink-subtle focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <ul className="max-h-48 overflow-y-auto rounded-lg border border-line" aria-label="Agents">
            {loading && <li className="px-3 py-3 text-[12.5px] text-ink-subtle">Loading agents…</li>}
            {!loading && agents.length === 0 && (
              <li className="px-3 py-3 text-[12.5px] text-ink-subtle">
                No agents yet.{' '}
                <Link to="/agents" className="underline hover:text-ink">
                  Create one
                </Link>{' '}
                first.
              </li>
            )}
            {!loading && agents.length > 0 && visible.length === 0 && (
              <li className="px-3 py-3 text-[12.5px] text-ink-subtle">No agent matches “{search}”.</li>
            )}
            {visible.map((agent) => (
              <li key={agent.id} className="border-b border-line last:border-0">
                <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-surface-muted">
                  <input
                    type="checkbox"
                    checked={selected.has(agent.id)}
                    onChange={() => toggle(agent.id)}
                    className="h-4 w-4"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{agent.name}</span>
                  {agent.status === 'needs_attention' && (
                    <StatusBadge status="needs_attention" size="sm" />
                  )}
                </label>
              </li>
            ))}
          </ul>
          {unknown.length > 0 && (
            <p className="mt-1.5 text-[11.5px] text-ink-subtle">
              {unknown.length} selected agent{unknown.length === 1 ? ' is' : 's are'} no longer available.
            </p>
          )}
          {count === 0 && !loading && agents.length > 0 && (
            <p className="mt-1.5 text-[11.5px] text-status-warning">Select at least one agent.</p>
          )}
        </div>
      )}
      {value?.mode === 'all' && (
        <p className="mt-2 text-[11.5px] text-ink-muted">
          This key can call every agent in the workspace, including ones created later.
        </p>
      )}
    </fieldset>
  )
}
