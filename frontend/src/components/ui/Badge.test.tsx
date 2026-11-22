import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Badge, { StatusBadge, resolveStatusConfig, formatStatusLabel } from './Badge'
import { CheckCircle2, XCircle, AlertTriangle, Clock } from 'lucide-react'
import { IosSharpSpinner } from './Spinner'

describe('Badge and StatusBadge', () => {
  describe('formatStatusLabel', () => {
    it('formats snake_case into Title case', () => {
      expect(formatStatusLabel('needs_attention')).toBe('Needs attention')
      expect(formatStatusLabel('in_progress')).toBe('In progress')
      expect(formatStatusLabel('completed')).toBe('Completed')
    })
  })

  describe('resolveStatusConfig', () => {
    it('resolves standard success statuses', () => {
      expect(resolveStatusConfig('ready')).toMatchObject({ tone: 'success', label: 'Ready', icon: CheckCircle2 })
      expect(resolveStatusConfig('completed')).toMatchObject({ tone: 'success', label: 'Completed', icon: CheckCircle2 })
      expect(resolveStatusConfig('active')).toMatchObject({ tone: 'success', label: 'Active', icon: CheckCircle2 })
    })

    it('resolves failure statuses', () => {
      expect(resolveStatusConfig('failed')).toMatchObject({ tone: 'danger', label: 'Failed', icon: XCircle })
      expect(resolveStatusConfig('error')).toMatchObject({ tone: 'danger', label: 'Error', icon: XCircle })
      expect(resolveStatusConfig('revoked')).toMatchObject({ tone: 'danger', label: 'Revoked', icon: XCircle })
    })

    it('resolves running/progress statuses', () => {
      expect(resolveStatusConfig('running')).toMatchObject({ tone: 'info', label: 'Running', icon: IosSharpSpinner })
      expect(resolveStatusConfig('in_progress')).toMatchObject({ tone: 'info', label: 'In progress', icon: IosSharpSpinner })
    })

    it('resolves pending and warning statuses', () => {
      expect(resolveStatusConfig('pending')).toMatchObject({ tone: 'warning', label: 'Pending', icon: AlertTriangle })
      expect(resolveStatusConfig('needs_attention')).toMatchObject({ tone: 'warning', label: 'Needs attention', icon: AlertTriangle })
    })

    it('resolves inactive/expired statuses', () => {
      expect(resolveStatusConfig('expired')).toMatchObject({ tone: 'neutral', label: 'Expired', icon: Clock })
      expect(resolveStatusConfig('disabled')).toMatchObject({ tone: 'neutral', label: 'Disabled' })
    })
  })

  describe('StatusBadge component', () => {
    it('renders ready status without dot and with squircle styling', () => {
      const { container } = render(<StatusBadge status="ready" />)
      expect(screen.getByText('Ready')).toBeDefined()
      // No dot element
      expect(container.querySelector('.rounded-full')).toBeNull()
      // Contains squircle radius
      expect(container.firstElementChild?.className).toContain('rounded-[9px]')
    })

    it('supports custom label override', () => {
      render(<StatusBadge status="completed" label="Task Finished" />)
      expect(screen.getByText('Task Finished')).toBeDefined()
    })

    it('supports small size', () => {
      const { container } = render(<StatusBadge status="active" size="sm" />)
      expect(container.firstElementChild?.className).toContain('rounded-[7px]')
      expect(container.firstElementChild?.className).toContain('text-[11px]')
    })
  })

  describe('Badge component', () => {
    it('renders outline variant with modern squircle', () => {
      const { container } = render(<Badge variant="outline">Admin</Badge>)
      expect(screen.getByText('Admin')).toBeDefined()
      expect(container.firstElementChild?.className).toContain('rounded-[7px]')
      expect(container.firstElementChild?.className).toContain('border-line')
    })

    it('converts dot request to semantic icon instead of raw dot', () => {
      const { container } = render(<Badge tone="success" dot>Verified</Badge>)
      expect(screen.getByText('Verified')).toBeDefined()
      // Raw dot element with rounded-full should NOT exist
      expect(container.querySelector('span.rounded-full')).toBeNull()
      // Lucide icon SVG exists
      expect(container.querySelector('svg')).toBeDefined()
    })
  })
})
