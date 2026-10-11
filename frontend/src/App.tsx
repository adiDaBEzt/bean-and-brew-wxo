import { useState, useEffect, useRef } from 'react'
import './App.css'

interface UserProfile {
  username: string
  email: string
  role: string
  store_id: string
  region: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  steps?: any[]
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
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [inspectSteps, setInspectSteps] = useState<any[] | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) setUser(data)
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
        setMessages([
          {
            id: 'welcome',
            role: 'assistant',
            content: `Welcome ${u.username}! You are signed in as **${u.role}** (${u.email}) at store **${u.store_id}** (${u.region} region). Ask me about inventory, sales, or your team!`,
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
        body: JSON.stringify({ message: userText, thread_id: threadId }),
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
          timestamp: new Date().toLocaleTimeString()
        }
        setMessages(prev => [...prev, botMsg])
      } else {
        const err = await res.json()
        setMessages(prev => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: `⚠️ Error: ${err.detail || 'Failed to communicate with WXO Agent'}`,
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
          <h2>Zero Trust AI Operations Assistant</h2>
          <p className="subtitle">
            Demonstrating watsonx Orchestrate with Self-Hosted Qwen Models, Snowflake Row-Level RBAC & Keycloak OIDC Authentication.
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
          {loading && <p className="status-note">Authenticating via Keycloak & minting session...</p>}
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
          <div className="user-meta">
            <span className="user-name">{user.username}</span>
            <span className="role-pill">{user.role}</span>
            <span className="store-pill">Store {user.store_id} ({user.region})</span>
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
                  <span className="author">{m.role === 'user' ? user.username : 'Bean & Brew Assistant'}</span>
                  <span className="time">{m.timestamp}</span>
                </div>
                <div className="bubble-content" style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                {m.steps && m.steps.length > 0 && (
                  <div className="bubble-footer">
                    <button
                      className="audit-btn"
                      onClick={() => setInspectSteps(m.steps || null)}
                    >
                      🔍 Inspect RBAC Tool Audit ({m.steps.length} calls)
                    </button>
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="message-bubble assistant loading-indicator">
                <span className="dots">☕ Qwen is executing tools in Snowflake...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form className="input-bar" onSubmit={sendMessage}>
            <input
              type="text"
              placeholder={`Ask as ${user.role} (e.g., 'Check store inventory', 'Show sales', 'List employees')...`}
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>Send</button>
          </form>
        </div>

        {/* Audit Inspector Drawer */}
        {inspectSteps && (
          <aside className="audit-drawer">
            <div className="drawer-header">
              <h4>Security & Tool Call Audit Trace</h4>
              <button className="close-btn" onClick={() => setInspectSteps(null)}>✕</button>
            </div>
            <div className="drawer-body">
              <p className="drawer-desc">
                Proof of Zero Trust: Shows context variables passed from JWT session and tool execution against Snowflake.
              </p>
              <pre className="audit-json">
                {JSON.stringify(inspectSteps, null, 2)}
              </pre>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
