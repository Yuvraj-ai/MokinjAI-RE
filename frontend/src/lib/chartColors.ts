/** Series colours: legible on both the light and the dark theme. */
export const PALETTE = [
  '#F59E0B',
  '#EC4899',
  '#3B82F6',
  '#10B981',
  '#8B5CF6',
  '#EF4444',
  '#14B8A6',
  '#9CA3AF',
]

export const colorAt = (index: number) => PALETTE[index % PALETTE.length]

export interface ChartSeries {
  key: string
  label: string
  color: string
  values: number[]
}
