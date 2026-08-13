import React, { useEffect, useMemo, useState } from 'react'
import { fetchVoices } from '../api.js'

const VOICE_LANGUAGE_BY_SCRIPT = {
  en: 'English',
  'zh-CN': 'Chinese',
  yue: 'Yue',
}

const LANGUAGE_LABELS = {
  en: 'English',
  'zh-CN': '普通话',
  yue: '粤语',
  auto: 'Auto',
}

export default function VoiceMapping({ roles, language, roleVoiceMap, onChange }) {
  const [voices, setVoices] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    let retryTimer

    async function loadVoices() {
      setLoading(true)
      try {
        const nextVoices = await fetchVoices()
        if (cancelled) return
        if (!Array.isArray(nextVoices) || nextVoices.length === 0) {
          throw new Error('No voices were returned by the backend')
        }
        setVoices(nextVoices)
        setLoadError('')
      } catch (error) {
        if (cancelled) return
        setVoices([])
        setLoadError(error.message || 'Unable to load voices')
        retryTimer = window.setTimeout(() => {
          setReloadToken((current) => current + 1)
        }, 3000)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadVoices()
    return () => {
      cancelled = true
      window.clearTimeout(retryTimer)
    }
  }, [reloadToken])

  const availableVoices = useMemo(() => {
    const voiceLanguage = VOICE_LANGUAGE_BY_SCRIPT[language]
    if (!voiceLanguage) return voices
    const matchingVoices = voices.filter((voice) => voice.language === voiceLanguage)
    return matchingVoices.length > 0 ? matchingVoices : voices
  }, [language, voices])

  return (
    <div className="side-panel voice-mapping-panel">
      <h3>Role-to-Voice Mapping</h3>
      <p className="hint">Language: {LANGUAGE_LABELS[language] || language}</p>

      {loading && voices.length === 0 && (
        <p className="voice-load-status">Loading voices...</p>
      )}
      {loadError && (
        <div className="voice-load-error">
          <span>{loadError}</span>
          <button type="button" className="text-btn" onClick={() => setReloadToken((current) => current + 1)}>
            Reload voices
          </button>
        </div>
      )}

      {availableVoices.length > 0 && roles.map((role) => (
        <div className="voice-row voice-selection-row" key={role}>
          <span className="role-name">{role}</span>
          <div className="voice-option-list" role="group" aria-label={`Choose a voice for ${role}`}>
            {availableVoices.map((voice) => {
              const selected = roleVoiceMap[role] === voice.voice_id
              return (
                <button
                  type="button"
                  className={selected ? 'voice-option selected' : 'voice-option'}
                  aria-pressed={selected}
                  key={voice.voice_id}
                  onClick={() => onChange(role, voice.voice_id)}
                >
                  <span>{voice.name}</span>
                  <small>{selected ? 'Selected' : 'Select'}</small>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
