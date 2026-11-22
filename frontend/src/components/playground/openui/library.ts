import {
  openuiChatAdditionalRules,
  openuiChatExamples,
  openuiChatLibrary,
} from '@openuidev/react-ui/genui-lib'

/**
 * The OpenUI component library the Playground renders, and the one the backend
 * prompt is generated from (see openuiPrompt.test.ts). Both must stay the same
 * library, or the model is taught components the renderer then drops.
 *
 * Based on OpenUI's chat library (root `Card`). Components whose job is to show
 * a remote image are removed: model output is untrusted, and an image URL is a
 * way to leak data to a third party. The CSP blocks remote images as well.
 */
export const REMOVED_COMPONENTS = [
  'Image',
  'ImageBlock',
  'ImageGallery',
  'ImageText',
  'ImageTextLarge',
  'ContextCardItem',
  'ContextCardBlock',
  'VisualCardItem',
  'VisualCardBlock',
] as const

export const playgroundLibrary = openuiChatLibrary.extend({
  components: { remove: [...REMOVED_COMPONENTS] },
})

/**
 * Upstream chat rules minus the ones that would mislead an agent platform:
 * inventing data, and the image rules for components removed above.
 */
const DROPPED_RULE_PATTERNS = [
  /generate realistic\/plausible data/i,
  /Every image slot/i,
  /If no image URL is in context/i,
  /Argument-order trap/i,
  /ListBlock variant "number"/i,
]

export const PLAYGROUND_RULES = [
  ...openuiChatAdditionalRules.filter(
    (rule) => !DROPPED_RULE_PATTERNS.some((pattern) => pattern.test(rule))
  ),
  'Never invent facts or numbers. Use only information from the conversation, the system prompt and tool results; say so when something is unknown.',
  'Images are not displayed in this interface: do not use image URLs or the ListBlock "image" variant.',
  'Only @OpenUrl links that came from the user or a tool result.',
]

/** Upstream examples that use only components still in the library. */
export const PLAYGROUND_EXAMPLES = openuiChatExamples.filter(
  (example) => !REMOVED_COMPONENTS.some((name) => new RegExp(`\\b${name}\\(`).test(example))
)

export const PLAYGROUND_PREAMBLE =
  'Write your final reply to the user as an OpenUI Lang program, following the rules below. ' +
  'Output only the program: no prose before or after it and no code fences. ' +
  'Tool calls and their results are unaffected; this applies to the final reply only.'

export function playgroundPrompt(): string {
  return playgroundLibrary.prompt({
    preamble: PLAYGROUND_PREAMBLE,
    additionalRules: PLAYGROUND_RULES,
    examples: PLAYGROUND_EXAMPLES,
  })
}
