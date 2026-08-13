import React, { useEffect, useMemo, useState } from 'react'
import {
  createBatchJob,
  fetchBatchJob,
  generateScript,
  parseChatlog,
  retryBatchJob,
} from '../api.js'
import BatchJobPanel from './BatchJobPanel.jsx'
import VoiceMapping from './VoiceMapping.jsx'

const TERMINAL_BATCH_STATUSES = new Set(['completed', 'partial_failed', 'failed'])

function parseRoles(value) {
  return value.split(',').map((role) => role.trim()).filter(Boolean)
}

export default function InputPanel({ onParsed }) {
  const [mode, setMode] = useState('chatlog')
  const [scenario, setScenario] = useState('')
  const [batchScenario, setBatchScenario] = useState('')
  const [rolesInput, setRolesInput] = useState('Agent, Customer')
  const [maxTurns, setMaxTurns] = useState(20)
  const [batchCount, setBatchCount] = useState(5)
  const [batchMaxTurns, setBatchMaxTurns] = useState(12)
  const [batchGapMs, setBatchGapMs] = useState(250)
  const [batchRoleVoiceMap, setBatchRoleVoiceMap] = useState({})
  const [language, setLanguage] = useState('yue')
  const [batchJob, setBatchJob] = useState(null)
  const [loading, setLoading] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [error, setError] = useState('')

  const roles = useMemo(() => parseRoles(rolesInput), [rolesInput])
  const allBatchVoicesAssigned = roles.length > 0
    && roles.every((role) => batchRoleVoiceMap[role])

  useEffect(() => {
    if (!batchJob?.job_id || TERMINAL_BATCH_STATUSES.has(batchJob.status)) return undefined

    let cancelled = false
    let timer

    async function poll() {
      try {
        const nextJob = await fetchBatchJob(batchJob.job_id)
        if (cancelled) return
        setBatchJob(nextJob)
        if (!TERMINAL_BATCH_STATUSES.has(nextJob.status)) {
          timer = window.setTimeout(poll, 1200)
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    timer = window.setTimeout(poll, 800)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [batchJob?.job_id, batchJob?.status])

  function handleLanguageChange(nextLanguage) {
    setLanguage(nextLanguage)
    setBatchRoleVoiceMap({})
    setBatchJob(null)
    setError('')
  }

  function handleRolesChange(value) {
    const nextRoles = parseRoles(value)
    setRolesInput(value)
    setBatchRoleVoiceMap((current) => Object.fromEntries(
      Object.entries(current).filter(([role]) => nextRoles.includes(role)),
    ))
    setBatchJob(null)
  }

  async function handleFile(event) {
    const file = event.target.files[0]
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const data = await parseChatlog(file)
      onParsed(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerateScript() {
    if (!scenario.trim() || roles.length === 0) {
      setError('Please fill in the scenario description and roles')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await generateScript(scenario.trim(), roles, maxTurns, language)
      onParsed(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerateBatch() {
    if (!batchScenario.trim() || roles.length === 0) {
      setError('Please fill in one base scenario and at least one role')
      return
    }
    if (!Number.isInteger(batchCount) || batchCount < 1 || batchCount > 10) {
      setError('Number of audio files must be between 1 and 10')
      return
    }
    if (!allBatchVoicesAssigned) {
      setError('Choose one fixed voice for every role before starting the batch')
      return
    }

    setLoading(true)
    setError('')
    setBatchJob(null)
    try {
      const job = await createBatchJob({
        scenario: batchScenario.trim(),
        count: batchCount,
        language,
        roles,
        max_turns: batchMaxTurns,
        gap_ms: batchGapMs,
        role_voice_map: batchRoleVoiceMap,
      })
      setBatchJob(job)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleRetryBatch() {
    if (!batchJob?.job_id) return
    setRetrying(true)
    setError('')
    try {
      const job = await retryBatchJob(batchJob.job_id)
      setBatchJob(job)
    } catch (err) {
      setError(err.message)
    } finally {
      setRetrying(false)
    }
  }

  function useBatchScript(item) {
    if (!item.script?.turns) return
    onParsed({
      roles: batchJob.roles,
      turns: item.script.turns,
      language: batchJob.language,
    })
  }

  return (
    <div className="panel">
      <div className="tabs">
        <button className={mode === 'chatlog' ? 'tab active' : 'tab'} onClick={() => setMode('chatlog')}>
          Upload Chatlog
        </button>
        <button className={mode === 'scenario' ? 'tab active' : 'tab'} onClick={() => setMode('scenario')}>
          AI Generator
        </button>
        <button className={mode === 'batch' ? 'tab active' : 'tab'} onClick={() => setMode('batch')}>
          AI Batch
        </button>
      </div>

      {mode === 'chatlog' && (
        <div className="tab-content">
          <p className="hint">Supports CSV (Speaker/Text/Chat Time columns) or plain text (one "Role: line" per turn).</p>
          <input type="file" accept=".csv,.txt" onChange={handleFile} disabled={loading} />
        </div>
      )}

      {(mode === 'scenario' || mode === 'batch') && (
        <div className="tab-content">
          <label htmlFor="output-language">Output language</label>
          <select
            id="output-language"
            value={language}
            onChange={(event) => handleLanguageChange(event.target.value)}
          >
            <option value="en">English</option>
            <option value="zh-CN">普通话 (Mandarin)</option>
            <option value="yue">粤语 (Cantonese)</option>
          </select>
          <label>Roles, comma-separated</label>
          <input value={rolesInput} onChange={(event) => handleRolesChange(event.target.value)} />

          {mode === 'scenario' && (
            <>
              <label>Maximum turns</label>
              <input
                type="number"
                min="1"
                max="100"
                value={maxTurns}
                onChange={(event) => setMaxTurns(Number(event.target.value))}
              />
              <label>Scenario description</label>
              <textarea
                rows={4}
                value={scenario}
                onChange={(event) => setScenario(event.target.value)}
                placeholder="e.g. A customer calls about an unrecognized account transaction."
              />
              <button className="primary-btn" onClick={handleGenerateScript} disabled={loading}>
                {loading ? 'Generating with DeepSeek...' : 'Generate Dialogue Script'}
              </button>
            </>
          )}

          {mode === 'batch' && (
            <>
              <p className="hint">Enter one base scenario. DeepSeek creates distinct variations, then MiniMax automatically generates every MP3 with the same role voices.</p>
              <label>Base scenario</label>
              <textarea
                rows={4}
                value={batchScenario}
                onChange={(event) => {
                  setBatchScenario(event.target.value)
                  setBatchJob(null)
                }}
                placeholder="e.g. A customer asks how to freeze a bank card."
              />
              <div className="batch-settings-grid">
                <div>
                  <label htmlFor="batch-count">Number of audio files</label>
                  <input
                    id="batch-count"
                    type="number"
                    min="1"
                    max="10"
                    value={batchCount}
                    onChange={(event) => setBatchCount(Number(event.target.value))}
                  />
                </div>
                <div>
                  <label htmlFor="batch-max-turns">Maximum turns per script</label>
                  <input
                    id="batch-max-turns"
                    type="number"
                    min="1"
                    max="100"
                    value={batchMaxTurns}
                    onChange={(event) => setBatchMaxTurns(Number(event.target.value))}
                  />
                </div>
                <div>
                  <label htmlFor="batch-gap-ms">Pause between lines (ms)</label>
                  <input
                    id="batch-gap-ms"
                    type="number"
                    min="0"
                    max="3000"
                    step="50"
                    value={batchGapMs}
                    onChange={(event) => setBatchGapMs(Number(event.target.value))}
                  />
                </div>
              </div>
              <div className="batch-voice-mapping">
                <VoiceMapping
                  roles={roles}
                  language={language}
                  roleVoiceMap={batchRoleVoiceMap}
                  onChange={(role, voiceId) => {
                    setBatchRoleVoiceMap((current) => ({ ...current, [role]: voiceId }))
                    setBatchJob(null)
                  }}
                />
                <p className="hint">These role voices are fixed across all {batchCount || 0} audio files.</p>
              </div>
              <button className="primary-btn" onClick={handleGenerateBatch} disabled={loading || !allBatchVoicesAssigned}>
                {loading ? 'Starting batch...' : `Generate ${batchCount || 0} Scripts + MP3s`}
              </button>
            </>
          )}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {mode === 'batch' && (
        <BatchJobPanel
          job={batchJob}
          onRetry={handleRetryBatch}
          onUseScript={useBatchScript}
          retrying={retrying}
        />
      )}
    </div>
  )
}
