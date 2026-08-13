import React from 'react'

export default function TranscriptPreview({ turns, onChange }) {
  function updateText(index, text) {
    onChange(turns.map((turn, turnIndex) => (turnIndex === index ? { ...turn, text } : turn)))
  }

  function removeTurn(index) {
    onChange(turns.filter((_, turnIndex) => turnIndex !== index))
  }

  return (
    <div className="transcript">
      <div className="transcript-header">
        <strong>Review dialogue</strong>
        <span>Edit the script before generating audio.</span>
      </div>
      {turns.map((turn, index) => (
        <div className="transcript-row" key={`${turn.speaker}-${index}`}>
          <div className="transcript-meta">
            <span className="speaker-tag">{turn.speaker}</span>
            {turn.timestamp && (
              <span className="timestamp">{new Date(turn.timestamp).toLocaleTimeString()}</span>
            )}
            <button
              className="text-btn danger"
              type="button"
              onClick={() => removeTurn(index)}
              aria-label={`Delete turn ${index + 1}`}
            >
              Delete
            </button>
          </div>
          <textarea
            className="transcript-editor"
            rows={2}
            value={turn.text}
            onChange={(event) => updateText(index, event.target.value)}
            aria-label={`${turn.speaker} dialogue turn ${index + 1}`}
          />
        </div>
      ))}
    </div>
  )
}
