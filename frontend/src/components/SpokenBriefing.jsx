import { useCallback, useEffect, useRef, useState } from 'react'
import { speakBriefing } from '../lib/api.js'

const BAR_COUNT = 28

/**
 * Reads the day's briefing aloud, in an ElevenLabs voice.
 *
 * The audio and the timing of every sentence arrive together, so the sentence
 * being spoken is highlighted as it plays — which is what makes this usable
 * as a glance rather than something to read.
 *
 * The equaliser is driven from the audio itself through an analyser node, so
 * it moves with the voice rather than being an animation that happens to run
 * while sound plays.
 */
function SpokenBriefing({ text }) {
  const [status, setStatus] = useState('idle') // idle | loading | playing | paused
  const [error, setError] = useState('')
  const [sentences, setSentences] = useState([])
  const [activeIndex, setActiveIndex] = useState(-1)

  const [audioSrc, setAudioSrc] = useState('')
  const audioRef = useRef(null)
  // Set when a fetch finishes, so playback starts as soon as the new source
  // is loadable rather than before the element has it.
  const pendingPlayRef = useRef(false)
  const barsRef = useRef([])
  const frameRef = useRef(0)
  const analyserRef = useRef(null)
  const contextRef = useRef(null)
  // The audio element is connected to the analyser exactly once: connecting a
  // second time throws, and the node outlives any single play.
  const wiredRef = useRef(false)

  const paint = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return
    const levels = new Uint8Array(analyser.frequencyBinCount)
    const tick = () => {
      analyser.getByteFrequencyData(levels)
      const step = Math.floor(levels.length / BAR_COUNT) || 1
      barsRef.current.forEach((bar, index) => {
        if (!bar) return
        let sum = 0
        for (let i = 0; i < step; i += 1) sum += levels[index * step + i] ?? 0
        bar.style.transform = `scaleY(${Math.max(0.08, (sum / step / 255) * 2)})`
      })
      frameRef.current = requestAnimationFrame(tick)
    }
    tick()
  }, [])

  const stopPainting = useCallback(() => {
    cancelAnimationFrame(frameRef.current)
    barsRef.current.forEach((bar) => {
      if (bar) bar.style.transform = 'scaleY(0.08)'
    })
  }, [])

  useEffect(
    () => () => {
      cancelAnimationFrame(frameRef.current)
      contextRef.current?.close().catch(() => {})
    },
    [],
  )

  const wireAnalyser = (audio) => {
    if (wiredRef.current) return
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (!AudioContextClass) return
    const context = new AudioContextClass()
    const source = context.createMediaElementSource(audio)
    const analyser = context.createAnalyser()
    analyser.fftSize = 128
    analyser.smoothingTimeConstant = 0.75
    source.connect(analyser)
    // Still has to reach the speakers: an analyser alone is a dead end.
    analyser.connect(context.destination)
    contextRef.current = context
    analyserRef.current = analyser
    wiredRef.current = true
  }

  const play = async () => {
    setError('')

    if (status === 'paused' && audioRef.current) {
      await audioRef.current.play()
      setStatus('playing')
      paint()
      return
    }

    setStatus('loading')
    try {
      const result = await speakBriefing(text)
      setSentences(result.sentences)
      pendingPlayRef.current = true
      setAudioSrc(`data:audio/mpeg;base64,${result.audio_base64}`)
    } catch (exc) {
      setStatus('idle')
      setError(exc.message)
    }
  }

  const pause = () => {
    audioRef.current?.pause()
    setStatus('paused')
    stopPainting()
  }

  const stop = () => {
    const audio = audioRef.current
    if (audio) {
      audio.pause()
      audio.currentTime = 0
    }
    setStatus('idle')
    setActiveIndex(-1)
    stopPainting()
  }

  /** Once the new audio is loadable, start it and light up the equaliser. */
  const onCanPlay = async () => {
    if (!pendingPlayRef.current) return
    pendingPlayRef.current = false
    const audio = audioRef.current
    if (!audio) return
    wireAnalyser(audio)
    await contextRef.current?.resume?.()
    await audio.play()
    setStatus('playing')
    paint()
  }

  const onTimeUpdate = () => {
    const at = audioRef.current?.currentTime ?? 0
    // The sentence whose window the playhead is inside is the one being said.
    setActiveIndex(
      sentences.findIndex((s) => at >= s.start_seconds && at < s.end_seconds),
    )
  }

  /** Jump to a sentence — tapping one plays from there. */
  const seekTo = (sentence) => {
    const audio = audioRef.current
    if (!audio || !audio.src) return
    audio.currentTime = sentence.start_seconds
    if (status !== 'playing') {
      audio.play()
      setStatus('playing')
      paint()
    }
  }

  const live = status === 'playing'

  return (
    <div className="briefing-player">
      <audio
        ref={audioRef}
        src={audioSrc}
        onCanPlay={onCanPlay}
        onTimeUpdate={onTimeUpdate}
        onEnded={() => {
          setStatus('idle')
          setActiveIndex(-1)
          stopPainting()
        }}
        onError={() => {
          if (!audioSrc) return
          setStatus('idle')
          setError('The audio could not be played.')
          stopPainting()
        }}
        hidden
      />

      <div className={`equaliser eq-briefing${live ? ' is-live' : ''}`}>
        {Array.from({ length: BAR_COUNT }, (_, index) => (
          <span
            key={index}
            className="eq-bar"
            ref={(node) => {
              barsRef.current[index] = node
            }}
          />
        ))}
      </div>

      <div className="briefing-controls">
        {!live ? (
          <button
            type="button"
            className="btn btn-primary"
            disabled={status === 'loading' || !text}
            onClick={play}
          >
            {status === 'loading'
              ? 'Preparing…'
              : status === 'paused'
                ? 'Resume'
                : 'Listen'}
          </button>
        ) : (
          <button type="button" className="btn" onClick={pause}>
            Pause
          </button>
        )}
        {status !== 'idle' && status !== 'loading' && (
          <button type="button" className="btn" onClick={stop}>
            Stop
          </button>
        )}
        <button
          type="button"
          className="btn"
          onClick={() => navigator.clipboard?.writeText(text)}
        >
          Copy
        </button>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {/* Before it has been spoken there are no timings, so the text is shown
          plain; once there are, each sentence becomes its own place to jump to. */}
      <p className="summary-text briefing-text">
        {sentences.length === 0
          ? text
          : sentences.map((sentence, index) => (
              <span
                key={`${sentence.start}-${index}`}
                className={`briefing-sentence${
                  index === activeIndex ? ' is-active' : ''
                }`}
                role="button"
                tabIndex={0}
                onClick={() => seekTo(sentence)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    seekTo(sentence)
                  }
                }}
              >
                {sentence.text}{' '}
              </span>
            ))}
      </p>
    </div>
  )
}

export default SpokenBriefing
