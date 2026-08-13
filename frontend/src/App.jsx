import React, { useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import InputPanel from './components/InputPanel.jsx'
import TranscriptPreview from './components/TranscriptPreview.jsx'
import VoiceMapping from './components/VoiceMapping.jsx'
import ResultPanel from './components/ResultPanel.jsx'
import { generateAudio } from './api.js'

export default function App() {
  const [roles, setRoles] = useState([])
  const [turns, setTurns] = useState([])
  const [roleVoiceMap, setRoleVoiceMap] = useState({})
  const [language, setLanguage] = useState('auto')
  const [gapMs, setGapMs] = useState(250)
  const [result, setResult] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')

  function handleParsed(data) {
    setRoles(data.roles)
    setTurns(data.turns)
    setLanguage(data.language || 'auto')
    setRoleVoiceMap({})
    setResult(null)
  }

  function handleVoiceChange(role, voiceId) {
    setRoleVoiceMap((prev) => ({ ...prev, [role]: voiceId }))
  }

  function handleTurnsChange(nextTurns) {
    const nextRoles = [...new Set(nextTurns.map((turn) => turn.speaker))]
    setTurns(nextTurns)
    setRoles(nextRoles)
    setRoleVoiceMap((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([role]) => nextRoles.includes(role))),
    )
    setResult(null)
  }

  async function handleGenerateAudio() {
    setGenerating(true)
    setError('')
    try {
      const data = await generateAudio(turns, roleVoiceMap, gapMs, language)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const allVoicesAssigned = roles.length > 0 && roles.every((role) => roleVoiceMap[role])

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-column">
        <header className="topbar">
          <span>Voice Dialogue Generator</span>
        </header>
        <div className="content-row">
          <main className="main-content">
            <InputPanel onParsed={handleParsed} />
            {turns.length > 0 && (
              <TranscriptPreview turns={turns} onChange={handleTurnsChange} />
            )}
            {turns.length > 0 && (
              <div className="generation-controls">
                <div className="gap-control">
                  <div className="gap-control-label">
                    <label htmlFor="gap-ms">Pause between lines</label>
                    <strong>{gapMs} ms</strong>
                  </div>
                  <input
                    id="gap-ms"
                    type="range"
                    min="0"
                    max="1500"
                    step="50"
                    value={gapMs}
                    onChange={(event) => {
                      setGapMs(Number(event.target.value))
                      setResult(null)
                    }}
                  />
                  <div className="gap-scale">
                    <span>No pause</span>
                    <span>1.5 sec</span>
                  </div>
                </div>
                <button
                  className="primary-btn"
                  disabled={!allVoicesAssigned || generating}
                  onClick={handleGenerateAudio}
                >
                  {generating ? 'Generating...' : 'Generate Dialogue Audio'}
                </button>
              </div>
            )}
            {error && <div className="error">{error}</div>}
            <ResultPanel result={result} />
          </main>
          {roles.length > 0 && (
            <aside className="right-panel">
              <VoiceMapping
                roles={roles}
                language={language}
                roleVoiceMap={roleVoiceMap}
                onChange={handleVoiceChange}
              />
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
