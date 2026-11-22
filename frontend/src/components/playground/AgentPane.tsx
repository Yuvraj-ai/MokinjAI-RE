import { Bot, CheckCircle2, AlertTriangle } from 'lucide-react'
import type { AgentListItem } from '../../api/agents'
import { cn } from '../../lib/utils'

interface AgentPaneProps {
  agents: AgentListItem[]
  selectedId: string | null
  onSelect: (agentId: string) => void
}

/** Pane 1 (spec P5): the workspace's agents with their readiness dot. */
export default function AgentPane({ agents, selectedId, onSelect }: AgentPaneProps) {
  return (
    <div className="flex h-full w-[210px] shrink-0 flex-col border-r border-line">
      <p className="px-3 pt-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-subtle">
        Agents
      </p>
      <div className="flex-1 overflow-y-auto pb-3">
        {agents.length === 0 && (
          <p className="px-3 text-[12px] text-ink-subtle">No agents yet.</p>
        )}
        {agents.map((agent) => (
          <button
            key={agent.id}
            onClick={() => onSelect(agent.id)}
            className={cn(
              'flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors',
              agent.id === selectedId
                ? 'bg-surface-muted text-ink'
                : 'text-ink-muted hover:bg-surface-muted hover:text-ink'
            )}
          >
            <Bot className="h-3.5 w-3.5 shrink-0 text-ink-subtle" aria-hidden />
            <span className="truncate flex-1">{agent.name}</span>
            {agent.status === 'ready' ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-success" aria-hidden />
            ) : (
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-status-warning" aria-hidden />
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
