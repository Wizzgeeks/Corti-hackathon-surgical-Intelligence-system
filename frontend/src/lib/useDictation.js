import { useCallback, useEffect, useRef, useState } from 'react'
import { getConsultationAuth, getDictationAuth } from './api.js'

// Corti's recommended streaming format: 16 kHz mono, 16-bit little-endian.
const SAMPLE_RATE = 16000
// 4096 frames at 16 kHz is ~256 ms, inside Corti's 250-500 ms guidance.
const FRAME_SIZE = 4096

/** Float32 [-1,1] from the AudioContext -> the PCM16 Corti expects. */
const toPcm16 = (input) => {
  const output = new Int16Array(input.length)
  for (let i = 0; i < input.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, input[i]))
    output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
  }
  return output.buffer
}

/** Config for the /transcribe socket: one voice, no speaker separation. */
const dictationConfig = (language) => ({
  type: 'config',
  configuration: {
    primaryLanguage: language,
    audioFormat: `audio/pcm; rate=${SAMPLE_RATE}; channels=1; bits=16`,
    // Interim results are what make the field fill as the clinician speaks.
    interimResults: true,
    automaticPunctuation: true,
    spokenPunctuation: true,
  },
})

/** Config for an interaction's /streams socket.
 *
 *  Shaped differently on purpose — this is not the dictation socket with a
 *  flag turned on. Only this one takes `participants`, and only with them
 *  does Corti diarize, which is what makes a consultation two voices instead
 *  of one. Both participants sit on channel 0: one microphone in the room.
 */
const conversationConfig = (language) => ({
  type: 'config',
  configuration: {
    transcription: {
      primaryLanguage: language,
      isDiarization: true,
      isMultichannel: false,
      participants: [
        { channel: 0, role: 'doctor' },
        { channel: 0, role: 'patient' },
      ],
    },
    mode: { type: 'transcription' },
    audioFormat: `audio/pcm; rate=${SAMPLE_RATE}; channels=1; bits=16`,
  },
})

/**
 * Live dictation straight to Corti's transcribe socket.
 *
 * Nothing is recorded: audio frames go to Corti and are dropped. The caller
 * receives text through `onText(finals, interim)` and decides where to put
 * it — for a plain field, straight into the textarea.
 *
 * Pass `conversation` for a consultation: that opens a Corti interaction
 * stream instead of the dictation socket, which is the only one that
 * separates the speakers. Each transcript is then also handed to
 * `onSegment({ id, text, isFinal, speaker })` carrying Corti's `speakerId`,
 * which is what a two-person consultation is rendered from.
 *
 * `status` is one of: idle | connecting | live | paused | error.
 */
export function useDictation({
  language = 'en',
  conversation = false,
  // Only used for a conversation: tags Corti's interaction with the case.
  caseId,
  onText,
  onLevels,
  onSegment,
} = {}) {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [seconds, setSeconds] = useState(0)

  const socketRef = useRef(null)
  const streamRef = useRef(null)
  const contextRef = useRef(null)
  const processorRef = useRef(null)
  const frameRef = useRef(0)
  const timerRef = useRef(0)
  const pausedRef = useRef(false)
  const finalsRef = useRef('')
  // Held in refs so the audio callback always sees the latest without
  // re-subscribing the processor on every render.
  const onTextRef = useRef(onText)
  const onLevelsRef = useRef(onLevels)
  const onSegmentRef = useRef(onSegment)

  // Kept in sync from an effect: writing a ref during render is not allowed,
  // and the audio callback must always see the current handlers.
  useEffect(() => {
    onTextRef.current = onText
    onLevelsRef.current = onLevels
    onSegmentRef.current = onSegment
  }, [onText, onLevels, onSegment])

  const teardown = useCallback(() => {
    cancelAnimationFrame(frameRef.current)
    clearInterval(timerRef.current)
    processorRef.current?.disconnect()
    processorRef.current = null
    if (
      socketRef.current &&
      socketRef.current.readyState <= WebSocket.OPEN
    ) {
      socketRef.current.close()
    }
    socketRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    contextRef.current?.close().catch(() => {})
    contextRef.current = null
  }, [])

  // Never leave the microphone open behind a closed page.
  useEffect(() => teardown, [teardown])

  const start = useCallback(async () => {
    setError('')
    setStatus('connecting')
    finalsRef.current = ''
    pausedRef.current = false

    try {
      // The token is fetched per session: Corti's expire in minutes, so
      // there is nothing worth caching in the browser.
      // Two different sockets, and each only understands its own config.
      const auth = conversation
        ? await getConsultationAuth({ caseId })
        : await getDictationAuth()
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const socket = new WebSocket(
        conversation ? auth.stream_url : auth.transcribe_url,
      )
      socket.binaryType = 'arraybuffer'
      socketRef.current = socket

      socket.onopen = () =>
        socket.send(
          JSON.stringify(
            conversation
              ? conversationConfig(language)
              : dictationConfig(language),
          ),
        )

      socket.onmessage = (event) => {
        let message
        try {
          message = JSON.parse(event.data)
        } catch {
          return
        }

        if (message.type === 'CONFIG_ACCEPTED') {
          setStatus('live')
          setSeconds(0)
          timerRef.current = setInterval(
            () => setSeconds((prev) => prev + 1),
            1000,
          )
          return
        }
        // The two sockets word this differently; treat them the same.
        if (
          message.type === 'CONFIG_REJECTED' ||
          message.type === 'CONFIG_DENIED' ||
          message.type === 'CONFIG_MISSING' ||
          message.type === 'CONFIG_NOT_PROVIDED'
        ) {
          setStatus('error')
          setError('Corti rejected the transcription configuration.')
          teardown()
          return
        }
        if (message.type !== 'transcript') return

        // The interaction stream sends an array of transcripts; dictation
        // sends a single object. Normalising here keeps both callers on one
        // shape — and reading a `.text` off the array is exactly the bug
        // that made a whole consultation look like one speaker.
        const payload = message.data ?? {}
        const segments = Array.isArray(payload) ? payload : [payload]

        for (const data of segments) {
          // Field names differ between the two sockets, so read both
          // spellings rather than depending on which one sent this.
          const text = data.text ?? data.transcript ?? ''
          const isFinal = data.isFinal ?? data.final ?? false
          if (!text) continue

          onSegmentRef.current?.({
            id: data.id ?? `${data.time?.start ?? ''}-${data.speakerId ?? 0}`,
            text,
            isFinal,
            // Dictation has no speakers, so everything lands on 0 and the
            // caller renders it as a single voice.
            speaker: data.speakerId ?? data.participant?.channel ?? 0,
          })

          if (isFinal) {
            finalsRef.current = `${finalsRef.current} ${text}`.trim()
            onTextRef.current?.(finalsRef.current, '')
          } else {
            onTextRef.current?.(finalsRef.current, text)
          }
        }
      }

      socket.onerror = () => {
        setStatus('error')
        setError('Lost the connection to the dictation service.')
      }

      // One context feeds both the level meter and the PCM tap; asking for
      // 16 kHz lets the browser do the resampling.
      const context = new AudioContext({ sampleRate: SAMPLE_RATE })
      contextRef.current = context
      const source = context.createMediaStreamSource(stream)

      const analyser = context.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.75
      source.connect(analyser)

      const levels = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        analyser.getByteFrequencyData(levels)
        onLevelsRef.current?.(levels, pausedRef.current)
        frameRef.current = requestAnimationFrame(tick)
      }
      tick()

      // ScriptProcessor is deprecated but needs no separate worklet module;
      // swap for an AudioWorklet if this ever runs hot.
      const processor = context.createScriptProcessor(FRAME_SIZE, 1, 1)
      processorRef.current = processor
      processor.onaudioprocess = (event) => {
        if (pausedRef.current) return
        if (socketRef.current?.readyState !== WebSocket.OPEN) return
        socketRef.current.send(toPcm16(event.inputBuffer.getChannelData(0)))
      }
      source.connect(processor)
      // Chrome only pulls audio through a processor that reaches the
      // destination; zero gain keeps it silent.
      const mute = context.createGain()
      mute.gain.value = 0
      processor.connect(mute).connect(context.destination)
    } catch (exc) {
      teardown()
      setStatus('error')
      setError(
        exc?.name === 'NotAllowedError'
          ? 'Microphone access was blocked. Allow it and try again.'
          : (exc?.message ?? 'Could not start dictation.'),
      )
    }
  }, [language, conversation, caseId, teardown])

  const pause = useCallback(() => {
    pausedRef.current = true
    clearInterval(timerRef.current)
    setStatus('paused')
  }, [])

  const resume = useCallback(() => {
    pausedRef.current = false
    timerRef.current = setInterval(() => setSeconds((prev) => prev + 1), 1000)
    setStatus('live')
  }, [])

  const stop = useCallback(() => {
    // Flush first, or Corti may never emit the closing segment.
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'flush' }))
      socketRef.current.send(JSON.stringify({ type: 'end' }))
    }
    clearInterval(timerRef.current)
    processorRef.current?.disconnect()
    processorRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    setStatus('idle')
    // Give Corti a moment to send the final transcript before the socket goes.
    setTimeout(teardown, 2500)
  }, [teardown])

  return { status, error, seconds, start, pause, resume, stop }
}
