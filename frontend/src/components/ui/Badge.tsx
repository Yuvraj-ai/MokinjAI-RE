import React from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Clock,
  MinusCircle,
  Send,
  Sparkles,
} from 'lucide-react'
import { cn } from '../../lib/utils'

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'purple' | 'orange'

export interface StatusConfig {
  tone: BadgeTone
  icon: LucideIcon
  label: string
  spin?: boolean
}

export const STATUS_CONFIG: Record<string, StatusConfig> = {
  // Success / Ready
  ready: { tone: 'success', icon: CheckCircle2, label: 'Ready' },
  completed: { tone: 'success', icon: CheckCircle2, label: 'Completed' },
  active: { tone: 'success', icon: CheckCircle2, label: 'Active' },
  verified: { tone: 'success', icon: CheckCircle2, label: 'Verified' },
  connected: { tone: 'success', icon: CheckCircle2, label: 'Connected' },
  ok: { tone: 'success', icon: CheckCircle2, label: 'Connected' },
  success: { tone: 'success', icon: CheckCircle2, label: 'Success' },

  // Progress / Running
  running: { tone: 'info', icon: Loader2, label: 'Running', spin: true },
  in_progress: { tone: 'info', icon: Loader2, label: 'In progress', spin: true },
  checking: { tone: 'info', icon: Loader2, label: 'Checking…', spin: true },

  // Attention / Pending
  pending: { tone: 'warning', icon: AlertTriangle, label: 'Pending' },
  waiting: { tone: 'warning', icon: Clock, label: 'Waiting' },
  queued: { tone: 'warning', icon: Clock, label: 'Queued' },
  needs_attention: { tone: 'warning', icon: AlertTriangle, label: 'Needs attention' },
  warning: { tone: 'warning', icon: AlertTriangle, label: 'Warning' },
  in_review: { tone: 'warning', icon: Sparkles, label: 'In review' },

  // Submitted
  submitted: { tone: 'purple', icon: Send, label: 'Submitted' },

  // Danger / Errors
  failed: { tone: 'danger', icon: XCircle, label: 'Failed' },
  error: { tone: 'danger', icon: XCircle, label: 'Error' },
  revoked: { tone: 'danger', icon: XCircle, label: 'Revoked' },
  cancelled: { tone: 'danger', icon: XCircle, label: 'Cancelled' },

  // Inactive / Neutral
  disabled: { tone: 'neutral', icon: MinusCircle, label: 'Disabled' },
  expired: { tone: 'neutral', icon: Clock, label: 'Expired' },
  archived: { tone: 'neutral', icon: MinusCircle, label: 'Archived' },
  draft: { tone: 'neutral', icon: Clock, label: 'Draft' },
  untested: { tone: 'neutral', icon: Clock, label: 'Untested' },
}

export function formatStatusLabel(raw: string): string {
  if (!raw) return ''
  const words = raw.trim().replace(/[-_]+/g, ' ').split(' ')
  return words
    .map((w, idx) => (idx === 0 ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w.toLowerCase()))
    .join(' ')
}

export function resolveStatusConfig(rawStatus: string): StatusConfig {
  const clean = (rawStatus || '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  if (STATUS_CONFIG[clean]) {
    return STATUS_CONFIG[clean]
  }

  if (/^(fail|err|revok|cancel|reject)/.test(clean)) {
    return { tone: 'danger', icon: XCircle, label: formatStatusLabel(rawStatus) }
  }
  if (/^(run|prog|load|check)/.test(clean)) {
    return { tone: 'info', icon: Loader2, label: formatStatusLabel(rawStatus), spin: true }
  }
  if (/^(pend|wait|queu)/.test(clean)) {
    return { tone: 'warning', icon: AlertTriangle, label: formatStatusLabel(rawStatus) }
  }
  if (/^(need|warn|attent)/.test(clean)) {
    return { tone: 'warning', icon: AlertTriangle, label: formatStatusLabel(rawStatus) }
  }
  if (/^(review)/.test(clean)) {
    return { tone: 'warning', icon: Sparkles, label: formatStatusLabel(rawStatus) }
  }
  if (/^(submit)/.test(clean)) {
    return { tone: 'purple', icon: Send, label: formatStatusLabel(rawStatus) }
  }
  if (/^(read|ok|done|pass|succ|verif|connect|activ)/.test(clean)) {
    return { tone: 'success', icon: CheckCircle2, label: formatStatusLabel(rawStatus) }
  }
  if (/^(expir)/.test(clean)) {
    return { tone: 'neutral', icon: Clock, label: formatStatusLabel(rawStatus) }
  }
  if (/^(disab|inactiv|archiv)/.test(clean)) {
    return { tone: 'neutral', icon: MinusCircle, label: formatStatusLabel(rawStatus) }
  }

  return { tone: 'neutral', icon: Clock, label: formatStatusLabel(rawStatus) }
}

const toneStyles: Record<BadgeTone, { text: string; bg: string; border: string; defaultIcon: LucideIcon }> = {
  neutral: {
    text: 'text-ink-muted',
    bg: 'bg-surface-muted',
    border: 'border-line',
    defaultIcon: Clock,
  },
  success: {
    text: 'text-status-success',
    bg: 'bg-status-success-soft',
    border: 'border-current/15',
    defaultIcon: CheckCircle2,
  },
  warning: {
    text: 'text-status-warning',
    bg: 'bg-status-warning-soft',
    border: 'border-current/15',
    defaultIcon: AlertTriangle,
  },
  danger: {
    text: 'text-status-error',
    bg: 'bg-status-error-soft',
    border: 'border-current/15',
    defaultIcon: XCircle,
  },
  info: {
    text: 'text-status-info',
    bg: 'bg-status-info-soft',
    border: 'border-current/15',
    defaultIcon: Loader2,
  },
  purple: {
    text: 'text-purple-700 dark:text-purple-300',
    bg: 'bg-purple-50 dark:bg-purple-950/40',
    border: 'border-current/15',
    defaultIcon: Send,
  },
  orange: {
    text: 'text-orange-700 dark:text-orange-300',
    bg: 'bg-orange-50 dark:bg-orange-950/40',
    border: 'border-current/15',
    defaultIcon: AlertTriangle,
  },
}

export interface StatusBadgeProps {
  status: string
  label?: React.ReactNode
  size?: 'sm' | 'md'
  tone?: BadgeTone
  icon?: LucideIcon | React.ComponentType<{ className?: string }>
  spin?: boolean
  className?: string
  children?: React.ReactNode
}

/**
 * Modern status chip/badge inspired by high-end design systems.
 * Uses soft squircle rounded corners, a meaningful Lucide icon,
 * clear semantic text, and completely avoids redundant colored dots.
 */
export function StatusBadge({
  status,
  label,
  size = 'md',
  tone: overrideTone,
  icon: overrideIcon,
  spin: overrideSpin,
  className,
  children,
}: StatusBadgeProps) {
  const resolved = resolveStatusConfig(status)
  const tone = overrideTone ?? resolved.tone
  const IconComponent = overrideIcon ?? resolved.icon
  const shouldSpin = overrideSpin ?? (resolved.spin && IconComponent === Loader2)
  const displayLabel = children ?? label ?? resolved.label
  const currentTone = toneStyles[tone] ?? toneStyles.neutral

  const isSmall = size === 'sm'

  return (
    <span
      className={cn(
        'inline-flex items-center select-none font-medium transition-colors duration-150',
        // Squircle geometry matching design inspiration
        isSmall
          ? 'gap-1 rounded-[7px] border px-2 py-0.5 text-[11px] leading-tight'
          : 'gap-1.5 rounded-[9px] border px-2.5 py-1 text-xs leading-none',
        currentTone.bg,
        currentTone.text,
        currentTone.border,
        className,
      )}
    >
      {IconComponent && (
        <IconComponent
          className={cn(
            'shrink-0 stroke-[2.2]',
            isSmall ? 'h-3 w-3' : 'h-3.5 w-3.5',
            shouldSpin && 'animate-spin',
          )}
          aria-hidden
        />
      )}
      <span>{displayLabel}</span>
    </span>
  )
}

/**
 * General Badge component.
 * variant="outline": mono micro-badge for kinds/roles ("Admin", "Built-in").
 * variant="soft": soft squircle badge; if dot is true, it renders the tone's semantic icon.
 */
export default function Badge({
  tone = 'neutral',
  variant = 'soft',
  size = 'md',
  dot = false,
  icon: IconProp,
  className,
  children,
}: {
  tone?: BadgeTone
  variant?: 'soft' | 'outline'
  size?: 'sm' | 'md'
  dot?: boolean
  icon?: LucideIcon | React.ComponentType<{ className?: string }>
  className?: string
  children: React.ReactNode
}) {
  const currentTone = toneStyles[tone] ?? toneStyles.neutral
  const isSmall = size === 'sm'

  if (variant === 'outline') {
    return (
      <span
        className={cn(
          'inline-flex items-center rounded-[7px] border border-line px-2 py-0.5',
          'text-[10px] font-mono uppercase tracking-wide select-none',
          tone === 'neutral' ? 'text-ink-muted' : currentTone.text,
          className,
        )}
      >
        {children}
      </span>
    )
  }

  // If dot was explicitly asked for or an icon was provided, render semantic icon
  const IconComponent = IconProp ?? (dot ? currentTone.defaultIcon : undefined)
  const shouldSpin = IconComponent === Loader2

  return (
    <span
      className={cn(
        'inline-flex items-center select-none font-medium transition-colors duration-150',
        isSmall
          ? 'gap-1 rounded-[7px] border px-2 py-0.5 text-[11px] leading-tight'
          : 'gap-1.5 rounded-[9px] border px-2.5 py-1 text-xs leading-none',
        currentTone.bg,
        currentTone.text,
        currentTone.border,
        className,
      )}
    >
      {IconComponent && (
        <IconComponent
          className={cn(
            'shrink-0 stroke-[2.2]',
            isSmall ? 'h-3 w-3' : 'h-3.5 w-3.5',
            shouldSpin && 'animate-spin',
          )}
          aria-hidden
        />
      )}
      <span>{children}</span>
    </span>
  )
}
