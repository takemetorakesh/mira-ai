import { label, rupees } from '../format'
import type { LiveTurn, ToolCallEntry, Turn, TurnError } from '../types'

type Props = { turns: Turn[]; live: LiveTurn | null }

// Structured decisions, not chain of thought: for each turn, which tools ran with what arguments,
// what they returned, what the agent decided to do next, and anything that went wrong.
// Newest turn first and expanded, because that is the decision being explained.
export default function TracePanel({ turns, live }: Props) {
  return (
    <section className="panel trace" aria-label="Agent trace">
      <h2>Trace</h2>
      {live && (
        <TurnTrace title="Current turn" calls={live.tool_calls} errors={live.errors} nextAction={null} open />
      )}
      {[...turns].reverse().map((t, i) => (
        <TurnTrace
          key={t.seq}
          title={`Turn ${t.seq}`}
          calls={t.tool_calls}
          errors={t.errors}
          nextAction={t.next_action}
          open={!live && i === 0}
        />
      ))}
      {!live && turns.length === 0 && <p className="muted">Tool calls appear here as Mira works.</p>}
    </section>
  )
}

function TurnTrace({ title, calls, errors, nextAction, open }: { title: string; calls: ToolCallEntry[]; errors: TurnError[]; nextAction: string | null; open: boolean }) {
  return (
    <details className="turn" open={open}>
      <summary>
        <span>{title}</span>
        <span className="muted"> · {calls.length} tool{calls.length === 1 ? '' : 's'}</span>
        {errors.length > 0 && <span className="badge error">{errors.length} error{errors.length === 1 ? '' : 's'}</span>}
        {nextAction ? <span className="badge next">next: {label(nextAction)}</span> : <span className="badge pending">running…</span>}
      </summary>
      <ol className="calls">
        {calls.map((c) => (
          <li key={c.id} className={`call ${c.status ?? 'pending'}`}>
            <div className="call-head">
              <code>{c.name}</code>
              <span className="muted">{c.status ? `${c.ms} ms` : '…'}</span>
            </div>
            <div className="args">{compactArgs(c.args)}</div>
            {c.result && (
              <details>
                <summary className={c.status === 'error' ? 'result-error' : ''}>{summarize(c)}</summary>
                <pre>{JSON.stringify(c.result, null, 2)}</pre>
              </details>
            )}
          </li>
        ))}
      </ol>
      {errors.map((e, i) => (
        <div key={i} className="banner error small">
          <strong>{label(e.kind)}</strong>
          {e.message && `: ${e.message}`}
          {e.violations?.map((v, j) => <div key={j}>• {v.message}</div>)}
          {e.rejected_reply && <div className="muted">Rejected reply: “{e.rejected_reply}”</div>}
        </div>
      ))}
    </details>
  )
}

function compactArgs(args: unknown): string {
  if (!args || (typeof args === 'object' && Object.keys(args).length === 0)) return '()'
  return JSON.stringify(args)
}

/** One-line reading of a tool result so the trace can be scanned without opening JSON. */
function summarize(c: ToolCallEntry): string {
  const r = c.result ?? {}
  if (r.error) return `${r.error}: ${r.message ?? ''}`
  switch (c.name) {
    case 'update_booking_state': {
      const changed = (r.changes ?? []).map((x: { field: string }) => x.field).join(', ') || 'nothing'
      const issues = (r.issues ?? []).map((x: { code: string }) => x.code).join(', ')
      return `changed: ${changed}${issues ? ` · issues: ${issues}` : ''}`
    }
    case 'search_properties':
      return `match: ${r.match} · ${r.options?.length ?? 0} option(s)${r.sold_out_matches?.length ? ` · ${r.sold_out_matches.length} sold out` : ''}`
    case 'check_availability':
      return r.available ? `available for ${r.rooms_required} room(s)` : `unavailable: ${r.unavailable_nights?.join(', ')}`
    case 'calculate_quote':
      return `total ${rupees(r.total)} (${rupees(r.total_before_tax)} + ${rupees(r.total_tax)} tax)`
    case 'create_booking_hold':
      return `hold ${r.hold_reference} · ${rupees(r.total)} · ${r.hold_minutes} min`
    case 'get_policy':
      return r.known ? `${r.kind}: on file` : `${r.kind}: not on file`
    case 'get_property_details':
      return `${r.name} · ${r.room_types?.length ?? 0} room type(s)`
    case 'get_addons':
      return `${r.addons?.length ?? 0} add-on(s)`
    default:
      return 'result'
  }
}
