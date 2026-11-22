import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import LabelInput from './LabelInput'

describe('LabelInput', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders with email label by default', () => {
    const { container } = render(<LabelInput field="Email" />)
    const label = container.querySelector('.lbi-label')
    expect(label?.textContent).toBe('Email')
    const input = container.querySelector('input')
    expect(input).toBeDefined()
    expect(input?.type).toBe('email')
  })

  it('renders password field with visibility toggle', () => {
    const { container } = render(<LabelInput field="Password" />)
    const label = container.querySelector('.lbi-label')
    expect(label?.textContent).toBe('Password')
    const input = container.querySelector('input') as HTMLInputElement
    expect(input.type).toBe('password')

    const toggle = screen.getByRole('button', { name: /Show password/i })
    fireEvent.click(toggle)
    expect(input.type).toBe('text')

    fireEvent.click(toggle)
    expect(input.type).toBe('password')
  })

  it('updates controlled value and fires onChange', () => {
    const handleChange = vi.fn()
    const { container } = render(<LabelInput field="Email" value="test@example.com" onChange={handleChange} />)
    const input = container.querySelector('input') as HTMLInputElement
    expect(input.value).toBe('test@example.com')

    fireEvent.change(input, { target: { value: 'new@example.com' } })
    expect(handleChange).toHaveBeenCalled()
  })

  it('respects custom corner and width props', () => {
    const { container } = render(<LabelInput field="Email" corner={12} width={320} />)
    const box = container.querySelector('.lbi-box') as HTMLElement
    expect(box.style.width).toBe('320px')
    expect(box.style.borderRadius).toBe('12px')
  })
})

