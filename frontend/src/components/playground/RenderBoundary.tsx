import { Component, type ErrorInfo, type ReactNode } from 'react'

interface RenderBoundaryProps {
  children: ReactNode
  /** What to show when the children throw while rendering. */
  fallback: ReactNode
}

/**
 * Isolates a renderer crash to one reply. Model output is untrusted, so a
 * renderer must never be able to take the rest of the Playground down.
 */
export default class RenderBoundary extends Component<
  RenderBoundaryProps,
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Reply renderer failed', error, info.componentStack)
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
