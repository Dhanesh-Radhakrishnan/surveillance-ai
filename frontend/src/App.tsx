// frontend/src/App.tsx
/**
 * Week 5 — Task 7: Responsive layout — works on both laptop screens.
 * Also resolves the W5T6 pending decision: tab switcher (Live / History).
 *
 * Single responsibility: top-level shell — header + tab nav + the two
 * already-built panels (LiveEventFeed W5T4/5, HistoryPage W5T6). No
 * fetching, no WebSocket logic lives here.
 *
 * WHY both panels stay mounted (CSS `hidden`, not conditional unmount):
 * LiveEventFeed owns a useEventSocket connection with its own reconnect
 * backoff and a capped 50-event buffer. Unmounting on tab switch would
 * tear down the socket and drop that buffer every time the user checks
 * History — CSS hidden keeps the connection alive underneath instead.
 *
 * WHY no split-pane / breakpoint logic: both target machines (RTX laptop,
 * i5 laptop) are laptop-class screens in the same rough size band
 * (~1366x768 to ~1920x1080) — a single-column layout that fills the
 * viewport height scales across that whole range without needing
 * different layouts per breakpoint. Padding alone (`sm:p-4`) is enough
 * breathing room on the larger screen.
 */

import { useState } from 'react'
import LiveEventFeed from './components/LiveEventFeed'
import HistoryPage from './components/HistoryPage'

type Tab = 'live' | 'history'

const TABS: { id: Tab; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'history', label: 'History' },
]

function App() {
  const [tab, setTab] = useState<Tab>('live')

  return (
    <div className="flex flex-col h-screen bg-bg-primary text-text-primary">
      <header className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <h1 className="text-sm font-semibold tracking-wide">
          Surveillance <span className="text-live">AI</span>
        </h1>

        <nav className="flex gap-1 bg-bg-secondary border border-border rounded-full p-1">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              aria-pressed={tab === id}
              className={`text-xs font-mono px-3 py-1.5 rounded-full transition-colors ${
                tab === id
                  ? 'bg-live/10 text-live'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {/* min-h-0 is required here: without it, a flex child with its own
          overflow-y-auto (both panels) refuses to shrink below its content
          size and the header gets pushed off-screen instead of the panel
          scrolling internally. */}
      <main className="flex-1 min-h-0 p-3 sm:p-4">
        <div className={tab === 'live' ? 'h-full' : 'hidden'}>
          <LiveEventFeed />
        </div>
        <div className={tab === 'history' ? 'h-full' : 'hidden'}>
          <HistoryPage />
        </div>
      </main>
    </div>
  )
}

export default App