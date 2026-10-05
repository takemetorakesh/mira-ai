import type { BookingState, Turn } from './types'

export type ConversationResponse = { id: string; state: BookingState; today: string; turns?: Turn[] }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const createConversation = () =>
  fetch('/api/conversations', { method: 'POST' }).then(json<ConversationResponse>)

export const getConversation = (id: string) =>
  fetch(`/api/conversations/${id}`).then(json<ConversationResponse>)

export type StreamEvent = { event: string; data: any }

/** POST a guest message and yield Server-Sent Events as they arrive (EventSource cannot POST). */
export async function* sendMessage(id: string, text: string): AsyncGenerator<StreamEvent> {
  const res = await fetch(`/api/conversations/${id}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const event = /^event: (.*)$/m.exec(block)?.[1] ?? 'message'
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (data) yield { event, data: JSON.parse(data) }
    }
  }
}
