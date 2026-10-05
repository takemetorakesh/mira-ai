import { useCallback, useEffect, useRef, useState } from 'react'
import { createConversation, getConversation, sendMessage, type ConversationResponse } from './api'
import ChatPanel from './components/ChatPanel'
import Header from './components/Header'
import StatePanel from './components/StatePanel'
import TracePanel from './components/TracePanel'
import type { BookingState, LiveTurn, StateChange, Turn } from './types'

const STORAGE_KEY = 'mira.conversationId'

function readStoredId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function storeId(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* storage unavailable: the conversation just won't survive a reload */
  }
}

async function newConversation(): Promise<ConversationResponse> {
  const conv = await createConversation()
  storeId(conv.id)
  return conv
}

/** Reopen the conversation from before a reload, or start a new one if there isn't one (e.g. after a re-seed). */
async function openConversation(): Promise<ConversationResponse> {
  const id = readStoredId()
  if (id) {
    try {
      return await getConversation(id)
    } catch {
      // fall through to a fresh conversation
    }
  }
  return newConversation()
}

export default function App() {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [today, setToday] = useState<string>('')
  const [state, setState] = useState<BookingState | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [live, setLive] = useState<LiveTurn | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)

  const show = useCallback((conv: ConversationResponse) => {
    setConversationId(conv.id)
    setToday(conv.today)
    setState(conv.state)
    setTurns(conv.turns ?? [])
    setLive(null)
  }, [])

  const startNew = () => {
    setFatal(null)
    newConversation()
      .then(show)
      .catch((e) => setFatal(String(e)))
  }

  const opened = useRef(false)
  useEffect(() => {
    if (opened.current) return // StrictMode runs effects twice in dev; don't open two conversations
    opened.current = true
    openConversation()
      .then(show)
      .catch((e) => setFatal(String(e)))
  }, [show])

  const send = async (text: string) => {
    if (!conversationId || live) return
    setFatal(null)
    let current: LiveTurn = { user_message: text, tool_calls: [], errors: [], changes: [] }
    setLive(current)
    const update = (patch: Partial<LiveTurn>) => {
      current = { ...current, ...patch }
      setLive(current)
    }
    try {
      for await (const { event, data } of sendMessage(conversationId, text)) {
        if (event === 'tool_call') {
          update({ tool_calls: [...current.tool_calls, { id: data.id, name: data.name, args: data.arguments }] })
        } else if (event === 'tool_result') {
          update({ tool_calls: current.tool_calls.map((c) => (c.id === data.id ? data : c)) })
        } else if (event === 'state') {
          setState(data.state)
          update({ changes: mergeChanges(current.changes, data.changes) })
        } else if (event === 'error') {
          update({ errors: [...current.errors, data] })
        } else if (event === 'done') {
          const { state: finalState, ...turn } = data
          setState(finalState)
          setTurns((ts) => [...ts, turn as Turn])
          setLive(null)
        } else if (event === 'fatal') {
          setFatal(data.message)
          setLive(null)
        }
      }
    } catch (e) {
      setFatal(String(e))
      setLive(null)
    }
  }

  const lastChanges = live?.changes ?? turns.at(-1)?.state_diff ?? []

  return (
    <div className="app">
      <Header today={today} busy={!!live} onNew={startNew} />
      <main className="layout">
        <ChatPanel turns={turns} live={live} fatal={fatal} onSend={send} />
        <aside className="inspector">
          <StatePanel state={state} changed={new Set(lastChanges.map((c) => c.field))} />
          <TracePanel turns={turns} live={live} />
        </aside>
      </main>
    </div>
  )
}

function mergeChanges(prev: StateChange[], next: StateChange[]): StateChange[] {
  const byField = new Map(prev.map((c) => [c.field, c]))
  for (const c of next) byField.set(c.field, { field: c.field, from: byField.get(c.field)?.from ?? c.from, to: c.to })
  return [...byField.values()]
}
