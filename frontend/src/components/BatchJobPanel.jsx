import React from 'react'

const STAGE_LABELS = {
  queued: 'Waiting to start',
  planning: 'Planning distinct scenarios',
  generating_scripts: 'Generating dialogue scripts',
  generating_audio: 'Generating audio files',
  retrying: 'Retrying failed items',
  completed: 'Completed',
  failed: 'Failed',
  interrupted: 'Interrupted by backend restart',
}

export default function BatchJobPanel({ job, onRetry, onUseScript, retrying }) {
  if (!job) return null
  const canRetry = ['completed', 'partial_failed', 'failed'].includes(job.status) && job.failed_count > 0

  return (
    <div className="batch-job-panel">
      <div className="batch-job-header">
        <div>
          <h3>Batch audio job</h3>
          <p>{STAGE_LABELS[job.stage] || job.stage} · {job.completed_count}/{job.requested_count} audio files</p>
        </div>
        {job.zip_url && (
          <a className="secondary-btn" href={job.zip_url} download>Download all ZIP</a>
        )}
      </div>

      <div className="progress-track" aria-label={`${job.progress_percent}% complete`}>
        <div className="progress-fill" style={{ width: `${job.progress_percent}%` }} />
      </div>
      <div className="batch-progress-meta">
        <span>{job.progress_percent}%</span>
        <span>{job.script_count} scripts · {job.failed_count} failed</span>
      </div>

      {job.error && <div className="error">{job.error}</div>}

      <div className="batch-audio-results">
        {job.items.map((item) => (
          <div className={`batch-result ${item.status === 'completed' ? 'success' : item.status === 'failed' ? 'error' : ''}`} key={item.index}>
            <div className="batch-result-title">
              <strong>#{item.index + 1}</strong>
              <span>{item.variant?.title || `Variation ${item.index + 1}`}</span>
              <small>{item.status.replaceAll('_', ' ')}</small>
            </div>
            {item.variant?.trigger && <p>{item.variant.trigger}</p>}
            {item.script?.turns && (
              <div className="batch-preview">
                {item.script.turns.slice(0, 3).map((turn, index) => (
                  <div key={`${turn.speaker}-${index}`}><b>{turn.speaker}:</b> {turn.text}</div>
                ))}
                {item.script.turns.length > 3 && <div>…</div>}
              </div>
            )}
            {item.audio_url && (
              <div className="batch-audio-actions">
                <audio controls preload="none" src={item.audio_url} />
                <a className="secondary-btn" href={item.audio_url} download>Download MP3</a>
              </div>
            )}
            {item.script?.turns && (
              <button className="text-btn" type="button" onClick={() => onUseScript(item)}>
                Open script in editor
              </button>
            )}
            {item.error && <p className="batch-error">{item.error}</p>}
          </div>
        ))}
      </div>

      {canRetry && (
        <button className="primary-btn" type="button" onClick={onRetry} disabled={retrying}>
          {retrying ? 'Retrying...' : `Retry ${job.failed_count} failed item(s)`}
        </button>
      )}
    </div>
  )
}
