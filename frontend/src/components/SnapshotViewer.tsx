// frontend/src/components/SnapshotViewer.tsx
/**
 * Week 5 — Task 5: Snapshot viewer — image + description card on event.
 *
 * Single responsibility: given ONE SecurityEventPayload, render its
 * snapshot + metadata as a modal card. No fetching, no WebSocket, no
 * history logic — that's W5T6. Knows nothing about where the event list
 * came from (live feed row click, or a future history list click).
 *
 * WHY resolve snapshot_filename against a static route (not a full path):
 * matches backend/schemas/security_event.py's rule — the ORM's absolute
 * server path is never sent to the client, only the filename. This
 * component reconstructs the fetchable URL client-side.
 *
 * DEPENDENCY NOT YET BUILT: backend/main.py must mount a StaticFiles route
 * at /snapshots serving config.SNAPSHOT_DIR, e.g.:
 *   from fastapi.staticfiles import StaticFiles
 *   app.mount("/snapshots", StaticFiles(directory="/tmp/surveillance_snapshots"), name="snapshots")
 * Until that exists, the <img> below will 404 — description/metadata will
 * still render correctly.
 */

import { useEffect, useState } from 'react'
import type { SecurityEventPayload } from '../hooks/useEventSocket'

// WHY a separate API base (not reusing VITE_WS_URL): ws:// and http://
// are different schemes hitting the same host:port — deriving one from
// the other via string replace is fragile once they diverge (W5T8 LAN IP
// change must update both, but they're still two distinct config values).
const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function formatFullTimestamp(iso: string): string {
  return new Date(iso).toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'medium',
  })
}

interface SnapshotViewerProps {
  event: SecurityEventPayload
  onClose: () => void
}

export default function SnapshotViewer({ event, onClose }: SnapshotViewerProps) {
  const [imageFailed, setImageFailed] = useState(false)
  const snapshotUrl = `${API_BASE_URL}/snapshots/${event.snapshot_filename}`

  // WHY reset on event change: viewer instance is reused across clicks
  // (parent swaps the `event` prop) rather than remounted — without this,
  // a failed image on event A would stay "failed" when viewing event B.
  useEffect(() => {
    setImageFailed(false)
  }, [event.id])

  // WHY Escape-to-close: modal has no other keyboard dismissal, and a
  // dashboard operator's hands are usually on the keyboard, not a mouse.
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-bg-secondary border border-border rounded-lg overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="aspect-video bg-bg-tertiary flex items-center justify-center">
          {imageFailed ? (
            <span className="text-xs font-mono text-text-muted px-4 text-center">
              Snapshot unavailable — {event.snapshot_filename}
            </span>
          ) : (
            <img
              src={snapshotUrl}
              alt={event.ai_description ?? `Detection at ${event.camera_id}`}
              className="w-full h-full object-contain"
              onError={() => setImageFailed(true)}
            />
          )}
        </div>

        <div className="p-4 flex flex-col gap-3">
          <p className="text-sm text-text-primary leading-relaxed">
            {event.ai_description ?? 'No AI description available for this event.'}
          </p>

          <dl className="grid grid-cols-2 gap-y-1 text-xs font-mono text-text-secondary">
            <dt className="text-text-muted">Camera</dt>
            <dd>{event.camera_id}</dd>

            <dt className="text-text-muted">Time</dt>
            <dd>{formatFullTimestamp(event.timestamp)}</dd>

            <dt className="text-text-muted">Confidence</dt>
            <dd>{event.confidence !== null ? `${Math.round(event.confidence * 100)}%` : '—'}</dd>

            <dt className="text-text-muted">Event ID</dt>
            <dd>#{event.id}</dd>
          </dl>

          <button
            type="button"
            onClick={onClose}
            className="mt-1 self-end text-xs font-mono text-text-secondary hover:text-text-primary transition-colors"
          >
            Close (Esc)
          </button>
        </div>
      </div>
    </div>
  )
}