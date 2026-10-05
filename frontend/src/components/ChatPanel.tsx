import { useEffect, useRef, useState } from 'react'
import type { LiveTurn, Turn } from '../types'

type Props = { turns: Turn[]; live: LiveTurn | null; fatal: string | null; onSend: (text: string) => void }

const SUGGESTIONS = [
  'Looking for something in Goa this weekend for my 2 friends and me. Something private would be nice.',
  'Travelling with my wife and 2 kids to Goa next weekend, something with a private pool under 20k',
  'Is the pool at Snowline in Manali heated?',
]

// Plain text bubbles only: Mehman's real channels (WhatsApp, Instagram) are text-first,
// so the demo shows exactly what a guest would see there.
export default function ChatPanel({ turns, live, fatal, onSend }: Props) {
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length, live?.user_message, fatal])

  const submit = (value: string) => {
    const v = value.trim()
    if (!v || live) return
    onSend(v)
    setText('')
  }

  return (
    <section className="chat" aria-label="Guest conversation">
      <div className="messages">
        {turns.length === 0 && !live && (
          <div className="empty">
            <p className="muted">Chat as a guest. Try:</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => submit(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t) => (
          <div key={t.seq}>
            <div className="bubble guest">{t.user_message}</div>
            <div className="bubble mira">{t.reply}</div>
          </div>
        ))}
        {live && (
          <>
            <div className="bubble guest">{live.user_message}</div>
            <div className="bubble mira typing">Mira is checking{live.tool_calls.length ? ` (${live.tool_calls.at(-1)!.name})` : ''}…</div>
          </>
        )}
        {fatal && <div className="banner error">{fatal}</div>}
        <div ref={endRef} />
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          submit(text)
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={live ? 'Waiting for Mira…' : 'Message Mira as a guest'}
          disabled={!!live}
          autoFocus
        />
        {/* One message at a time: the server processes turns sequentially per conversation. */}
        <button type="submit" disabled={!!live || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  )
}
