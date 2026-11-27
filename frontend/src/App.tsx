import { useState, useEffect, useRef } from 'react'
import type { ComponentProps } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Accordion,
  AccordionItem,
  Button,
  ClickableTile,
  CodeSnippet,
  Column,
  Content,
  Grid,
  Header,
  HeaderGlobalBar,
  HeaderName,
  IconButton,
  InlineLoading,
  InlineNotification,
  Layer,
  StructuredListBody,
  StructuredListCell,
  StructuredListRow,
  StructuredListWrapper,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tag,
  TextInput,
  Theme,
  Tile,
} from '@carbon/react'
import {
  Analytics,
  Close,
  Cafe,
  Finance,
  Logout,
  Report,
  Search,
  Send,
  TrashCan,
  UserAdmin,
  UserMultiple,
  ShoppingCatalog,
} from '@carbon/icons-react'
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
  tone?: 'error'
}

type TagType = 'red' | 'magenta' | 'purple' | 'blue' | 'cyan' | 'teal' | 'green' | 'gray' | 'cool-gray' | 'warm-gray' | 'high-contrast' | 'outline'

const DEMO_PERSONAS = [
  { username: 'maya', name: 'Maya Chen', role: 'barista', badge: 'Barista · Store S01', icon: Cafe, tag: 'warm-gray' as TagType,
    blurb: 'Checks stock at her own store. No access to employee data.' },
  { username: 'sam', name: 'Sam Rivera', role: 'store_manager', badge: 'Store manager · S01', icon: ShoppingCatalog, tag: 'blue' as TagType,
    blurb: 'Runs the S01 team and restocks. Sees the roster with salary and contacts masked.' },
  { username: 'priya', name: 'Priya Nair', role: 'regional_manager', badge: 'Regional manager · North', icon: Report, tag: 'teal' as TagType,
    blurb: 'Compares sales and inventory across the stores in her region.' },
  { username: 'felix', name: 'Felix Weber', role: 'finance_analyst', badge: 'Finance analyst · HQ', icon: Finance, tag: 'green' as TagType,
    blurb: 'Reads payroll and sales aggregates, never individual salaries.' },
  { username: 'hana', name: 'Hana Sato', role: 'hr_admin', badge: 'HR administrator · HQ', icon: UserAdmin, tag: 'purple' as TagType,
    blurb: 'Sees the full employee record, including salary and contacts.' },
]

const ROLE_TAG: Record<string, TagType> = Object.fromEntries(DEMO_PERSONAS.map(p => [p.role, p.tag]))

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

const PREFERENCE_PROMPTS = [
  { label: 'Switch to almond milk', prompt: 'I switched to almond milk, please use that.' },
  { label: 'Prefer oat milk', prompt: 'I prefer oat milk in my drinks.' },
  { label: 'Format as tables', prompt: 'Always format my responses in markdown tables.' },
  { label: 'Lookback 14 days', prompt: 'Default lookback window to 14 days.' },
]

const CHAT_REQUEST_TIMEOUT_MS = 120_000

// Render agent markdown tables with Carbon data-table styling.
const markdownComponents = {
  table: (props: ComponentProps<'table'>) => (
    <div className="bb-table-wrap">
      <table className="cds--data-table cds--data-table--sm" {...props} />
    </div>
  ),
}

export default function App() {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [inspectAudit, setInspectAudit] = useState<any | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [activeTab, setActiveTab] = useState(0)
  const [memories, setMemories] = useState<any[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inspectorHeadingRef = useRef<HTMLHeadingElement>(null)
  const traceHeadingRef = useRef<HTMLHeadingElement>(null)
  const inspectorTriggerRef = useRef<HTMLButtonElement | null>(null)

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
      const res = await fetch('/api/memory/clear', { method: 'POST', credentials: 'include' })
      if (res.ok) setMemories([])
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
    setLoginError('')
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
            content: `**Welcome, ${u.username}.**\n\nYou signed in through **Keycloak** as **${u.role}** (store **${u.store_id}**, region **${u.region}**).\n\nYou're talking to the **Bean & Brew Master Operations Agent**. It routes HR and finance questions to its collaborator agents (\`bb_hr_agent\`, \`bb_finance_agent\`) and remembers your preferences for this session.\n\n*Demo session marker: \`${u.dynamic_token?.token?.slice(0, 16)}...\` (valid for 300 s).*`,
            timestamp: new Date().toLocaleTimeString()
          }
        ])
        setThreadId(null)
      } else {
        const error = await res.json().catch(() => null)
        setLoginError(error?.detail || 'Sign-in failed. Check that Keycloak and the backend are running.')
      }
    } catch {
      setLoginError('Could not reach the backend. Check that it is running on port 8000.')
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
    setInspectorOpen(false)
    setMemories([])
  }

  const openInspector = (trigger: HTMLButtonElement | null, showTrace = false) => {
    inspectorTriggerRef.current = trigger
    setInspectorOpen(true)
    requestAnimationFrame(() => {
      const heading = showTrace ? traceHeadingRef.current : inspectorHeadingRef.current
      heading?.focus({ preventScroll: true })
      if (showTrace) heading?.scrollIntoView({ block: 'start' })
    })
  }

  const closeInspector = () => {
    setInspectorOpen(false)
    inspectorTriggerRef.current?.focus({ preventScroll: true })
  }

  const sendQuery = async (queryText: string) => {
    if (!queryText.trim() || loading || !user) return

    setInput('')
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: 'user',
      content: queryText,
      timestamp: new Date().toLocaleTimeString()
    }])
    setLoading(true)

    const addError = (content: string) => setMessages(prev => [...prev, {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content,
      tone: 'error',
      timestamp: new Date().toLocaleTimeString()
    }])

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: queryText, thread_id: threadId }),
        credentials: 'include',
        signal: AbortSignal.timeout(CHAT_REQUEST_TIMEOUT_MS)
      })
      if (res.ok) {
        const data = await res.json()
        setThreadId(data.thread_id)
        setMessages(prev => [...prev, {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.reply?.trim() ? data.reply : 'The agent finished without a reply. Try sending your message again.',
          steps: data.steps,
          agent_used: data.agent_used,
          timestamp: new Date().toLocaleTimeString()
        }])
        if (data.memories) setMemories(data.memories)
        setInspectAudit({
          steps: data.steps,
          agent_used: data.agent_used,
          thread_id: data.thread_id,
          token: data.dynamic_token
        })
      } else {
        const err = await res.json().catch(() => ({}))
        addError(err.detail || 'Access denied or execution error.')
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Unknown error'
      addError(error instanceof DOMException && error.name === 'TimeoutError'
        ? 'The agent is taking longer than expected. Try sending your message again.'
        : `Network error: ${detail}`)
    } finally {
      setLoading(false)
    }
  }

  /* ---------------------------------------------------------------- sign-in */

  if (!user) {
    return (
      <>
        <Theme theme="g100">
          <Header aria-label="Bean & Brew Operations AI">
            <HeaderName href="#" prefix="Bean & Brew">Operations AI</HeaderName>
          </Header>
        </Theme>
        <Theme theme="g10" className="bb-page">
          <Content className="bb-login">
            <Grid>
              <Column sm={4} md={8} lg={6} className="bb-login__intro">
                <p className="bb-eyebrow">IBM watsonx Orchestrate · Snowflake · Keycloak</p>
                <h1 className="bb-login__title">Governed AI agents for store operations</h1>
                <p className="bb-login__lead">
                  One assistant answers questions about inventory, sales and staff. What each person gets back
                  is decided by their identity and by Snowflake policies, not by the model.
                </p>
                <StructuredListWrapper isCondensed aria-label="How access is enforced" className="bb-login__layers">
                  <StructuredListBody>
                    {[
                      ['Keycloak', 'Signs the user in with role, store and region claims.'],
                      ['Orchestrate', 'Routes to tools and to HR and finance collaborator agents.'],
                      ['Snowflake', 'Row access and masking policies decide the rows and columns returned.'],
                    ].map(([k, v]) => (
                      <StructuredListRow key={k}>
                        <StructuredListCell noWrap className="bb-strong">{k}</StructuredListCell>
                        <StructuredListCell>{v}</StructuredListCell>
                      </StructuredListRow>
                    ))}
                  </StructuredListBody>
                </StructuredListWrapper>
              </Column>

              <Column sm={4} md={8} lg={10}>
                <h2 className="bb-section-title">Select an employee persona</h2>
                <p className="bb-helper">Sign in as one of five synthetic users to compare what each role can see.</p>

                {loginError && (
                  <InlineNotification
                    kind="error"
                    title="Sign-in failed"
                    subtitle={loginError}
                    lowContrast
                    hideCloseButton
                    role="alert"
                  />
                )}
                {loading && <InlineLoading description="Authenticating with Keycloak and starting a session..." />}

                <div className="bb-persona-grid">
                  {DEMO_PERSONAS.map(p => {
                    const Icon = p.icon
                    return (
                      <ClickableTile
                        key={p.username}
                        className="bb-persona"
                        onClick={() => handleLogin(p.username)}
                        disabled={loading}
                      >
                        <div className="bb-persona__top">
                          <Icon size={24} aria-hidden="true" />
                          <Tag type={p.tag} size="sm">{p.role}</Tag>
                        </div>
                        <h3 className="bb-persona__name">{p.name}</h3>
                        <p className="bb-persona__badge">{p.badge}</p>
                        <p className="bb-persona__blurb">{p.blurb}</p>
                      </ClickableTile>
                    )
                  })}
                </div>
              </Column>
            </Grid>
          </Content>
        </Theme>
      </>
    )
  }

  /* ------------------------------------------------------------- workspace */

  const suggestions = ROLE_SUGGESTIONS[user.role] || []

  return (
    <>
      <Theme theme="g100">
        <Header aria-label="Bean & Brew Operations AI">
          <HeaderName href="#" prefix="Bean & Brew">Operations AI</HeaderName>
          <HeaderGlobalBar className="bb-header-bar">
            <span className="bb-header-user">{user.username}</span>
            <Tag type={ROLE_TAG[user.role] || 'gray'} size="sm">{user.role}</Tag>
            <Tag type="outline" size="sm">Store {user.store_id}</Tag>
            <Button
              kind="ghost"
              size="sm"
              className="bb-header-btn"
              aria-controls="agent-inspector"
              aria-expanded={inspectorOpen}
              renderIcon={Analytics}
              onClick={(e) => inspectorOpen ? closeInspector() : openInspector(e.currentTarget as HTMLButtonElement)}
            >
              Inspector
            </Button>
            <Button kind="ghost" size="sm" className="bb-header-btn" renderIcon={Logout} onClick={handleLogout}>
              Switch User
            </Button>
          </HeaderGlobalBar>
        </Header>
      </Theme>

      <Theme theme="g10" className="bb-page">
        <div className={inspectorOpen ? 'bb-workspace bb-workspace--inspector' : 'bb-workspace'}>
          <main className="bb-chat" aria-label="Conversation">
            <div className="bb-chat__agent">
              <UserMultiple size={16} aria-hidden="true" />
              <span>Master Operations Agent</span>
              <Tag type="green" size="sm">Live</Tag>
            </div>

            <div className="bb-messages" aria-live="polite">
              {messages.map(m => (
                <div key={m.id} className={`bb-message bb-message--${m.role}`}>
                  <Layer>
                    <Tile className={m.tone === 'error' ? 'bb-bubble bb-bubble--error' : 'bb-bubble'}>
                      <div className="bb-bubble__meta">
                        <span className="bb-bubble__author">
                          {m.role === 'user' ? user.username : (m.agent_used || 'Master Operations Agent')}
                        </span>
                        <span className="bb-bubble__time">{m.timestamp}</span>
                      </div>
                      <div className="bb-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {m.content}
                        </ReactMarkdown>
                      </div>
                      {m.steps && m.steps.length > 0 && (
                        <Button
                          kind="ghost"
                          size="sm"
                          renderIcon={Search}
                          className="bb-bubble__audit"
                          aria-controls="agent-inspector"
                          onClick={(event) => {
                            setInspectAudit({
                              steps: m.steps,
                              agent_used: m.agent_used,
                              thread_id: threadId,
                              token: user.dynamic_token
                            })
                            setActiveTab(0)
                            openInspector(event.currentTarget as HTMLButtonElement, true)
                          }}
                        >
                          Inspect Agent Routing & Tool Audit
                        </Button>
                      )}
                    </Tile>
                  </Layer>
                </div>
              ))}

              {loading && (
                <div className="bb-message bb-message--assistant" role="status">
                  <InlineLoading description="Master Agent reasoning & evaluating Zero Trust policies..." />
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="bb-composer">
              <div className="bb-suggestions" role="group" aria-label="Quick actions">
                <span className="bb-suggestions__label">Quick actions</span>
                {suggestions.map(s => (
                  <Button key={s} kind="tertiary" size="sm" onClick={() => sendQuery(s)} disabled={loading}>
                    {s}
                  </Button>
                ))}
              </div>
              <form className="bb-input" onSubmit={(e) => { e.preventDefault(); sendQuery(input) }}>
                <TextInput
                  id="bb-chat-input"
                  labelText="Message"
                  hideLabel
                  size="lg"
                  placeholder={`Ask as ${user.role}: inventory, team roster, sales...`}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  disabled={loading}
                />
                <Button type="submit" size="lg" renderIcon={Send} disabled={loading || !input.trim()}>
                  Send
                </Button>
              </form>
            </div>
          </main>

          <aside
            id="agent-inspector"
            className="bb-inspector"
            aria-labelledby="agent-inspector-title"
            hidden={!inspectorOpen}
          >
            <div className="bb-inspector__header">
              <h2 id="agent-inspector-title" ref={inspectorHeadingRef} tabIndex={-1}>
                Agent & Security Inspector
              </h2>
              <IconButton kind="ghost" size="sm" label="Close" align="left" onClick={closeInspector}>
                <Close />
              </IconButton>
            </div>

            <Tabs selectedIndex={activeTab} onChange={({ selectedIndex }) => setActiveTab(selectedIndex)}>
              <TabList aria-label="Inspector views" contained fullWidth>
                <Tab>Execution Audit</Tab>
                <Tab>Identity & Token</Tab>
                <Tab>Memory{memories.length > 0 ? ` (${memories.length})` : ''}</Tab>
              </TabList>
              <TabPanels>
                {/* Execution audit */}
                <TabPanel className="bb-panel">
                  <Tile className="bb-card">
                    <p className="bb-label">Active orchestrator</p>
                    <p className="bb-strong">bb_master_agent</p>
                    <p className="bb-helper">
                      Session thread: <code>{threadId || 'starts on the first message'}</code>
                    </p>
                  </Tile>

                  <Tile className="bb-card">
                    <p className="bb-label">Collaborators and tools</p>
                    <StructuredListWrapper isCondensed aria-label="Collaborators">
                      <StructuredListBody>
                        <StructuredListRow>
                          <StructuredListCell noWrap><Tag type="purple" size="sm">bb_hr_agent</Tag></StructuredListCell>
                          <StructuredListCell>Rosters and personnel directory. Salaries masked for store managers.</StructuredListCell>
                        </StructuredListRow>
                        <StructuredListRow>
                          <StructuredListCell noWrap><Tag type="green" size="sm">bb_finance_agent</Tag></StructuredListCell>
                          <StructuredListCell>Sales aggregates and salary statistics. Finance analysts only.</StructuredListCell>
                        </StructuredListRow>
                        <StructuredListRow>
                          <StructuredListCell noWrap><Tag type="blue" size="sm">Snowflake tools</Tag></StructuredListCell>
                          <StructuredListCell><code>bb_get_inventory</code>, <code>bb_restock_inventory</code> over RSA key-pair auth.</StructuredListCell>
                        </StructuredListRow>
                      </StructuredListBody>
                    </StructuredListWrapper>
                  </Tile>

                  <h3 className="bb-section-title" ref={traceHeadingRef} tabIndex={-1}>Tool & Routing Traces</h3>
                  {inspectAudit?.steps && inspectAudit.steps.length > 0 ? (
                    <>
                      <ol className="bb-steps">
                        {inspectAudit.steps.map((st: any, idx: number) => (
                          <li key={idx} className="bb-step">
                            <div className="bb-step__top">
                              <Tag type="cool-gray" size="sm">{st.node || 'tool_call'}</Tag>
                              <Tag type={st.status === 'error' ? 'red' : 'green'} size="sm">{st.status || 'executed'}</Tag>
                            </div>
                            {st.tool && (
                              <p className="bb-step__row">
                                Tool <strong>{st.tool}</strong>
                                {st.user && <> · user <code>{st.user}</code></>}
                              </p>
                            )}
                            {st.auth && <p className="bb-helper">Auth: {st.auth}</p>}
                          </li>
                        ))}
                      </ol>
                      <Accordion size="sm">
                        <AccordionItem title="View Raw Trace JSON">
                          <CodeSnippet type="multi" feedback="Copied" maxCollapsedNumberOfRows={20} wrapText>
                            {JSON.stringify(inspectAudit.steps, null, 2)}
                          </CodeSnippet>
                        </AccordionItem>
                      </Accordion>
                    </>
                  ) : (
                    <p className="bb-helper">
                      Send a message, or select Inspect Agent Routing & Tool Audit under a response, to see its trace.
                    </p>
                  )}
                </TabPanel>

                {/* Identity */}
                <TabPanel className="bb-panel">
                  <Tile className="bb-card">
                    <p className="bb-label">Verified context variables</p>
                    <StructuredListWrapper isCondensed aria-label="Context variables">
                      <StructuredListBody>
                        {[
                          ['bb_role', user.role],
                          ['bb_store_id', `Store ${user.store_id}`],
                          ['bb_region', user.region],
                          ['bb_email', user.email],
                        ].map(([k, v]) => (
                          <StructuredListRow key={k}>
                            <StructuredListCell noWrap><code>{k}</code></StructuredListCell>
                            <StructuredListCell className="bb-strong">{v}</StructuredListCell>
                          </StructuredListRow>
                        ))}
                      </StructuredListBody>
                    </StructuredListWrapper>
                  </Tile>

                  <Tile className="bb-card">
                    <p className="bb-label">Demo session marker</p>
                    <StructuredListWrapper isCondensed aria-label="Session marker">
                      <StructuredListBody>
                        <StructuredListRow>
                          <StructuredListCell noWrap>Snowflake user</StructuredListCell>
                          <StructuredListCell><code>{user.dynamic_token?.snowflake_user}</code></StructuredListCell>
                        </StructuredListRow>
                        <StructuredListRow>
                          <StructuredListCell noWrap>Snowflake role</StructuredListCell>
                          <StructuredListCell><code>{user.dynamic_token?.snowflake_role}</code></StructuredListCell>
                        </StructuredListRow>
                        <StructuredListRow>
                          <StructuredListCell noWrap>Granted scopes</StructuredListCell>
                          <StructuredListCell>{user.dynamic_token?.scopes?.join(', ')}</StructuredListCell>
                        </StructuredListRow>
                        <StructuredListRow>
                          <StructuredListCell noWrap>TTL</StructuredListCell>
                          <StructuredListCell><Tag type="cyan" size="sm">300 s</Tag></StructuredListCell>
                        </StructuredListRow>
                      </StructuredListBody>
                    </StructuredListWrapper>
                    <CodeSnippet type="single" feedback="Copied">{user.dynamic_token?.token || ''}</CodeSnippet>
                  </Tile>
                </TabPanel>

                {/* Memory */}
                <TabPanel className="bb-panel">
                  <Tile className="bb-card">
                    <p className="bb-label">Learned preferences</p>
                    <p className="bb-helper">
                      Each preference has one slot. A new value replaces the old one, so there are no duplicates.
                    </p>
                    {memories.length > 0 ? (
                      <ul className="bb-memories">
                        {memories.map((m: any, idx: number) => (
                          <li key={idx} className="bb-memory">
                            <div>
                              <div className="bb-memory__top">
                                <Tag type="teal" size="sm">{m.category}</Tag>
                                <span className="bb-helper">{m.updated_at ? m.updated_at.split(' ')[1] : 'active'}</span>
                              </div>
                              <p>
                                <strong>{m.entity}</strong> ({m.attribute}): <span className="bb-memory__value">{m.value}</span>
                              </p>
                            </div>
                            <IconButton
                              kind="ghost"
                              size="sm"
                              label="Delete preference"
                              align="left"
                              onClick={() => handleDeleteMemory(m.entity)}
                            >
                              <TrashCan />
                            </IconButton>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="bb-helper">No preferences yet. Try "I prefer oat milk" or "Format in tables".</p>
                    )}
                    {memories.length > 0 && (
                      <Button kind="danger--tertiary" size="sm" renderIcon={TrashCan} onClick={handleClearMemory}>
                        Clear all preferences
                      </Button>
                    )}
                  </Tile>

                  <Tile className="bb-card">
                    <p className="bb-label">Try a preference change</p>
                    <p className="bb-helper">Send one of these to watch the stored value update.</p>
                    <div className="bb-suggestions">
                      {PREFERENCE_PROMPTS.map(p => (
                        <Button key={p.label} kind="tertiary" size="sm" disabled={loading} onClick={() => sendQuery(p.prompt)}>
                          {p.label}
                        </Button>
                      ))}
                    </div>
                  </Tile>
                </TabPanel>
              </TabPanels>
            </Tabs>
          </aside>
        </div>
      </Theme>
    </>
  )
}
