import React from 'react'
import { cn } from '../../lib/utils'

export interface SpinnerProps extends React.SVGAttributes<SVGSVGElement> {
  /**
   * 'sharp': 8-spoke sharp line iOS spinner for small/tight spaces (buttons, badges, table cells)
   * 'default': 12-spoke rounded capsule iOS spinner for ample spaces (pages, cards, dialogs)
   * 'auto': automatically selects 'sharp' for small sizes (<=16px / w-3, w-4) and 'default' for larger
   */
  variant?: 'default' | 'sharp' | 'auto'
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}

const DEFAULT_12_SPOKES = Array.from({ length: 12 }, (_, i) => ({
  angle: i * 30,
  delay: `${-(((12 - i) % 12) / 12 * 1.0).toFixed(4)}s`,
}))

const SHARP_8_SPOKES = Array.from({ length: 8 }, (_, i) => ({
  angle: i * 45,
  delay: `${-(((8 - i) % 8) / 8 * 0.8).toFixed(4)}s`,
}))

const SIZE_CLASSES = {
  xs: 'w-3 h-3',
  sm: 'w-3.5 h-3.5',
  md: 'w-5 h-5',
  lg: 'w-6 h-6',
  xl: 'w-8 h-8',
}

/**
 * Line sharp small iOS spinner (8 radial sharp line spokes, 45deg intervals).
 * Engineered specifically for compact/small spaces: buttons, status chips, table rows, and toolbars.
 * Spokes remain stationary while brightness sweeps clockwise with a fading tail.
 */
export const IosSharpSpinner = React.forwardRef<SVGSVGElement, React.SVGProps<SVGSVGElement>>(
  ({ className, ...props }, ref) => {
    return (
      <svg
        ref={ref}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className={cn('shrink-0 text-current', className)}
        {...props}
      >
        {SHARP_8_SPOKES.map(({ angle, delay }) => (
          <line
            key={angle}
            x1="12"
            y1="2"
            x2="12"
            y2="6.5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="square"
            className="ios-spoke-sharp"
            style={{ animationDelay: delay }}
            transform={`rotate(${angle} 12 12)`}
          />
        ))}
      </svg>
    )
  }
)
IosSharpSpinner.displayName = 'IosSharpSpinner'

/**
 * Default iOS activity indicator (12 radial rounded capsules, 30deg intervals).
 * Engineered for ample space: page loaders, section loaders, cards, empty states, and dialogs.
 * Spokes remain stationary while brightness sweeps clockwise with a fading tail.
 */
export const IosDefaultSpinner = React.forwardRef<SVGSVGElement, React.SVGProps<SVGSVGElement>>(
  ({ className, ...props }, ref) => {
    return (
      <svg
        ref={ref}
        viewBox="0 0 24 24"
        fill="none"
        role="status"
        aria-label="Loading"
        className={cn('shrink-0 text-current', className)}
        {...props}
      >
        {DEFAULT_12_SPOKES.map(({ angle, delay }) => (
          <line
            key={angle}
            x1="12"
            y1="2.2"
            x2="12"
            y2="6.6"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            className="ios-spoke"
            style={{ animationDelay: delay }}
            transform={`rotate(${angle} 12 12)`}
          />
        ))}
      </svg>
    )
  }
)
IosDefaultSpinner.displayName = 'IosDefaultSpinner'

/**
 * Universal Spinner component.
 * Automatically chooses:
 * - Line sharp small iOS spinner for small/tight spaces (size <= 16px, e.g. xs, sm, w-3, w-3.5, w-4)
 * - Default iOS spinner for ample space (size >= 20px, e.g. md, lg, xl, w-5, w-6, w-8)
 */
export function Spinner({
  variant = 'auto',
  size,
  className,
  ...props
}: SpinnerProps) {
  const isSmallClass = className && /(w-[1234]\b|h-[1234]\b|w-3\.5|h-3\.5)/.test(className)
  const isSmallSize = size === 'xs' || size === 'sm'

  const resolvedVariant =
    variant === 'auto' ? (isSmallClass || isSmallSize ? 'sharp' : 'default') : variant

  const defaultSizeClass = size ? SIZE_CLASSES[size] : resolvedVariant === 'sharp' ? 'w-3.5 h-3.5' : 'w-5 h-5'

  if (resolvedVariant === 'sharp') {
    return <IosSharpSpinner className={cn(defaultSizeClass, className)} {...props} />
  }

  return <IosDefaultSpinner className={cn(defaultSizeClass, className)} {...props} />
}

export default Spinner
