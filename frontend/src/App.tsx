import { useState, useEffect, useRef } from 'react'
import './App.css'

interface AgentMeta {
  name: string
  title: string
  id: string
}

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
  accessible_agents: AgentMeta[]
  dynamic_token: DynamicToken
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

export default function App() {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<string>('bb_assistant')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [inspectAudit, setInspectAudit] = useState<any | null>(null)
  const [activeTab, setActiveTab] = useState<'tools' | 'memory' | 'token'>('tools')
  const [longTermMemories, setLongTermMemories] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) {
          setUser(data)
          if (data.accessible_agents?.length > 0) {
            setSelectedAgent(data.accessible_agents[0].name)
          }
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
        setLongTermMemories(d.memories || [])
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
        setSelectedAgent(u.accessible_agents[0]?.name || 'bb_assistant')
        setMessages([
          {
            id: 'welcome',
            role: 'assistant',
            content: `Welcome ${u.username}! Signed in as **${u.role}** at store **${u.store_id}** (${u.region}).\n\nAuthorized Agents: ${u.accessible_agents.map((a: any) => a.title).join(', ')}.\nEphemeral Snowflake OAuth Token: \`${u.dynamic_token?.token?.slice(0, 16)}...\``,
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
    setLongTermMemories([])
  }

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading || !user) return

    const userText = input.trim()
    setInput('')
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: userText,
      timestamp: new Date().toLocaleTimeString()
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText, agent_name: selectedAgent, thread_id: threadId }),
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
            watsonx Orchestrate with Agent RBAC, Mem0 Long-Term Memory & Snowflake Ephemeral OAuth Tokens.
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

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <span className="logo-icon">☕</span>
          <div>
            <h3>Bean & Brew AI Portal</h3>
            <span className="model-tag">Model: Qwen 2.5 7B (Modal vLLM → Ollama fallback)</span>
          </div>
        </div>

        <div className="user-profile-strip">
          <div className="agent-selector-wrapper">
            <label className="agent-label">Target Agent:</label>
            <select
              className="agent-select"
              value={selectedAgent}
              onChange={e => setSelectedAgent(e.target.value)}
            >
              {user.accessible_agents.map(a => (
                <option key={a.name} value={a.name}>{a.title}</option>
              ))}
            </select>
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
                    {m.role === 'user' ? user.username : (m.agent_used || 'Bean & Brew Assistant')}
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
                <span className="dots">☕ {selectedAgent} is executing with Snowflake OAuth token...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form className="input-bar" onSubmit={sendMessage}>
            <input
              type="text"
              placeholder={`Ask ${selectedAgent} as ${user.role}...`}
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
            <button className={activeTab === 'memory' ? 'tab-btn active' : 'tab-btn'} onClick={() => setActiveTab('memory')}>Mem0 ({longTermMemories.length})</button>
            <button className={activeTab === 'token' ? 'tab-btn active' : 'tab-btn'} onClick={() => setActiveTab('token')}>OAuth Token</button>
          </div>

          <div className="drawer-body">
            {activeTab === 'tools' && (
              <div>
                <p className="drawer-desc">Real-time WXO execution traces with context variables:</p>
                <pre className="audit-json">
                  {JSON.stringify(inspectAudit?.steps || "Click 'Inspect Zero Trust Audit' on any assistant message to view execution traces.", null, 2)}
                </pre>
              </div>
            )}

            {activeTab === 'memory' && (
              <div>
                <p className="drawer-desc">Persistent Semantic Facts in Mem0 for <strong>{user.username}</strong>:</p>
                {longTermMemories.length === 0 ? (
                  <p className="empty-note">No memories stored yet. Mention a syrup preference or schedule in chat!</p>
                ) : (
                  <ul className="memory-list">
                    {longTermMemories.map((mem, i) => (
                      <li key={i} className="memory-item">🧠 {mem}</li>
                    ))}
                  </ul>
                )}
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
