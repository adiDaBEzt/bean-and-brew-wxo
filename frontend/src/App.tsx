import { useState, useEffect, useRef } from 'react'
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

interface SemanticFact {
  category: string
  entity: string
  attribute: string
  value: string
  confidence: number
  updated_at: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  steps?: any[]
  recalled_memories?: string[]
  agent_used?: string
  timestamp: string
}

const DEMO_PERSONAS = [
  { username: 'maya', name: 'Maya Chen', role: 'barista', store: 'S01', badge: 'Barista (Store S01)' },
  { username: 'sam', name: 'Sam Rivera', role: 'store_manager', store: 'S01', badge: 'Store Manager (S01)' },
  { username: 'priya', name: 'Priya Nair', role: 'regional_manager', store: 'HQ', badge: 'Regional Mgr (North)' },
  { username: 'felix', name: 'Felix Weber', role: 'finance_analyst', store: 'HQ', badge: 'Finance Analyst' },
  { username: 'hana', name: 'Hana Sato', role: 'hr_admin', store: 'HQ', badge: 'HR Administrator' },
]

const ROLE_SUGGESTIONS: Record<string, string[]> = {
  barista: [
    'Check low inventory for my store (S01)',
    'Can I see all employee salaries? (RBAC Block Test)',
    'Remember that I prefer brewing light roasts with oat milk (SQL Memory Test)',
    'Update my preference: I now use almond milk (SQL Conflict Resolution)',
  ],
  store_manager: [
    'Show team roster for Store S01',
    'Restock Oat Milk (SKU-OAT-001) by 25 units',
    'Summarize sales revenue for Store S01',
  ],
  regional_manager: [
    'Summarize sales across all stores in the North region',
    'List store managers across my region',
    'Which store has the lowest inventory levels?',
  ],
  finance_analyst: [
    'Provide salary summary and budget breakdown for Store S01',
    'Show total sales revenue for all stores',
    'Analyze inventory costs across regions',
  ],
  hr_admin: [
    'Show full employee roster across all stores',
    'List all baristas working at Store S01',
    'Audit staff distribution across regions',
  ],
}

export default function App() {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [inspectAudit, setInspectAudit] = useState<any | null>(null)
  const [activeTab, setActiveTab] = useState<'tools' | 'memory' | 'token'>('tools')
  const [facts, setFacts] = useState<SemanticFact[]>([])
  const [newEntity, setNewEntity] = useState('')
  const [newAttr, setNewAttr] = useState('type')
  const [newVal, setNewVal] = useState('')
  const [memoryActionMsg, setMemoryActionMsg] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

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

  const refreshMemories = async () => {
    try {
      const res = await fetch('/api/memory', { credentials: 'include' })
      if (res.ok) {
        const d = await res.json()
        setFacts(d.facts || [])
      }
    } catch {}
  }

  const handleClearMemory = async () => {
    try {
      const res = await fetch('/api/memory/clear', { method: 'POST', credentials: 'include' })
      if (res.ok) {
        setMemoryActionMsg('Cleared all SQLite memory rows.')
        setTimeout(() => setMemoryActionMsg(''), 3000)
        refreshMemories()
      }
    } catch {}
  }

  const handleDeleteFact = async (fact: SemanticFact) => {
    try {
      const res = await fetch('/api/memory/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: fact.category,
          entity: fact.entity,
          attribute: fact.attribute,
        }),
        credentials: 'include',
      })
      if (res.ok) {
        setMemoryActionMsg(`Deleted ${fact.entity} (${fact.attribute})`)
        setTimeout(() => setMemoryActionMsg(''), 3000)
        refreshMemories()
      }
    } catch {}
  }

  const handleManualUpsert = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newEntity.trim() || !newVal.trim()) return
    try {
      const res = await fetch('/api/memory/upsert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: 'preference',
          entity: newEntity.trim(),
          attribute: newAttr.trim() || 'type',
          value: newVal.trim(),
        }),
        credentials: 'include',
      })
      if (res.ok) {
        setMemoryActionMsg(`Upserted: ${newEntity} -> ${newVal}`)
        setTimeout(() => setMemoryActionMsg(''), 3000)
        setNewEntity('')
        setNewVal('')
        refreshMemories()
      }
    } catch {}
  }

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
        setMessages([
          {
            id: 'welcome',
            role: 'assistant',
            content: `☕ **Welcome ${u.username}!**\n\nAuthenticated via Keycloak SSO as **${u.role}** (Store **${u.store_id}**, Region **${u.region}**).\n\nYou are connected to the **Bean & Brew Master Operations Agent** with Zero Trust Multi-Agent RBAC.\nEphemeral Snowflake OAuth Token: \`${u.dynamic_token?.token?.slice(0, 16)}...\` (Valid for 300s).`,
            timestamp: new Date().toLocaleTimeString()
          }
        ])
        setThreadId(null)
        refreshMemories()
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
    setFacts([])
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
          recalled_memories: data.recalled_memories,
          agent_used: data.agent_used,
          timestamp: new Date().toLocaleTimeString()
        }
        setMessages(prev => [...prev, botMsg])
        refreshMemories()
        setTimeout(refreshMemories, 1500)
        setTimeout(refreshMemories, 4000)
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
        <div className="login-card">
          <div className="logo-badge">☕ Bean & Brew</div>
          <h2>Enterprise Zero Trust AI Portal</h2>
          <p className="subtitle">
            IBM watsonx Orchestrate Multi-Agent Router with Keycloak SSO, Ephemeral Snowflake OAuth Tokens & Mem0 Long-Term Memory.
          </p>

          <div className="persona-selection">
            <h4>Select an authenticated employee persona:</h4>
            <div className="persona-grid">
              {DEMO_PERSONAS.map(p => (
                <button
                  key={p.username}
                  className="persona-btn"
                  onClick={() => handleLogin(p.username)}
                  disabled={loading}
                >
                  <div className="p-title">{p.name}</div>
                  <div className="p-badge">{p.badge}</div>
                </button>
              ))}
            </div>
          </div>
          {loading && <p className="status-note">Authenticating via Keycloak & minting dynamic credentials...</p>}
        </div>
      </div>
    )
  }

  const suggestions = ROLE_SUGGESTIONS[user.role] || []

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <span className="logo-icon">☕</span>
          <div>
            <h3>Bean & Brew AI Portal</h3>
            <span className="model-tag">Master Agent Router (Qwen 2.5 7B on Modal vLLM → Ollama)</span>
          </div>
        </div>

        <div className="user-profile-strip">
          <div className="agent-badge-pill">
            <span className="agent-indicator-dot"></span>
            <span>Master Operations Agent</span>
          </div>

          <div className="user-meta">
            <span className="user-name">{user.username}</span>
            <span className="role-pill">{user.role}</span>
            <span className="store-pill">Store {user.store_id}</span>
          </div>
          <button className="logout-btn" onClick={handleLogout}>Switch User</button>
        </div>
      </header>

      {/* Main chat layout */}
      <div className="chat-layout">
        <div className="chat-main">
          <div className="message-list">
            {messages.map(m => (
              <div key={m.id} className={`message-bubble ${m.role}`}>
                <div className="bubble-header">
                  <span className="author">
                    {m.role === 'user' ? user.username : (m.agent_used || 'Master Agent')}
                  </span>
                  <span className="time">{m.timestamp}</span>
                </div>
                <div className="bubble-content" style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>

                {m.recalled_memories && m.recalled_memories.length > 0 && (
                  <div className="memory-badge-strip">
                    🧠 Recalled Mem0 Fact: <em>"{m.recalled_memories[0]}"</em>
                  </div>
                )}

                {m.steps && m.steps.length > 0 && (
                  <div className="bubble-footer">
                    <button
                      className="audit-btn"
                      onClick={() => {
                        setInspectAudit({
                          steps: m.steps,
                          recalled: m.recalled_memories,
                          token: user.dynamic_token
                        })
                        setActiveTab('tools')
                      }}
                    >
                      🔍 Inspect Zero Trust Audit ({m.steps.length} Tool Calls)
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

          <form className="input-bar" onSubmit={(e) => { e.preventDefault(); sendQuery(input); }}>
            <input
              type="text"
              placeholder={`Ask Master Agent as ${user.role} (e.g. inventory, sales, roster)...`}
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>Send</button>
          </form>
        </div>

        {/* Audit Inspector Drawer */}
        <aside className="audit-drawer">
          <div className="drawer-header">
            <h4>Security & Memory Inspector</h4>
          </div>
          <div className="tab-buttons">
            <button className={activeTab === 'tools' ? 'tab-btn active' : 'tab-btn'} onClick={() => setActiveTab('tools')}>Tool Audit</button>
            <button className={activeTab === 'memory' ? 'tab-btn active' : 'tab-btn'} onClick={() => setActiveTab('memory')}>SQL Memory ({facts.length})</button>
            <button className={activeTab === 'token' ? 'tab-btn active' : 'tab-btn'} onClick={() => setActiveTab('token')}>OAuth Token</button>
          </div>

          <div className="drawer-body">
            {activeTab === 'tools' && (
              <div>
                <p className="drawer-desc">Real-time WXO execution traces & tool parameters:</p>
                <pre className="audit-json">
                  {JSON.stringify(inspectAudit?.steps || "Click 'Inspect Zero Trust Audit' on any assistant message to view execution traces.", null, 2)}
                </pre>
              </div>
            )}

            {activeTab === 'memory' && (
              <div className="memory-tab-content">
                <div className="memory-tab-header">
                  <div className="sqlite-badge">
                    <span className="sqlite-dot"></span>
                    <span>SQLite 3 (data/semantic_memory.db)</span>
                  </div>
                  <div className="memory-controls">
                    <button className="small-action-btn" onClick={refreshMemories} title="Refresh Table">
                      🔄 Refresh
                    </button>
                    {facts.length > 0 && (
                      <button className="small-action-btn danger" onClick={handleClearMemory} title="Clear All Rows">
                        🗑️ Clear
                      </button>
                    )}
                  </div>
                </div>

                {memoryActionMsg && <div className="action-feedback-pill">{memoryActionMsg}</div>}

                <p className="drawer-desc">
                  Structured EAV table with atomic <code>ON CONFLICT DO UPDATE</code> (User: <strong>{user.username}</strong>):
                </p>

                {facts.length === 0 ? (
                  <div className="empty-memory-box">
                    <p className="empty-note">No rows in SQLite database yet.</p>
                    <p className="empty-sub">Say <em>"Remember that I prefer brewing light roasts with oat milk"</em> or test manual upsert below!</p>
                  </div>
                ) : (
                  <div className="table-responsive">
                    <table className="sqlite-eav-table">
                      <thead>
                        <tr>
                          <th>Entity</th>
                          <th>Attribute</th>
                          <th>Value</th>
                          <th>Conf.</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {facts.map((f, i) => (
                          <tr key={i}>
                            <td><strong className="entity-cell">{f.entity}</strong></td>
                            <td className="attr-cell">{f.attribute}</td>
                            <td className="val-cell">{f.value}</td>
                            <td className="conf-cell">{Math.round(f.confidence * 100)}%</td>
                            <td>
                              <button
                                className="delete-row-btn"
                                onClick={() => handleDeleteFact(f)}
                                title="Delete row"
                              >
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Live SQL Conflict / Upsert Tester */}
                <div className="upsert-test-card">
                  <h5>⚡ Test Atomic SQL Conflict Resolution</h5>
                  <p className="card-subtext">
                    Insert or update an attribute (e.g. entity: <code>milk</code> $\to$ value: <code>almond milk</code>). SQLite replaces the value in-place without duplicate rows:
                  </p>
                  <form onSubmit={handleManualUpsert} className="upsert-inline-form">
                    <input
                      type="text"
                      placeholder="Entity (e.g. milk)"
                      value={newEntity}
                      onChange={e => setNewEntity(e.target.value)}
                      className="mini-input"
                    />
                    <input
                      type="text"
                      placeholder="Attr (e.g. type)"
                      value={newAttr}
                      onChange={e => setNewAttr(e.target.value)}
                      className="mini-input"
                    />
                    <input
                      type="text"
                      placeholder="Value (e.g. oat milk)"
                      value={newVal}
                      onChange={e => setNewVal(e.target.value)}
                      className="mini-input"
                    />
                    <button type="submit" className="mini-submit-btn">UPSERT</button>
                  </form>
                </div>

                {/* SQL Schema Transparency Box */}
                <details className="sql-schema-details">
                  <summary>View SQL Table Schema & Query</summary>
                  <pre className="schema-sql">
{`CREATE TABLE semantic_memory (
  user_id TEXT NOT NULL,
  category TEXT NOT NULL,
  entity TEXT NOT NULL,
  attribute TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL DEFAULT 1.0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, category, entity, attribute)
);

-- Atomic Conflict Target (No Duplicates)
INSERT INTO semantic_memory (user_id, category, entity, attribute, value)
VALUES ('${user.username}', 'preference', 'milk', 'type', 'almond milk')
ON CONFLICT (user_id, category, entity, attribute)
DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP;`}
                  </pre>
                </details>
              </div>
            )}

            {activeTab === 'token' && (
              <div>
                <p className="drawer-desc">Ephemeral Snowflake OAuth Token issued by Broker:</p>
                <div className="token-card">
                  <div><strong>Token:</strong> <code>{user.dynamic_token?.token}</code></div>
                  <div><strong>Snowflake User:</strong> {user.dynamic_token?.snowflake_user}</div>
                  <div><strong>Snowflake Role:</strong> {user.dynamic_token?.snowflake_role}</div>
                  <div><strong>Scopes:</strong> {user.dynamic_token?.scopes?.join(', ')}</div>
                  <div><strong>Expires In:</strong> 300s (Auto-revoked)</div>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
