import { describe, expect, it } from 'vitest'
import { inspectOpenUI, MAX_OPENUI_CHARS } from './inspect'

const VALID = 'root = Card([t])\nt = TextContent("Hello")'

describe('inspectOpenUI', () => {
  it('accepts a valid program', () => {
    const result = inspectOpenUI(VALID, false)
    expect(result.status).toBe('ok')
    expect(result.issues).toEqual([])
  })

  it('reports prose with no program as unrenderable', () => {
    const result = inspectOpenUI('Sure! Here is the summary you asked for.', false)
    expect(result.status).toBe('invalid')
    expect(result.reason).toMatch(/not valid OpenUI/i)
  })

  it('reports an empty reply as unrenderable', () => {
    expect(inspectOpenUI('', false).status).toBe('invalid')
  })

  it('lists unknown components as skipped but still renders the rest', () => {
    const result = inspectOpenUI(VALID.replace('[t]', '[t, x]') + '\nx = EvilWidget("boom")', false)
    expect(result.status).toBe('ok')
    expect(result.issues.join(' ')).toMatch(/EvilWidget/)
  })

  it('lists removed image components as skipped', () => {
    const result = inspectOpenUI(
      'root = Card([t, i])\nt = TextContent("x")\ni = Image("alt", "https://evil.example/p.png")',
      false
    )
    expect(result.status).toBe('ok')
    expect(result.issues.join(' ')).toMatch(/Image/)
  })

  it('does not judge a reply that is still streaming', () => {
    expect(inspectOpenUI('Sure', true).status).toBe('pending')
    expect(inspectOpenUI('root = Card([t, u])\nt = TextContent("a")\nu = TextConte', true).status).toBe('pending')
  })

  it('refuses oversized replies', () => {
    const result = inspectOpenUI(VALID + '\n' + 'x'.repeat(MAX_OPENUI_CHARS), false)
    expect(result.status).toBe('invalid')
    expect(result.reason).toMatch(/too long/i)
  })

  it('never throws on garbage', () => {
    for (const junk of ['root = ', '((((', 'root = Card([', '"unterminated', '}{][', 'root = Card([t])\nt = ']) {
      expect(() => inspectOpenUI(junk, false)).not.toThrow()
    }
  })
})
