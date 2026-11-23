import { afterEach, describe, expect, it, vi } from 'vitest'
import { drainSseBuffer, streamSessionChat } from './playground'

describe('drainSseBuffer', () => {
  it('skips keep-alive comments and still reads the events after them', () => {
    // The backend sends ": ping" every 15 s while a model is slow to start.
    // A skipped block used to leave the loop spinning on a stale boundary,
    // freezing the tab ("This page is slowing down Firefox").
    const { events, rest } = drainSseBuffer(
      ': ping\n\n: ping\n\nevent: token\ndata: {"delta":"Hi"}\n\n'
    )
    expect(events).toEqual([{ event: 'token', data: { delta: 'Hi' } }])
    expect(rest).toBe('')
  })

  it('keeps an incomplete trailing block for the next chunk', () => {
    const { events, rest } = drainSseBuffer('event: token\ndata: {"delta":"a"}\n\nevent: tok')
    expect(events).toHaveLength(1)
    expect(rest).toBe('event: tok')
  })

  it('ignores malformed blocks without stopping', () => {
    const { events } = drainSseBuffer(
      'event: token\ndata: {not json\n\njunk\n\nevent: done\ndata: {"status":"completed"}\n\n'
    )
    expect(events.map((e) => e.event)).toEqual(['done'])
  })

  it('returns nothing for a buffer with no complete block', () => {
    expect(drainSseBuffer(': pi')).toEqual({ events: [], rest: ': pi' })
    expect(drainSseBuffer('')).toEqual({ events: [], rest: '' })
  })
})

describe('streamSessionChat', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('streams through pings sent before the first token', async () => {
    const chunks = [
      'event: message\ndata: {"user_message_id":"u","assistant_message_id":"a"}\n\n',
      ': ping\n\n',
      ': ping\n\nevent: token\ndata: {"delta":"Hel',
      'lo"}\n\nevent: done\ndata: {"status":"completed","usage":null,"cost_usd":0}\n\n',
    ]
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))

    const seen = []
    for await (const event of streamSessionChat('ws', 'session', 'hi')) seen.push(event)

    expect(seen.map((e) => e.type)).toEqual(['message', 'token', 'done'])
    expect(seen[1]).toEqual({ type: 'token', delta: 'Hello' })
  })
})

describe('streamSessionChat: resilience events', () => {
  afterEach(() => vi.unstubAllGlobals())

  async function collect(chunks: string[]) {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))
    const seen = []
    for await (const event of streamSessionChat('ws', 'session', 'hi')) seen.push(event)
    return seen
  }

  it('parses queued events', async () => {
    const seen = await collect(['event: queued\ndata: {"position":2}\n\n'])
    expect(seen).toEqual([{ type: 'queued', position: 2 }])
  })

  it('keeps the error code and retry_after_s', async () => {
    const seen = await collect([
      'event: error\ndata: {"detail":"The sandbox is busy. Try again in about 30 seconds.","code":"sandbox_busy","retry_after_s":30}\n\n',
      'event: error\ndata: {"detail":"plain"}\n\n',
    ])
    expect(seen[0]).toEqual({
      type: 'error',
      detail: 'The sandbox is busy. Try again in about 30 seconds.',
      code: 'sandbox_busy',
      retryAfterS: 30,
    })
    expect(seen[1]).toEqual({ type: 'error', detail: 'plain' })
  })
})
