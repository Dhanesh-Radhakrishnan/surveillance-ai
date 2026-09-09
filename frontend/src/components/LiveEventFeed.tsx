// frontend/src/components/LiveEventFeed.tsx
/**
 * Week 5 — Task 4: Live event feed — flashes on new event, shows AI
 * description + timestamp.
 *
 * Single responsibility: render what useEventSocket (W5T3) gives it.
 * Knows nothing about WebSocket lifecycle, reconnects, or backoff —
 * that's already owned by the hook.
 */

import { useEffect, useRef, useState } from 'react'
import { useEventSocket, type SocketStatus } from '../hooks/useEventSocket'

const FLASH_DURATION_MS = 1500

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function confidenceTone(confidence: number | null): string {
  if (confidence === null) return 'text-text-muted'
  if (confidence >= 0.7) return 'text-online'
  if (confidence >= 0.4) return 'text-warning'
  return 'text-alert'
}

function StatusPill({ status }: { status: SocketStatus }) {
  const map: Record<SocketStatus, { label: string; dot: string }> = {
    open: { label: 'Live', dot: 'bg-live' },
    connecting: { label: 'Connecting…', dot: 'bg-warning' },
    closed: { label: 'Disconnected', dot: 'bg-text-muted' },
    error: { label: 'Connection error', dot: 'bg-alert' },
  }
  const { label, dot } = map[status]
  return (
    <span className="flex items-center gap-2 text-xs font-mono text-text-secondary">
      <span className={`h-2 w-2 rounded-full ${dot} ${status === 'open' ? 'animate-pulse' : ''}`} />
      {label}
    </span>
  )
}

export default function LiveEventFeed() {
  const { events, status } = useEventSocket()
  const [flashingId, setFlashingId] = useState<number | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // WHY a ref set (not events.length): StrictMode double-invokes effects
  // in dev — a length-based check would re-flash the same id twice.
  const seenIds = useRef<Set<number>>(new Set())

  useEffect(() => {
    const latest = events[0]
    if (!latest || seenIds.current.has(latest.id)) return
    seenIds.current.add(latest.id)

    setFlashingId(latest.id)
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setFlashingId(null), FLASH_DURATION_MS)

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [events])

  return (
    <div className="flex flex-col h-full bg-bg-secondary border border-border rounded-lg overflow-hidden">
      <header className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold text-text-primary">Live Event Feed</h2>
        <StatusPill status={status} />
      </header>

      <ul className="flex-1 overflow-y-auto divide-y divide-border">
        {events.length === 0 && (
          <li className="px-4 py-6 text-sm text-text-muted text-center">
            Waiting for detections…
          </li>
        )}

        {events.map((event) => (
          <li
            key={event.id}
            className={`px-4 py-3 transition-colors duration-500 ${
              flashingId === event.id ? 'bg-live/10' : 'bg-transparent'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm text-text-primary leading-snug">
                {event.ai_description ?? 'Description unavailable'}
              </p>
              <span className={`text-xs font-mono shrink-0 ${confidenceTone(event.confidence)}`}>
                {event.confidence !== null ? `${Math.round(event.confidence * 100)}%` : '—'}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs font-mono text-text-secondary">
              <span>{event.camera_id}</span>
              <span className="text-text-muted">•</span>
              <span>{formatTime(event.timestamp)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}