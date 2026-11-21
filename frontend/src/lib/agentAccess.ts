import type { AgentAccess } from '../api/apiKeys'

/** Short label for the keys list. */
export function accessLabel(access: AgentAccess): string {
  return access.mode === 'all'
    ? 'All agents'
    : `${access.agent_ids.length} agent${access.agent_ids.length === 1 ? '' : 's'}`
}

/** A choice has been made, and a selection is never empty. */
export function accessIsValid(access: AgentAccess | null): access is AgentAccess {
  return !!access && (access.mode === 'all' || access.agent_ids.length > 0)
}
