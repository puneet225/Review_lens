'use client'

import { useState, useEffect, useRef } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Quote = { text: string; rating: number; store: string }
type Theme = {
  name: string
  description: string
  review_count: number
  action: string
  quotes: Quote[]
}
type Job = {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  themes?: Theme[]
  stats?: { reviews: number; themes: number; tokens: number }
  error?: string
}

const WEEK_OPTIONS = [
  { label: '1 Week', value: 1 },
  { label: '2 Weeks', value: 2 },
  { label: '3 Weeks', value: 3 },
  { label: '4 Weeks', value: 4 },
  { label: '6 Weeks', value: 6 },
  { label: '8 Weeks', value: 8 },
  { label: '12 Weeks', value: 12 },
]

const STAR_COLORS: Record<number, string> = {
  1: '#ef4444', 2: '#f97316', 3: '#f59e0b', 4: '#84cc16', 5: '#10b981'
}

export default function Home() {
  const [maxReviews, setMaxReviews] = useState(1000)
  const [weeks, setWeeks] = useState(4)
  const [job, setJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(false)
  const [emailInput, setEmailInput] = useState('225puneet@gmail.com')
  const [deliveryStatus, setDeliveryStatus] = useState<{ email?: string; doc?: string }>({})
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const progressRef = useRef(0)
  const [progress, setProgress] = useState(0)

  const startAnalysis = async () => {
    setLoading(true)
    setJob(null)
    setDeliveryStatus({})
    setProgress(5)
    try {
      const res = await fetch(`${API}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product: 'groww', weeks, max_reviews: maxReviews }),
      })
      const data = await res.json()
      setJob({ job_id: data.job_id, status: 'queued' })
      pollJob(data.job_id)
    } catch (e) {
      setLoading(false)
      alert('Failed to connect to backend. Make sure the server is running.')
    }
  }

  const pollJob = (jobId: string) => {
    let tick = 10
    pollRef.current = setInterval(async () => {
      tick = Math.min(tick + 3, 90)
      setProgress(tick)
      try {
        const res = await fetch(`${API}/api/jobs/${jobId}`)
        const data: Job = await res.json()
        setJob(data)
        if (data.status === 'done' || data.status === 'failed') {
          clearInterval(pollRef.current!)
          setLoading(false)
          setProgress(100)
        }
      } catch {}
    }, 2000)
  }

  const sendEmail = async () => {
    if (!job) return
    setDeliveryStatus(s => ({ ...s, email: 'sending' }))
    try {
      const res = await fetch(`${API}/api/deliver/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: job.job_id, recipients: [emailInput] }),
      })
      const data = await res.json()
      setDeliveryStatus(s => ({ ...s, email: data.status === 'sent' ? 'sent' : 'error' }))
    } catch {
      setDeliveryStatus(s => ({ ...s, email: 'error' }))
    }
  }

  const createDoc = async () => {
    if (!job) return
    setDeliveryStatus(s => ({ ...s, doc: 'creating' }))
    try {
      const res = await fetch(`${API}/api/deliver/gdoc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: job.job_id }),
      })
      const data = await res.json()
      setDeliveryStatus(s => ({
        ...s,
        doc: data.doc_url ? data.doc_url : 'error'
      }))
    } catch {
      setDeliveryStatus(s => ({ ...s, doc: 'error' }))
    }
  }

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const isDone = job?.status === 'done'
  const isRunning = loading || job?.status === 'queued' || job?.status === 'running'

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <header style={{
        padding: '20px 40px',
        borderBottom: '1px solid #1e1e2e',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        background: 'linear-gradient(180deg, #0d0d18 0%, #0a0a0f 100%)',
        position: 'sticky', top: 0, zIndex: 100,
        backdropFilter: 'blur(12px)',
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10,
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, boxShadow: '0 0 20px #6366f140',
        }}>📊</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 18, letterSpacing: '-0.5px' }}>Review Pulse</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>AI-Powered Product Review Analyst</div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <span style={{
            padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 500,
            background: '#10b98120', color: '#10b981', border: '1px solid #10b98140',
          }}>● Live</span>
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, gap: 0 }}>
        {/* Left Sidebar — Controls */}
        <aside style={{
          width: 320, minWidth: 320,
          background: '#0d0d18',
          borderRight: '1px solid #1e1e2e',
          padding: '32px 24px',
          display: 'flex', flexDirection: 'column', gap: 32,
          position: 'sticky', top: 81, height: 'calc(100vh - 81px)', overflowY: 'auto',
        }}>
          <div>
            <h2 style={{ fontSize: 13, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 20 }}>
              Analysis Settings
            </h2>

            {/* Product */}
            <div style={{ marginBottom: 28 }}>
              <label style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500, display: 'block', marginBottom: 10 }}>
                Product
              </label>
              <div style={{
                padding: '10px 14px', borderRadius: 10, border: '1px solid #1e1e2e',
                background: '#12121a', color: '#f1f5f9', fontSize: 14, fontWeight: 500,
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span>📱</span> Groww
              </div>
            </div>

            {/* Reviews Slider */}
            <div style={{ marginBottom: 28 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <label style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500 }}>
                  Max Reviews
                </label>
                <span style={{
                  fontSize: 13, fontWeight: 700, color: '#6366f1',
                  background: '#6366f115', padding: '2px 8px', borderRadius: 6,
                }}>
                  {maxReviews.toLocaleString()}
                </span>
              </div>
              <input
                type="range"
                min={100} max={5000} step={100}
                value={maxReviews}
                onChange={e => setMaxReviews(Number(e.target.value))}
                style={{
                  width: '100%', accentColor: '#6366f1', cursor: 'pointer',
                  height: 4, borderRadius: 2,
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
                <span style={{ fontSize: 11, color: '#475569' }}>100</span>
                <span style={{ fontSize: 11, color: '#475569' }}>5,000</span>
              </div>
            </div>

            {/* Date Range */}
            <div style={{ marginBottom: 32 }}>
              <label style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500, display: 'block', marginBottom: 10 }}>
                Date Range (from today)
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {WEEK_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setWeeks(opt.value)}
                    style={{
                      padding: '8px 4px', borderRadius: 8, border: '1px solid',
                      fontSize: 13, fontWeight: 500, cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      borderColor: weeks === opt.value ? '#6366f1' : '#1e1e2e',
                      background: weeks === opt.value ? '#6366f115' : '#12121a',
                      color: weeks === opt.value ? '#818cf8' : '#64748b',
                      boxShadow: weeks === opt.value ? '0 0 12px #6366f120' : 'none',
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Run Button */}
            <button
              onClick={startAnalysis}
              disabled={isRunning}
              style={{
                width: '100%', padding: '14px', borderRadius: 12, border: 'none',
                background: isRunning
                  ? 'linear-gradient(135deg, #4338ca, #6d28d9)'
                  : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                color: 'white', fontSize: 15, fontWeight: 600, cursor: isRunning ? 'wait' : 'pointer',
                opacity: isRunning ? 0.8 : 1,
                boxShadow: '0 4px 20px #6366f130',
                transition: 'all 0.2s ease',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              {isRunning ? (
                <>
                  <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⚙️</span>
                  Analyzing...
                </>
              ) : '🚀 Run Analysis'}
            </button>
          </div>

          {/* Delivery Options (shown only after job is done) */}
          {isDone && (
            <div style={{ borderTop: '1px solid #1e1e2e', paddingTop: 28 }}>
              <h2 style={{ fontSize: 13, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 20 }}>
                Deliver Report
              </h2>

              {/* Email */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 8 }}>
                  Email Recipients
                </label>
                <input
                  type="email"
                  value={emailInput}
                  onChange={e => setEmailInput(e.target.value)}
                  style={{
                    width: '100%', padding: '9px 12px', borderRadius: 8,
                    border: '1px solid #1e1e2e', background: '#12121a',
                    color: '#f1f5f9', fontSize: 13, marginBottom: 10,
                    outline: 'none',
                  }}
                />
                <button
                  onClick={sendEmail}
                  disabled={deliveryStatus.email === 'sending' || deliveryStatus.email === 'sent'}
                  style={{
                    width: '100%', padding: '10px', borderRadius: 8, border: '1px solid #1e1e2e',
                    background: deliveryStatus.email === 'sent' ? '#10b98120' : '#12121a',
                    color: deliveryStatus.email === 'sent' ? '#10b981' : '#94a3b8',
                    fontSize: 13, fontWeight: 500, cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  {deliveryStatus.email === 'sending' ? '⏳ Sending...'
                    : deliveryStatus.email === 'sent' ? '✅ Email Sent!'
                    : deliveryStatus.email === 'error' ? '❌ Failed — Retry'
                    : '📧 Send Email'}
                </button>
              </div>

              {/* Google Doc */}
              <button
                onClick={createDoc}
                disabled={deliveryStatus.doc === 'creating' || (deliveryStatus.doc || '').startsWith('http')}
                style={{
                  width: '100%', padding: '10px', borderRadius: 8, border: '1px solid #1e1e2e',
                  background: (deliveryStatus.doc || '').startsWith('http') ? '#6366f115' : '#12121a',
                  color: (deliveryStatus.doc || '').startsWith('http') ? '#818cf8' : '#94a3b8',
                  fontSize: 13, fontWeight: 500, cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {deliveryStatus.doc === 'creating' ? '⏳ Creating Doc...'
                  : (deliveryStatus.doc || '').startsWith('http') ? '✅ Doc Created!'
                  : deliveryStatus.doc === 'error' ? '❌ Failed — Retry'
                  : '📄 Create Google Doc'}
              </button>
              {(deliveryStatus.doc || '').startsWith('http') && (
                <a
                  href={deliveryStatus.doc}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'block', marginTop: 8, textAlign: 'center',
                    fontSize: 12, color: '#6366f1', textDecoration: 'none',
                  }}
                >
                  Open in Google Docs →
                </a>
              )}
            </div>
          )}
        </aside>

        {/* Main Content Area */}
        <main style={{ flex: 1, padding: '32px 40px', overflowY: 'auto' }}>
          {/* Empty state */}
          {!job && !loading && (
            <div style={{
              height: '100%', display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 20,
              color: '#334155', textAlign: 'center',
              minHeight: 'calc(100vh - 200px)',
            }}>
              <div style={{ fontSize: 64, opacity: 0.5 }}>📊</div>
              <div style={{ fontSize: 22, fontWeight: 600, color: '#475569' }}>
                No analysis running
              </div>
              <div style={{ fontSize: 14, color: '#334155', maxWidth: 380 }}>
                Configure your settings on the left and click{' '}
                <strong style={{ color: '#6366f1' }}>Run Analysis</strong> to start
                ingesting and analyzing Groww reviews.
              </div>
              <div style={{
                display: 'flex', gap: 16, marginTop: 12,
                flexWrap: 'wrap', justifyContent: 'center',
              }}>
                {['🔍 AI Clustering', '⚡ Groq-Powered', '📧 Email Reports', '📄 Google Docs'].map(tag => (
                  <span key={tag} style={{
                    padding: '6px 14px', borderRadius: 20, fontSize: 13,
                    background: '#12121a', border: '1px solid #1e1e2e', color: '#64748b',
                  }}>{tag}</span>
                ))}
              </div>
            </div>
          )}

          {/* Progress bar */}
          {isRunning && (
            <div style={{ marginBottom: 32 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 16 }}>
                    {job?.status === 'queued' ? '⏳ Queued...'
                      : '🔬 Analyzing reviews...'}
                  </div>
                  <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
                    Scraping {maxReviews.toLocaleString()} reviews from last {weeks} week{weeks > 1 ? 's' : ''}
                  </div>
                </div>
                <span style={{ fontSize: 14, fontWeight: 600, color: '#6366f1' }}>{progress}%</span>
              </div>
              <div style={{ height: 6, background: '#12121a', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 3,
                  width: `${progress}%`,
                  background: 'linear-gradient(90deg, #6366f1, #8b5cf6)',
                  transition: 'width 0.5s ease',
                  boxShadow: '0 0 12px #6366f160',
                }} />
              </div>
              {/* Steps */}
              <div style={{ display: 'flex', gap: 24, marginTop: 20 }}>
                {[
                  { label: 'Ingestion', done: progress > 20 },
                  { label: 'Embedding', done: progress > 40 },
                  { label: 'Clustering', done: progress > 60 },
                  { label: 'Summarising', done: progress > 80 },
                  { label: 'Done', done: progress >= 100 },
                ].map(step => (
                  <div key={step.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: step.done ? '#10b981' : '#1e1e2e',
                      boxShadow: step.done ? '0 0 8px #10b981' : 'none',
                      transition: 'all 0.3s',
                    }} />
                    <span style={{ fontSize: 12, color: step.done ? '#10b981' : '#475569' }}>
                      {step.label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error state */}
          {job?.status === 'failed' && (
            <div style={{
              padding: 20, borderRadius: 12, border: '1px solid #ef444430',
              background: '#ef444410', marginBottom: 24, color: '#fca5a5',
            }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>❌ Analysis Failed</div>
              <div style={{ fontSize: 13 }}>{job.error}</div>
            </div>
          )}

          {/* Stats bar */}
          {isDone && job.stats && (
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16,
              marginBottom: 32,
            }}>
              {[
                { label: 'Reviews Analyzed', value: job.stats.reviews.toLocaleString(), icon: '📱', color: '#6366f1' },
                { label: 'Themes Identified', value: job.stats.themes, icon: '🔍', color: '#10b981' },
                { label: 'Tokens Used', value: job.stats.tokens.toLocaleString(), icon: '⚡', color: '#f59e0b' },
              ].map(stat => (
                <div key={stat.label} style={{
                  padding: '20px 24px', borderRadius: 14, border: '1px solid #1e1e2e',
                  background: '#12121a',
                }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>{stat.icon}</div>
                  <div style={{ fontSize: 28, fontWeight: 700, color: stat.color }}>{stat.value}</div>
                  <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>{stat.label}</div>
                </div>
              ))}
            </div>
          )}

          {/* Theme Cards */}
          {isDone && job.themes && job.themes.length > 0 && (
            <>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 20, color: '#f1f5f9' }}>
                🔍 Identified Themes
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 20 }}>
                {job.themes.map((theme, i) => (
                  <ThemeCard key={i} theme={theme} index={i} />
                ))}
              </div>
            </>
          )}
        </main>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  )
}

function ThemeCard({ theme, index }: { theme: Theme; index: number }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      style={{
        borderRadius: 14, border: '1px solid #1e1e2e',
        background: '#12121a',
        animation: `fadeIn 0.4s ease ${index * 0.08}s both`,
        transition: 'border-color 0.2s, box-shadow 0.2s',
        cursor: 'pointer',
        overflow: 'hidden',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.borderColor = '#6366f140'
        ;(e.currentTarget as HTMLElement).style.boxShadow = '0 4px 24px #6366f115'
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.borderColor = '#1e1e2e'
        ;(e.currentTarget as HTMLElement).style.boxShadow = 'none'
      }}
      onClick={() => setExpanded(x => !x)}
    >
      {/* Card Header */}
      <div style={{ padding: '20px 20px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
          <div style={{
            fontSize: 11, fontWeight: 600, color: '#6366f1',
            background: '#6366f115', padding: '3px 10px', borderRadius: 20,
            letterSpacing: 0.5,
          }}>
            THEME {index + 1}
          </div>
          <div style={{
            fontSize: 12, color: '#64748b',
            background: '#0a0a0f', padding: '3px 10px', borderRadius: 20,
            border: '1px solid #1e1e2e',
          }}>
            {theme.review_count} reviews
          </div>
        </div>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>
          {theme.name}
        </h3>
        <p style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6 }}>
          {theme.description || 'No description available.'}
        </p>
      </div>

      {/* Action */}
      {theme.action && (
        <div style={{
          margin: '0 20px 16px', padding: '10px 14px', borderRadius: 8,
          background: '#10b98110', border: '1px solid #10b98120',
          fontSize: 13, color: '#6ee7b7', lineHeight: 1.5,
        }}>
          <span style={{ fontWeight: 600, color: '#10b981' }}>✅ Action: </span>
          {theme.action}
        </div>
      )}

      {/* Quotes (collapsible) */}
      {theme.quotes && theme.quotes.length > 0 && (
        <div style={{ borderTop: '1px solid #1e1e2e' }}>
          <div style={{
            padding: '10px 20px', fontSize: 12, color: '#64748b', fontWeight: 500,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span>💬 {theme.quotes.length} user quote{theme.quotes.length > 1 ? 's' : ''}</span>
            <span style={{ fontSize: 10 }}>{expanded ? '▲' : '▼'}</span>
          </div>
          {expanded && (
            <div style={{ padding: '0 20px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              {theme.quotes.map((q, qi) => (
                <div key={qi} style={{
                  padding: '12px 14px', borderRadius: 8,
                  background: '#0a0a0f', border: '1px solid #1e1e2e',
                }}>
                  <p style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6, marginBottom: 8 }}>
                    "{q.text}"
                  </p>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{
                      fontSize: 12, fontWeight: 600,
                      color: STAR_COLORS[q.rating] || '#94a3b8',
                    }}>
                      {'★'.repeat(q.rating)}{'☆'.repeat(5 - q.rating)}
                    </span>
                    <span style={{
                      fontSize: 11, color: '#475569',
                      background: '#12121a', padding: '2px 8px', borderRadius: 10,
                      border: '1px solid #1e1e2e',
                    }}>
                      {q.store === 'playstore' ? '🤖 Play Store' : '📱 App Store'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
