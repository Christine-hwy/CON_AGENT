import React from 'react'

export default function ResultPanel({ result }) {
  if (!result) return null
  return (
    <div className="result-panel">
      <h3>Done — {result.turn_count} turns generated</h3>
      <audio controls src={result.audio_url}></audio>
      <a className="primary-btn" href={result.audio_url} download>
        Download Audio
      </a>
    </div>
  )
}
