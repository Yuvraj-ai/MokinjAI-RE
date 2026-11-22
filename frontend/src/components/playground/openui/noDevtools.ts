/**
 * `@openuidev/react-lang` mounts its "OpenUI Inspect" widget in development
 * builds (it never ships in production). The widget advertises a hosted Thesys
 * service and floats over the Playground, so it is switched off here using the
 * package's own "already mounted" flag. Must be imported before react-lang.
 */
;(globalThis as Record<symbol, unknown>)[Symbol.for('openui.devtools.autoMount')] = true

export {}
