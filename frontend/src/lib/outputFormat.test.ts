import { describe, expect, it } from 'vitest'
import type { AgentCapabilities } from '../api/agents'
import { availableFormats, openUiUnavailableReason, reconcileFormat } from './outputFormat'

const caps = (extra: Partial<AgentCapabilities>) => extra as AgentCapabilities

describe('availableFormats', () => {
  it('uses the server list', () => {
    expect(availableFormats(caps({ output_formats: ['markdown', 'openui'] }))).toEqual(['markdown', 'openui'])
    expect(availableFormats(caps({ output_formats: ['markdown'] }))).toEqual(['markdown'])
  })

  it('falls back to Markdown without capabilities', () => {
    expect(availableFormats(null)).toEqual(['markdown'])
    expect(availableFormats(caps({}))).toEqual(['markdown'])
    expect(availableFormats(caps({ output_formats: [] }))).toEqual(['markdown'])
  })
})

describe('reconcileFormat (model switching)', () => {
  const both = ['markdown', 'openui'] as const
  it('keeps OpenUI between eligible models', () => {
    expect(reconcileFormat('openui', [...both])).toBe('openui')
  })
  it('resets OpenUI to Markdown on an ineligible model', () => {
    expect(reconcileFormat('openui', ['markdown'])).toBe('markdown')
  })
  it('stays on Markdown when returning to an eligible model', () => {
    const afterIneligible = reconcileFormat('openui', ['markdown'])
    expect(reconcileFormat(afterIneligible, [...both])).toBe('markdown')
  })
})

describe('openUiUnavailableReason', () => {
  it('names the model window', () => {
    expect(openUiUnavailableReason(caps({ context_window: 128000 }))).toBe(
      'OpenUI needs a 200,000-token context window. This model has 128,000.'
    )
  })
  it('handles an unknown window', () => {
    expect(openUiUnavailableReason(null)).toContain('unknown')
  })
})
