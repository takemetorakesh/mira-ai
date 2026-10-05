type Props = { today: string; onNew: () => void; busy: boolean }

// "Today" is shown because every relative date ("this weekend", "till the 13th") is resolved against it.
export default function Header({ today, onNew, busy }: Props) {
  const day = today
    ? new Date(`${today}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
    : '…'
  return (
    <header className="header">
      <div className="brand">
        <span className="logo">M</span>
        <div>
          <strong>Mira</strong>
          <span className="muted"> · guest booking agent</span>
        </div>
      </div>
      <div className="header-right">
        <span className="today" title="Relative dates are resolved against this date">
          Today: {day}
        </span>
        <button onClick={onNew} disabled={busy}>
          New conversation
        </button>
      </div>
    </header>
  )
}
