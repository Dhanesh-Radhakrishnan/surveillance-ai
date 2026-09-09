/**
 * frontend/src/hooks/useEventSocket.ts
 * Week 5 — Task 3: WebSocket hook — connects to backend, reconnects on drop.
 *
 * Single responsibility: own the WebSocket lifecycle (connect, parse,
 * reconnect) and expose a plain data + status API. Knows nothing about
 * how the feed is rendered — W5T4's feed component just consumes this.
 *
 * WHY exponential backoff (not fixed interval): a dead backend (e.g.
 * uvicorn restarting on --reload, or the RTX laptop rebooting) shouldn't
 * be hammered with a reconnect attempt every second — backoff caps the
 * retry rate while still recovering quickly on transient drops.
 */

import { useEffect, useRef, useState, useCallback } from 'react'

// Mirrors backend/schemas/security_event.py's SecurityEventResponse shape —
// the WS broadcast payload (ai-worker/ollama_worker.py's _broadcast_event)
// intentionally matches this so the frontend can share one type for both
// the live feed and the REST /events history (W5T6).
export interface SecurityEventPayload {
  id: number
  timestamp: string // ISO-8601 — backend sends via .isoformat()
  camera_id: string
  snapshot_filename: string
  ai_description: string | null
  confidence: number | null
}

export type SocketStatus = 'connecting' | 'open' | 'closed' | 'error'

const DEFAULT_WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws/events'

// WHY cap at 50: this is a live feed, not history (that's GET /events,
// W4T2) — an unbounded array would leak memory on a 24/7-open dashboard tab.
const MAX_FEED_LENGTH = 50

const INITIAL_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30_000

interface UseEventSocketResult {
  events: SecurityEventPayload[]
  latestEvent: SecurityEventPayload | null
  status: SocketStatus
  clearEvents: () => void
}

export function useEventSocket(url: string = DEFAULT_WS_URL): UseEventSocketResult {
  const [events, setEvents] = useState<SecurityEventPayload[]>([])
  const [status, setStatus] = useState<SocketStatus>('connecting')

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const backoffRef = useRef<number>(INITIAL_BACKOFF_MS)
  // WHY a ref (not state) for "should we reconnect": unmount must be able
  // to suppress a reconnect scheduled just before cleanup runs — state
  // updates are async and would race the effect teardown.
  const manualCloseRef = useRef<boolean>(false)

  const connect = useCallback(() => {
    setStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      // WHY reset backoff here: a successful connection means the outage
      // is over — don't keep escalating the delay on the *next* drop.
      backoffRef.current = INITIAL_BACKOFF_MS
      setStatus('open')
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const payload: SecurityEventPayload = JSON.parse(event.data)
        setEvents((prev) => [payload, ...prev].slice(0, MAX_FEED_LENGTH))
      } catch {
        // Malformed payload dropped silently — mirrors ollama_worker.py's
        // "never crash the loop over one bad message" discipline.
        console.error('useEventSocket: failed to parse message', event.data)
      }
    }

    ws.onerror = () => {
      setStatus('error')
    }

    ws.onclose = () => {
      setStatus('closed')
      wsRef.current = null

      if (manualCloseRef.current) return // unmounting — do not reconnect

      // WHY schedule from onclose (not a separate effect): guarantees
      // exactly one reconnect attempt per actual drop, regardless of
      // whether the drop was clean, an error, or the server going away.
      reconnectTimeoutRef.current = setTimeout(() => {
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS)
        connect()
      }, backoffRef.current)
    }
  }, [url])

  useEffect(() => {
    manualCloseRef.current = false
    connect()

    return () => {
      manualCloseRef.current = true
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clearEvents = useCallback(() => setEvents([]), [])

  return {
    events,
    latestEvent: events[0] ?? null,
    status,
    clearEvents,
  }
}