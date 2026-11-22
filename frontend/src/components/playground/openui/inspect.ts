import { createParser } from '@openuidev/react-lang'
import { playgroundLibrary } from './library'

/** Above this a reply is not parsed as UI; the raw text stays available. */
export const MAX_OPENUI_CHARS = 200_000

export interface OpenUIInspection {
  /** pending: still streaming; ok: renders (maybe with skipped parts); invalid: nothing to render. */
  status: 'pending' | 'ok' | 'invalid'
  /** Why nothing renders (invalid only). */
  reason?: string
  /** Parts that were dropped while rendering the rest (ok only). */
  issues: string[]
}

const parser = createParser(playgroundLibrary.toJSONSchema(), playgroundLibrary.root)

/**
 * Judge a reply the way the renderer will see it. The OpenUI Renderer quietly
 * renders nothing for prose and drops unknown components, so this is what
 * lets the Playground say so instead of showing a blank bubble.
 */
export function inspectOpenUI(text: string, streaming: boolean): OpenUIInspection {
  if (text.length > MAX_OPENUI_CHARS) {
    return { status: 'invalid', reason: 'This reply is too long to render as UI.', issues: [] }
  }
  if (streaming) return { status: 'pending', issues: [] }

  let result: ReturnType<typeof parser.parse>
  try {
    result = parser.parse(text)
  } catch {
    return { status: 'invalid', reason: "The reply is not valid OpenUI (it couldn't be parsed).", issues: [] }
  }
  if (!result.root || result.meta.statementCount === 0) {
    return { status: 'invalid', reason: 'The reply is not valid OpenUI (no root component).', issues: [] }
  }
  const issues = [
    ...result.meta.errors.map((error) => describe(error)),
    ...result.meta.unresolved.map((name) => `"${name}" is referenced but never defined`),
  ]
  return { status: 'ok', issues }
}

function describe(error: { message?: string; component?: string; statementId?: string }): string {
  const where = error.statementId ? `"${error.statementId}"` : error.component ?? 'a component'
  return `${where}: ${error.message ?? 'invalid'}`
}
