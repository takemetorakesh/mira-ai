import { useEffect, useState } from 'react'
import { label, prettyId, rupees, timeLeft } from '../format'
import type { BookingState } from '../types'

type Props = { state: BookingState | null; changed: Set<string> }

// The agent's memory, laid out as a front-desk booking card. Fields changed in the latest turn are
// highlighted so state updates ("make that 4 people") are visible; fields search needs but doesn't
// have yet are marked, which is exactly what the agent should be asking for.
export default function StatePanel({ state, changed }: Props) {
  const now = useNow(!!state?.hold)
  if (!state) return <section className="panel">Loading…</section>

  const guests =
    state.adults == null
      ? null
      : `${state.adults} adult${state.adults === 1 ? '' : 's'}${state.children ? ` + ${state.children} child${state.children === 1 ? '' : 'ren'}` : ''}`

  return (
    <section className="panel" aria-label="Booking state">
      <h2>Booking state</h2>
      <dl className="fields">
        <Field name="Destination" value={state.city} required changed={changed.has('city')} />
        <Field
          name="Dates"
          value={state.stay ? `${state.stay} · ${state.nights} night${state.nights === 1 ? '' : 's'}` : null}
          required
          changed={changed.has('check_in') || changed.has('check_out')}
        />
        <Field name="Guests" value={guests} required changed={changed.has('adults') || changed.has('children')} />
        <Field name="Rooms" value={String(state.rooms)} changed={changed.has('rooms')} />
        <Field name="Budget / night" value={state.budget_per_night ? rupees(state.budget_per_night) : null} changed={changed.has('budget_per_night')} />
        <Field name="Preferences" value={state.preferences.length ? state.preferences.map(label).join(', ') : null} changed={changed.has('preferences')} />
        <Field name="Requests" value={state.special_requests.length ? state.special_requests.join(', ') : null} changed={changed.has('special_requests')} />
      </dl>

      <h3>Selection</h3>
      <dl className="fields">
        <Field name="Room" value={state.selected_room_type_id ? prettyId(state.selected_room_type_id) : null} changed={changed.has('selected_room_type_id')} />
        <Field name="Add-ons" value={state.addon_ids.length ? state.addon_ids.map(prettyId).join(', ') : null} changed={changed.has('addon_ids')} />
        <Field name="Guest name" value={state.guest_name} changed={changed.has('guest_name')} />
        <Field
          name="Quote"
          value={state.last_quote ? `${rupees(state.last_quote.total)} · ${prettyId(state.last_quote.room_type_id)}` : null}
          changed={changed.has('last_quote')}
        />
        <Field
          name="Hold"
          value={state.hold ? `${state.hold.id.slice(0, 8).toUpperCase()} · ${rupees(state.hold.total)} · ${timeLeft(state.hold.expires_at, now)}` : null}
          changed={changed.has('hold')}
        />
      </dl>

      {state.shown_options.length > 0 && (
        <>
          {/* What "the other one" / "the cheaper one" refers to on the next turn. */}
          <h3 className={changed.has('shown_options') ? 'changed-heading' : ''}>Options shown to guest</h3>
          <ol className="options">
            {state.shown_options.map((o) => (
              <li key={o.room_type_id}>
                {o.room_name} · {o.property_name}
                <span className="muted">
                  {' '}
                  {o.rooms > 1 ? `${o.rooms} rooms · ` : ''}
                  {rupees(o.avg_room_cost_per_night)}/night
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  )
}

function Field({ name, value, required, changed }: { name: string; value: string | null; required?: boolean; changed?: boolean }) {
  return (
    <div className={`field${changed ? ' changed' : ''}`}>
      <dt>{name}</dt>
      <dd>{value ?? <span className={required ? 'missing' : 'muted'}>{required ? 'needed to search' : '—'}</span>}</dd>
    </div>
  )
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}
