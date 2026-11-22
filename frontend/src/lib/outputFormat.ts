import type { AgentCapabilities, OutputFormat } from '../api/agents'

/**
 * Output-format state for the Playground. Eligibility is decided by the
 * server (capabilities.output_formats). The 200,000 figure below is only the
 * explanation shown to the user; it is never used to decide anything here.
 */

export const DEFAULT_OUTPUT_FORMAT: OutputFormat = 'markdown'

export const OUTPUT_FORMAT_LABELS: Record<OutputFormat, string> = {
  markdown: 'Markdown',
  openui: 'OpenUI',
}

/** The formats this model may use. Missing capabilities mean Markdown only. */
export function availableFormats(capabilities: AgentCapabilities | null | undefined): OutputFormat[] {
  const formats = capabilities?.output_formats
  if (!formats || formats.length === 0) return [DEFAULT_OUTPUT_FORMAT]
  return formats.includes(DEFAULT_OUTPUT_FORMAT) ? formats : [DEFAULT_OUTPUT_FORMAT, ...formats]
}

/** Keep the user's choice when the new model supports it, else fall back to Markdown. */
export function reconcileFormat(current: OutputFormat, available: OutputFormat[]): OutputFormat {
  return available.includes(current) ? current : DEFAULT_OUTPUT_FORMAT
}

/** Why OpenUI is unavailable, phrased for the composer hint. */
export function openUiUnavailableReason(capabilities: AgentCapabilities | null | undefined): string {
  const window = capabilities?.context_window
  const have =
    typeof window === 'number' && window > 0
      ? `This model has ${window.toLocaleString('en-US')}.`
      : "This model's context window is unknown."
  return `OpenUI needs a 200,000-token context window. ${have}`
}
