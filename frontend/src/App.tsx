import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

interface DynamicToken {
  token: string
  role: string
  snowflake_user: string
  snowflake_role: string
  scopes: string[]
  expires_at: number
}

interface UserProfile {
  username: string
  email: string
  role: string
  store_id: string
  region: string
  accessible_agents?: any[]
  dynamic_token: DynamicToken
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  steps?: any[]
  agent_used?: string
  timestamp: string
}

const DEMO_PERSONAS = [
  { username: 'maya', name: 'Maya Chen', role: 'barista', store: 'S01', badge: 'Barista (Store S01)', icon: '☕' },
  { username: 'sam', name: 'Sam Rivera', role: 'store_manager', store: 'S01', badge: 'Store Manager (S01)', icon: '📋' },
  { username: 'priya', name: 'Priya Nair', role: 'regional_manager', store: 'HQ', badge: 'Regional Mgr (North)', icon: '📊' },
  { username: 'felix', name: 'Felix Weber', role: 'finance_analyst', store: 'HQ', badge: 'Finance Analyst', icon: '💼' },
  { username: 'hana', name: 'Hana Sato', role: 'hr_admin', store: 'HQ', badge: 'HR Administrator', icon: '👥' },
]

const ROLE_SUGGESTIONS: Record<string, string[]> = {
  barista: [
    'Check low inventory for my store (S01)',
    'Can I see all employee salaries? (Zero Trust Test)',
    'Show recipe for Artisan Oat Milk Latte',
  ],
  store_manager: [
    'Show team roster for Store S01',
    'Restock Espresso Beans (SKU001) by 25 units',
    'Summarize sales revenue for Store S01',
  ],
  regional_manager: [
    'Summarize sales across all stores in North region',
    'Which store has the lowest inventory levels?',
    'List store managers in my region',
  ],
  finance_analyst: [
    'Show company salary statistics and headcount',
    'Show total sales revenue grouped by product',
    'Analyze budget breakdown across regions',
  ],
  hr_admin: [
    'Show full employee roster across all stores',
    'List all baristas assigned to Store S01',
  ],
}

export default function App() {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [inspectAudit, setInspectAudit] = useState<any | null>(null)
  const [activeTab, setActiveTab] = useState<'audit' | 'identity' | 'memory'>('audit')
  const [memories, setMemories] = useState<any[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const refreshMemories = async () => {
    try {
      const res = await fetch('/api/memory', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setMemories(data.facts || [])
      }
    } catch {}
  }

  const handleDeleteMemory = async (entity: string) => {
    try {
      const res = await fetch('/api/memory/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity }),
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setMemories(data.facts || [])
      }
    } catch {}
  }

  const handleClearMemory = async () => {
    try {
      const res = await fetch('/api/memory/clear', {
        method: 'POST',
        credentials: 'include'
      })
      if (res.ok) {
        setMemories([])
      }
    } catch {}
  }

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) {
          setUser(data)
          refreshMemories()
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleLogin = async (username: string) => {
    setLoading(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
        credentials: 'include'
      })
      if (res.ok) {
        const u = await res.json()
        setUser(u)
        refreshMemories()
        setMessages([
          {
            id: 'welcome',
            role: 'assistant',
            content: `☕ **Welcome ${u.username}!**\n\nAuthenticated via **Keycloak SSO** as **${u.role}** (Store **${u.store_id}**, Region **${u.region}**).\n\nYou are connected to the **Bean & Brew Master Operations Agent** with Zero Trust Multi-Agent Collaborators (\`bb_hr_agent\`, \`bb_finance_agent\`) and native session memory.\n\n*Ephemeral Snowflake OAuth Token: \`${u.dynamic_token?.token?.slice(0, 16)}...\` (Valid for 300s).*`,
            timestamp: new Date().toLocaleTimeString()
          }
        ])
        setThreadId(null)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setUser(null)
    setMessages([])
    setThreadId(null)
    setInspectAudit(null)
    setMemories([])
  }

  const sendQuery = async (queryText: string) => {
    if (!queryText.trim() || loading || !user) return

    setInput('')
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: queryText,
      timestamp: new Date().toLocaleTimeString()
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: queryText, thread_id: threadId }),
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setThreadId(data.thread_id)
        const botMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.reply,
          steps: data.steps,
          agent_used: data.agent_used,
          timestamp: new Date().toLocaleTimeString()
        }
        setMessages(prev => [...prev, botMsg])
        if (data.memories) {
          setMemories(data.memories)
        }
        setInspectAudit({
          steps: data.steps,
          agent_used: data.agent_used,
          thread_id: data.thread_id,
          token: data.dynamic_token
        })
      } else {
        const err = await res.json()
        setMessages(prev => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: `⛔ ${err.detail || 'Access Denied or Execution Error'}`,
            timestamp: new Date().toLocaleTimeString()
          }
        ])
      }
    } catch (e: any) {
      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: `⚠️ Network error: ${e.message}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  if (!user) {
    return (
      <div className="login-screen">
        <div className="login-hero-card">
          <div className="hero-visual-pane">
            <img src="/hero.jpg" alt="Bean & Brew Coffee Bar" className="hero-banner-image" />
            <div className="hero-gradient-overlay">
              <span className="hero-subtitle-tag">ENTERPRISE MULTI-AGENT PLATFORM</span>
              <h3>Artisan Roastery Operations</h3>
              <p>
                IBM Watsonx Orchestrate • Zero Trust Collaborator Routing • Snowflake RSA Key-Pair Security
              </p>
            </div>
          </div>

          <div className="login-form-pane">
            <div className="brand-header-box">
              <img src="/logo.jpg" alt="Bean & Brew Logo" className="login-logo-img" />
              <div>
                <h2>Bean & Brew AI Portal</h2>
                <p className="subtitle">
                  Select an authenticated persona to test role-based access, collaborator routing, and ephemeral tokens.
                </p>
              </div>
            </div>

            <div className="persona-selection">
              <h4>Select Employee Persona:</h4>
              <div className="persona-grid">
                {DEMO_PERSONAS.map(p => (
                  <button
                    key={p.username}
                    className="persona-btn"
                    onClick={() => handleLogin(p.username)}
                    disabled={loading}
                  >
                    <div className="persona-top">
                      <span className="persona-icon">{p.icon}</span>
                      <span className="p-title">{p.name}</span>
                    </div>
                    <div className="p-badge">{p.badge}</div>
                  </button>
                ))}
              </div>
            </div>

            {loading && (
              <div className="login-status-pill">
                <span className="status-spinner"></span>
                <span>Authenticating with Keycloak & initializing session...</span>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  const suggestions = ROLE_SUGGESTIONS[user.role] || []

  return (
    <div className="app-container">
      {/* App Header */}
      <header className="app-header">
        <div className="header-brand">
          <img src="/logo.jpg" alt="Bean & Brew Logo" className="header-logo-img" />
          <div className="brand-info">
            <div className="title-row">
              <h3>Bean & Brew</h3>
              <span className="artisan-badge">Operations AI</span>
            </div>
            <span className="model-tag">Master Operations Agent • Multi-Agent Collaborators • Snowflake RSA</span>
          </div>
        </div>

        <div className="user-profile-strip">
          <div className="agent-badge-pill">
            <span className="agent-indicator-dot"></span>
            <span>Master Operations Agent</span>
          </div>

          <div className="user-meta">
            <span className="user-name">👤 {user.username}</span>
            <span className="role-pill">{user.role}</span>
            <span className="store-pill">Store {user.store_id}</span>
          </div>
          <button className="logout-btn" onClick={handleLogout}>Switch User</button>
        </div>
      </header>

      {/* Main Chat Layout */}
      <div className="chat-layout">
        <div className="chat-main">
          <div className="message-list">
            {messages.map(m => (
              <div key={m.id} className={`message-bubble ${m.role}`}>
                <div className="bubble-header">
                  <span className="author">
                    {m.role === 'user' ? user.username : (m.agent_used || 'Master Operations Agent')}
                  </span>
                  <span className="time">{m.timestamp}</span>
                </div>

                {/* Rendered Markdown Body with HTML Tables */}
                <div className="bubble-content markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {m.content}
                  </ReactMarkdown>
                </div>

                {m.steps && m.steps.length > 0 && (
                  <div className="bubble-footer">
                    <button
                      className="audit-btn"
                      onClick={() => {
                        setInspectAudit({
                          steps: m.steps,
                          agent_used: m.agent_used,
                          thread_id: threadId,
                          token: user.dynamic_token
                        })
                        setActiveTab('audit')
                      }}
                    >
                      🔍 Inspect Agent Routing & Tool Audit
                    </button>
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="message-bubble assistant loading-indicator">
                <span className="dots">☕ Master Agent reasoning & evaluating Zero Trust policies...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Suggestions Strip */}
          <div className="suggestions-strip">
            <span className="suggestions-label">Quick Actions:</span>
            {suggestions.map((s, idx) => (
              <button
                key={idx}
                className="suggestion-chip"
                onClick={() => sendQuery(s)}
                disabled={loading}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Chat Input Bar */}
          <form className="input-bar" onSubmit={(e) => { e.preventDefault(); sendQuery(input); }}>
            <input
              type="text"
              placeholder={`Ask Master Agent as ${user.role} (e.g. inventory, team roster, sales statistics)...`}
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>Send</button>
          </form>
        </div>

        {/* Minimal Clean Inspector Drawer */}
        <aside className="audit-drawer">
          <div className="drawer-header">
            <h4>Agent & Security Inspector</h4>
          </div>

          <div className="tab-buttons">
            <button
              className={activeTab === 'audit' ? 'tab-btn active' : 'tab-btn'}
              onClick={() => setActiveTab('audit')}
            >
              Execution Audit
            </button>
            <button
              className={activeTab === 'identity' ? 'tab-btn active' : 'tab-btn'}
              onClick={() => setActiveTab('identity')}
            >
              Identity & Token
            </button>
            <button
              className={activeTab === 'memory' ? 'tab-btn active' : 'tab-btn'}
              onClick={() => setActiveTab('memory')}
            >
              🧠 Memory {memories.length > 0 && `(${memories.length})`}
            </button>
          </div>

          <div className="drawer-body">
            {activeTab === 'audit' && (
              <div className="audit-tab-content">
                <div className="inspector-card">
                  <div className="card-label">Active Orchestrator:</div>
                  <div className="card-val">
                    <strong>bb_master_agent</strong>
                  </div>
                  <div className="card-sub">
                    Session Thread: <code>{threadId || 'Initialized on first message'}</code>
                  </div>
                </div>

                <div className="collaborator-architecture-card">
                  <div className="card-label">Available Multi-Agent Collaborators:</div>
                  <div className="collab-item">
                    <span className="collab-dot hr"></span>
                    <div>
                      <strong>bb_hr_agent</strong>
                      <p>Employee rosters, personnel directory (Salaries masked for Store Managers).</p>
                    </div>
                  </div>
                  <div className="collab-item">
                    <span className="collab-dot finance"></span>
                    <div>
                      <strong>bb_finance_agent</strong>
                      <p>Company-wide sales aggregates & salary statistics (Finance Analysts only).</p>
                    </div>
                  </div>
                  <div className="collab-item">
                    <span className="collab-dot tool"></span>
                    <div>
                      <strong>Direct Snowflake Tools</strong>
                      <p><code>bb_get_inventory</code>, <code>bb_restock_inventory</code> via RSA key-pair auth.</p>
                    </div>
                  </div>
                </div>

                <h5 className="subgraph-section-title">🔍 Tool & Routing Traces</h5>
                {inspectAudit?.steps && inspectAudit.steps.length > 0 ? (
                  <div className="steps-list">
                    {inspectAudit.steps.map((st: any, idx: number) => (
                      <div key={idx} className="step-card">
                        <div className="step-top">
                          <span className="step-badge">{st.node || 'tool_call'}</span>
                          <span className="step-status">{st.status || 'executed'}</span>
                        </div>
                        {st.tool && (
                          <div className="step-info-row">
                            <span>Tool: <strong>{st.tool}</strong></span>
                            {st.user && <span>User: <code>{st.user}</code></span>}
                          </div>
                        )}
                        {st.auth && (
                          <div className="step-auth-pill">
                            🔐 Auth: {st.auth}
                          </div>
                        )}
                      </div>
                    ))}
                    <details className="raw-json-details">
                      <summary>View Raw Trace JSON</summary>
                      <pre className="audit-json">
                        {JSON.stringify(inspectAudit.steps, null, 2)}
                      </pre>
                    </details>
                  </div>
                ) : (
                  <p className="empty-sub">Send a message or click 'Inspect Agent Routing & Tool Audit' on any response to view live traces.</p>
                )}
              </div>
            )}

            {activeTab === 'identity' && (
              <div className="identity-tab-content">
                <div className="inspector-card">
                  <div className="card-label">Verified Context Variables:</div>
                  <div className="context-vars-list">
                    <div className="context-row">
                      <span>bb_role</span>
                      <strong>{user.role}</strong>
                    </div>
                    <div className="context-row">
                      <span>bb_store_id</span>
                      <strong>Store {user.store_id}</strong>
                    </div>
                    <div className="context-row">
                      <span>bb_region</span>
                      <strong>{user.region}</strong>
                    </div>
                    <div className="context-row">
                      <span>bb_email</span>
                      <strong>{user.email}</strong>
                    </div>
                  </div>
                </div>

                <div className="inspector-card">
                  <div className="card-label">Ephemeral Snowflake OAuth Token:</div>
                  <div className="token-meta-row">
                    <span>Snowflake User:</span>
                    <code>{user.dynamic_token?.snowflake_user}</code>
                  </div>
                  <div className="token-meta-row">
                    <span>Snowflake Role:</span>
                    <code>{user.dynamic_token?.snowflake_role}</code>
                  </div>
                  <div className="token-meta-row">
                    <span>Granted Scopes:</span>
                    <span>{user.dynamic_token?.scopes?.join(', ')}</span>
                  </div>
                  <div className="token-meta-row">
                    <span>TTL:</span>
                    <span className="ttl-badge">300s (Auto-Revoked)</span>
                  </div>
                  <div className="token-code-box">
                    <code>{user.dynamic_token?.token}</code>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'memory' && (
              <div className="memory-tab-content">
                <div className="inspector-card">
                  <div className="card-label">Dynamic EAV Preference State:</div>
                  <p className="card-desc">
                    Contradiction-free atomic slot memory. When preferences change, slots are dynamically updated with zero duplicates.
                  </p>

                  {memories.length > 0 ? (
                    <div className="memory-cards-list">
                      {memories.map((m: any, idx: number) => (
                        <div key={idx} className="memory-badge-card">
                          <div className="memory-badge-top">
                            <span className="memory-cat-pill">{m.category}</span>
                            <span className="memory-time">{m.updated_at ? m.updated_at.split(' ')[1] : 'active'}</span>
                          </div>
                          <div className="memory-fact-text">
                            <strong>{m.entity}</strong> <span>({m.attribute})</span>: <span className="memory-val">{m.value}</span>
                          </div>
                          <button
                            className="del-memory-btn"
                            onClick={() => handleDeleteMemory(m.entity)}
                            title="Delete preference"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="empty-sub">No preferences stored yet. Try saying "I prefer oat milk" or "Format in tables".</p>
                  )}

                  {memories.length > 0 && (
                    <button className="clear-memory-btn" onClick={handleClearMemory}>
                      🗑️ Clear All Learned Preferences
                    </button>
                  )}
                </div>

                <div className="teach-preference-box">
                  <div className="card-label">Test Dynamic Memory Invalidation:</div>
                  <p className="card-sub">Click a prompt to see atomic slot updates supersede old values in real time:</p>
                  <div className="quick-pref-chips">
                    <button className="pref-chip" onClick={() => sendQuery("I switched to almond milk, please use that.")}>
                      🔄 Switch to Almond Milk
                    </button>
                    <button className="pref-chip" onClick={() => sendQuery("I prefer oat milk in my drinks.")}>
                      🥛 Prefer Oat Milk
                    </button>
                    <button className="pref-chip" onClick={() => sendQuery("Always format my responses in markdown tables.")}>
                      📊 Format: Markdown Tables
                    </button>
                    <button className="pref-chip" onClick={() => sendQuery("Default lookback window to 14 days.")}>
                      📅 Lookback: 14 Days
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
