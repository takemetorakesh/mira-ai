export const rupees = (n: number | null | undefined) => (n == null ? '—' : `₹${n.toLocaleString('en-IN')}`)

export const prettyId = (id: string) => id.replace(/-/g, ' ')

export const label = (s: string) => s.replace(/_/g, ' ')

export function timeLeft(iso: string, now: number): string {
  const ms = new Date(iso).getTime() - now
  if (ms <= 0) return 'expired'
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}:${String(s).padStart(2, '0')} left`
}
