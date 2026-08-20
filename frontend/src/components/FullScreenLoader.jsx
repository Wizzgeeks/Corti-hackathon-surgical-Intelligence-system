import { useSyncExternalStore } from 'react'
import { isLoading, subscribe } from '../lib/loading.js'

/** Blocking overlay shown while any API call is in flight. */
function FullScreenLoader() {
  const busy = useSyncExternalStore(subscribe, isLoading, isLoading)

  if (!busy) return null

  return (
    <div className="loader-overlay" role="alert" aria-busy="true">
      <div className="loader-card">
        <span className="spinner" aria-hidden="true" />
        <p className="loader-text">Working…</p>
      </div>
    </div>
  )
}

export default FullScreenLoader
