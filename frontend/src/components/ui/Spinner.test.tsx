import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Spinner, { IosSharpSpinner, IosDefaultSpinner } from './Spinner'

describe('iOS Spinners', () => {
  describe('IosSharpSpinner', () => {
    it('renders 8 sharp line spokes with clockwise fading animation', () => {
      const { container } = render(<IosSharpSpinner className="w-4 h-4" />)
      const svg = container.querySelector('svg')
      expect(svg).toBeDefined()
      const lines = container.querySelectorAll('line')
      expect(lines.length).toBe(8)
      expect(lines[0].getAttribute('stroke-linecap')).toBe('square')
      expect(lines[0].classList.contains('ios-spoke-sharp')).toBe(true)
      // Check negative delays cascade clockwise
      expect(lines[0].style.animationDelay).toMatch(/^(0s|-?0(\.0+)?s)$/)
      expect(lines[1].style.animationDelay).toMatch(/-0\.7/)
    })
  })

  describe('IosDefaultSpinner', () => {
    it('renders 12 rounded capsule spokes with clockwise fading animation', () => {
      const { container } = render(<IosDefaultSpinner className="w-6 h-6" />)
      const svg = container.querySelector('svg')
      expect(svg).toBeDefined()
      const lines = container.querySelectorAll('line')
      expect(lines.length).toBe(12)
      expect(lines[0].getAttribute('stroke-linecap')).toBe('round')
      expect(lines[0].classList.contains('ios-spoke')).toBe(true)
      // Check negative delays cascade clockwise
      expect(lines[0].style.animationDelay).toMatch(/^(0s|-?0(\.0+)?s)$/)
      expect(lines[1].style.animationDelay).toMatch(/-0\.916/)
    })
  })

  describe('Spinner auto resolution', () => {
    it('chooses sharp variant when small size or small classes are provided', () => {
      const { container: c1 } = render(<Spinner size="sm" />)
      expect(c1.querySelectorAll('line').length).toBe(8)

      const { container: c2 } = render(<Spinner className="w-3.5 h-3.5" />)
      expect(c2.querySelectorAll('line').length).toBe(8)

      const { container: c3 } = render(<Spinner className="w-4 h-4" />)
      expect(c3.querySelectorAll('line').length).toBe(8)
    })

    it('chooses default variant when ample space size or classes are provided', () => {
      const { container: c1 } = render(<Spinner size="lg" />)
      expect(c1.querySelectorAll('line').length).toBe(12)

      const { container: c2 } = render(<Spinner className="w-6 h-6" />)
      expect(c2.querySelectorAll('line').length).toBe(12)

      const { container: c3 } = render(<Spinner />)
      expect(c3.querySelectorAll('line').length).toBe(12)
    })

    it('respects explicit variant overrides', () => {
      const { container: c1 } = render(<Spinner variant="sharp" className="w-8 h-8" />)
      expect(c1.querySelectorAll('line').length).toBe(8)

      const { container: c2 } = render(<Spinner variant="default" className="w-3 h-3" />)
      expect(c2.querySelectorAll('line').length).toBe(12)
    })
  })
})
