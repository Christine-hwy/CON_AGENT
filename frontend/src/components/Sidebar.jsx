import React from 'react'

const NAV_ITEMS = ['New Dialogue', 'History']

function WaveformLogo() {
  const heights = [6, 12, 18, 10, 16, 8, 14]
  return (
    <svg width="16" height="18" viewBox="0 0 16 18" fill="none">
      {heights.map((h, i) => (
        <rect key={i} x={i * 2.3} y={(18 - h) / 2} width="1.4" height={h} rx="0.7" fill="#fff" />
      ))}
    </svg>
  )
}

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <WaveformLogo />
        </div>
        <span>KEAI</span>
      </div>
      <nav>
        {NAV_ITEMS.map((item, i) => (
          <div key={item} className={i === 0 ? 'sidebar-item active' : 'sidebar-item'}>
            {item}
          </div>
        ))}
      </nav>
    </aside>
  )
}
