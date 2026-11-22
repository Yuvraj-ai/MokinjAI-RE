import { useState, useEffect } from 'react'
import { listWorkspaces } from '../api/workspaces'
import PromptLibrary from '../components/flow/sidebar/PromptLibrary'
import { Spinner } from '../components/ui/Feedback'

export default function PromptsPage() {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)

  useEffect(() => {
    listWorkspaces().then((ws) => {
      if (ws && ws.length > 0) setWorkspaceId(ws[0].id)
    }).catch(() => {})
  }, [])

  if (!workspaceId) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner className="w-6 h-6 text-primary" />
      </div>
    )
  }

  return (
    <div className="h-full">
      <PromptLibrary workspaceId={workspaceId} fullPage />
    </div>
  )
}
