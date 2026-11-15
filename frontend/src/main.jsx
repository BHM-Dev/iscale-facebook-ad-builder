import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { installPendingTimestamps, sweepPendingHandoffs } from './lib/pendingHandoffs'

// Before anything reads a page-to-page handoff: expire stale ones, and stamp new ones as they're written.
sweepPendingHandoffs()
installPendingTimestamps()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
