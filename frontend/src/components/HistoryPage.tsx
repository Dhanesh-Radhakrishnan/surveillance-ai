// frontend/src/components/HistoryPage.tsx
/**
 * Week 5 — Task 6: History search page — paginated list, filter by date range.
 *
 * Single responsibility: fetch from GET /events (REST, cursor-paginated,
 * W5T6 date-range filter) and render a browsable list. Knows nothing about
 * the WebSocket live feed (useEventSocket.ts / LiveEventFeed.tsx) — this is
 * a separate read path against history, not live pushes.
 */

import { useCallback, useEffect, useState } from 'react'
import type { SecurityEventPayload } from '../hooks/useEventSocket'
import SnapshotViewer from './SnapshotViewer'

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const PAGE_SIZE = 25

type Preset = 'today' | '7d' | '30d' | 'custom'

interface EventsPage {
  items: SecurityEventPayload[]
  next_cursor: string | null
  limit: number
}

// WHY local-anchored T00:00:00 / T23:59:59 (not new Date(dateString) directly):
// a bare "YYYY-MM-DD" parses as UTC midnight, which drifts a day in some
// timezones, and a end-of-range with no time component excludes that whole
// day's later events.
function presetToRange(
  preset: Preset,
  customStart: string,
  customEnd: string,
): { start: string | null; end: string | null } {
  const now = new Date()

  if (preset === 'custom') {
    return {
      start: customStart ? new Date(`${customStart}T00:00:00`).toISOString() : null,
      end: customEnd ? new Date(`${customEnd}T23:59:59`).toISOString() : null,
    }
  }

  const start = new Date(now)
  if (preset === 'today') {
    start.setHours(0, 0, 0, 0)
  } else if (preset === '7d') {
    start.setDate(start.getDate() - 7)
  } else if (preset === '30d') {
    start.setDate(start.getDate() - 30)
  }
  return { start: start.toISOString(), end: now.toISOString() }
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

const PRESET_LABELS: Record<Preset, string> = {
  today: 'Today',
  '7d': 'Last 7d',
  '30d': 'Last 30d',
  custom: 'Custom',
}

export default function HistoryPage() {
  const [preset, setPreset] = useState<Preset>('7d')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [events, setEvents] = useState<SecurityEventPayload[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<SecurityEventPayload | null>(null)

  const fetchPage = useCallback(
    async (cursor: string | null, replace: boolean) => {
      // WHY guard here: avoids firing an unbounded "no start, no end" query
      // on every keystroke before the user has picked both custom dates.
      if (preset === 'custom' && (!customStart || !customEnd)) return

      setLoading(true)
      setError(null)

      const { start, end } = presetToRange(preset, customStart, customEnd)
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
      if (start) params.set('start_date', start)
      if (end) params.set('end_date', end)
      if (cursor) params.set('cursor', cursor)

      try {
        const res = await fetch(`${API_BASE_URL}/events?${params.toString()}`)
        if (!res.ok) {
          const body = await res.json().catch(() => null)
          throw new Error(body?.detail ?? `Request failed (${res.status})`)
        }
        const page: EventsPage = await res.json()
        setEvents((prev) => (replace ? page.items : [...prev, ...page.items]))
        setNextCursor(page.next_cursor)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load history')
      } finally {
        setLoading(false)
      }
    },
    [preset, customStart, customEnd],
  )

  // WHY replace + cursor=null on every range change: a new preset/custom
  // range is a new search, not a continuation of the previous one's pages.
  useEffect(() => {
    void fetchPage(null, true)
  }, [fetchPage])

  return (
    <div className="flex flex-col h-full bg-bg-secondary border border-border rounded-lg overflow-hidden">
      <header className="flex flex-col gap-3 px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold text-text-primary">History</h2>

        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPreset(p)}
              className={`text-xs font-mono px-3 py-1 rounded-full border transition-colors ${
                preset === p
                  ? 'bg-live/10 border-live text-live'
                  : 'border-border text-text-secondary hover:border-border-hover'
              }`}
            >
              {PRESET_LABELS[p]}
            </button>
          ))}

          {preset === 'custom' && (
            <div className="flex items-center gap-2 ml-1">
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="text-xs font-mono bg-bg-tertiary border border-border rounded px-2 py-1 text-text-primary"
              />
              <span className="text-text-muted text-xs">to</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="text-xs font-mono bg-bg-tertiary border border-border rounded px-2 py-1 text-text-primary"
              />
            </div>
          )}
        </div>
      </header>

      {error && (
        <p className="px-4 py-2 text-xs font-mono text-alert border-b border-border">{error}</p>
      )}

      <ul className="flex-1 overflow-y-auto divide-y divide-border">
        {events.length === 0 && !loading && (
          <li className="px-4 py-6 text-sm text-text-muted text-center">
            No events in this range.
          </li>
        )}

        {events.map((event) => (
          <li
            key={event.id}
            onClick={() => setSelectedEvent(event)}
            className="px-4 py-3 cursor-pointer transition-colors hover:bg-bg-tertiary"
          >
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm text-text-primary leading-snug">
                {event.ai_description ?? 'Description unavailable'}
              </p>
              <span className="text-xs font-mono shrink-0 text-text-secondary">
                {event.confidence !== null ? `${Math.round(event.confidence * 100)}%` : '—'}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs font-mono text-text-secondary">
              <span>{event.camera_id}</span>
              <span className="text-text-muted">•</span>
              <span>{formatTimestamp(event.timestamp)}</span>
            </div>
          </li>
        ))}
      </ul>

      <footer className="px-4 py-3 border-t border-border flex justify-center">
        {nextCursor && (
          <button
            type="button"
            disabled={loading}
            onClick={() => fetchPage(nextCursor, false)}
            className="text-xs font-mono text-text-secondary hover:text-text-primary disabled:opacity-50 transition-colors"
          >
            {loading ? 'Loading…' : 'Load more'}
          </button>
        )}
      </footer>

      {selectedEvent && (
        <SnapshotViewer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  )
}