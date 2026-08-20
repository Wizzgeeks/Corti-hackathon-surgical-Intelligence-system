/** Global "an API call is in flight" state, driving the full-screen loader.
 *
 *  A counter rather than a boolean: overlapping requests each hold the
 *  loader open, and it only clears when the last one settles.
 */

let pending = 0
const listeners = new Set()

const emit = () => listeners.forEach((listener) => listener())

export const subscribe = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const isLoading = () => pending > 0

/** Run `task` with the loader shown, whatever the outcome. */
export async function withLoading(task) {
  pending += 1
  emit()
  try {
    return await task()
  } finally {
    pending -= 1
    emit()
  }
}
