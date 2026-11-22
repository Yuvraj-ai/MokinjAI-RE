// @vitest-environment node
/// <reference types="node" />
import { readFileSync, writeFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { playgroundLibrary, playgroundPrompt, REMOVED_COMPONENTS } from './library'

/**
 * The backend sends this prompt when a turn asks for OpenUI. It is generated
 * from the same library the Playground renders, then committed, because the
 * generator is JavaScript and the backend is Python.
 *
 * Regenerate after changing the library or the OpenUI packages:
 *   npm run openui:prompt
 */
const PROMPT_FILE = new URL('../../../../../backend/app/services/openui_prompt.txt', import.meta.url)

describe('OpenUI prompt', () => {
  const prompt = playgroundPrompt()

  if (process.env.UPDATE_OPENUI_PROMPT === '1') {
    writeFileSync(PROMPT_FILE, prompt)
  }

  it('matches the committed backend prompt (run npm run openui:prompt)', () => {
    expect(readFileSync(PROMPT_FILE, 'utf8')).toBe(prompt)
  })

  it('does not teach removed image components', () => {
    for (const name of REMOVED_COMPONENTS) {
      expect(playgroundLibrary.components).not.toHaveProperty(name)
      expect(prompt).not.toMatch(new RegExp(`\\b${name}\\(`))
    }
  })

  it('does not tell the model to invent data', () => {
    expect(prompt).not.toMatch(/generate realistic\/plausible data/i)
  })
})
