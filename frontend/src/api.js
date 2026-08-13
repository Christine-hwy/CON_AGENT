const BASE = '/api'

async function readJson(res, fallbackMessage) {
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`${fallbackMessage} (HTTP ${res.status})`)
  }
  if (!res.ok) throw new Error(data.error || fallbackMessage)
  return data
}

export async function parseChatlog(file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/parse-chatlog`, { method: 'POST', body: formData })
  return readJson(res, 'Failed to parse file')
}

export async function generateScript(scenario, roles, maxTurns = 20, language = 'en') {
  const res = await fetch(`${BASE}/generate-script`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario, roles, max_turns: maxTurns, language }),
  })
  return readJson(res, 'Failed to generate script with DeepSeek')
}

export async function createBatchJob(payload) {
  const res = await fetch(`${BASE}/batch-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJson(res, 'Failed to create batch audio job')
}

export async function fetchBatchJob(jobId) {
  const res = await fetch(`${BASE}/batch-jobs/${encodeURIComponent(jobId)}`)
  return readJson(res, 'Failed to load batch audio job')
}

export async function retryBatchJob(jobId) {
  const res = await fetch(`${BASE}/batch-jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  })
  return readJson(res, 'Failed to retry batch audio job')
}

export async function fetchVoices() {
  const res = await fetch(`${BASE}/voices`)
  const data = await readJson(res, 'Failed to load voices')
  return data.voices
}

export async function generateAudio(turns, roleVoiceMap, gapMs, language = 'auto') {
  const res = await fetch(`${BASE}/generate-audio`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      turns,
      role_voice_map: roleVoiceMap,
      gap_ms: gapMs,
      language,
    }),
  })
  return readJson(res, 'Failed to generate audio')
}
