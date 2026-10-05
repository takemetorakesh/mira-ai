export type ShownOption = {
  room_type_id: string
  room_name: string
  property_name: string
  rooms: number
  avg_room_cost_per_night: number
}

export type BookingState = {
  city: string | null
  check_in: string | null
  check_out: string | null
  stay: string | null
  nights: number | null
  adults: number | null
  children: number
  guests: number | null
  rooms: number
  budget_per_night: number | null
  preferences: string[]
  special_requests: string[]
  selected_room_type_id: string | null
  addon_ids: string[]
  guest_name: string | null
  shown_options: ShownOption[]
  last_quote: { room_type_id: string; total: number; addon_ids: string[] } | null
  hold: { id: string; room_type_id: string; total: number; expires_at: string } | null
}

export type ToolCallEntry = {
  id: string
  name: string
  args: unknown
  result?: Record<string, any>
  status?: 'ok' | 'error'
  ms?: number
}

export type TurnError = { kind: string; message?: string; violations?: { code: string; message: string }[]; rejected_reply?: string }

export type StateChange = { field: string; from: unknown; to: unknown }

export type Turn = {
  seq: number
  user_message: string
  reply: string
  next_action: string
  tool_calls: ToolCallEntry[]
  state_diff: StateChange[]
  errors: TurnError[]
}

/** A turn while its SSE stream is still arriving. */
export type LiveTurn = {
  user_message: string
  tool_calls: ToolCallEntry[]
  errors: TurnError[]
  changes: StateChange[]
}
