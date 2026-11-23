import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { PlaygroundEvent } from '../../api/playground'
import ThreadPane from './ThreadPane'
import ActivityCard from './ActivityCard'

// jsdom has no scrollIntoView; the thread calls it after every update.
Element.prototype.scrollIntoView = () => {}
afterEach(cleanup)

let script: () => AsyncGenerator<PlaygroundEvent>

vi.mock('../../api/playground', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/playground')>()
  return { ...actual, streamSessionChat: () => script() }
})

const session = {
  id: 's1',
  workspace_id: 'w',
  agent_id: 'a',
  title: 'Chat',
  created_by: null,
  created_at: '',
  updated_at: '',
}

function renderPane() {
  render(
    <ThreadPane
      workspaceId="w"
      session={session}
      messages={[]}
      readOnly={false}
      outputFormat="markdown"
      availableFormats={['markdown']}
      capabilities={null}
      onOutputFormatChange={() => {}}
      onTurnEnded={() => {}}
    />
  )
  const box = screen.getByPlaceholderText(/Message Chat/)
  fireEvent.change(box, { target: { value: 'hi' } })
  fireEvent.keyDown(box, { key: 'Enter' })
}

describe('ThreadPane queued state', () => {
  it('shows the waiting line while queued and removes it on the first token', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    script = async function* () {
      yield { type: 'message', user_message_id: 'u', assistant_message_id: 'a' }
      yield { type: 'queued', position: 2 }
      await gate
      yield { type: 'token', delta: 'Hello' }
      await new Promise(() => {})
    }
    renderPane()
    expect(await screen.findByText('Waiting for a sandbox slot (position 2)…')).toBeTruthy()
    await act(async () => release())
    await waitFor(() => expect(screen.getByText('Hello')).toBeTruthy())
    expect(screen.queryByText(/Waiting for a sandbox slot/)).toBeNull()
  })

  it('shows the server message for a sandbox_busy error', async () => {
    script = async function* () {
      yield { type: 'queued', position: 1 }
      yield {
        type: 'error',
        detail: 'The sandbox is busy. Try again in about 30 seconds.',
        code: 'sandbox_busy',
        retryAfterS: 30,
      }
    }
    renderPane()
    expect(
      await screen.findByText('The sandbox is busy. Try again in about 30 seconds.')
    ).toBeTruthy()
  })
})

describe('ActivityCard resilience', () => {
  it('lists unavailable names with the warning tone', () => {
    const { container } = render(
      <ActivityCard
        event={{
          type: 'unavailable',
          names: ['Connector Slack (unreachable)', 'File gone.csv (not found in storage)'],
        }}
      />
    )
    expect(screen.getByText(/Connector Slack \(unreachable\)/)).toBeTruthy()
    expect(screen.getByText(/File gone\.csv/)).toBeTruthy()
    expect(container.querySelector('.text-status-warning')).not.toBeNull()
  })

  it('shows "after N attempts" on a retried tool card', () => {
    render(<ActivityCard event={{ type: 'tool_end', kind: 'tool', name: 'lookup', attempts: 3 }} />)
    expect(screen.getByText(/after 3 attempts/)).toBeTruthy()
  })
})
