import { useEffect, useState } from 'react'
import { ApiError, request } from '../api/client'
import './ObservabilityPage.css'

interface Event {
  timestamp: string
  user_id: string | null
  session_id: string | null
  trace_id: string
  description: string | null
}

interface UserUsage {
  user_id: string | null
  calls: number
  total_tokens: number
  estimated_cost_usd: string
}

interface Snapshot {
  resources: { cpu: number; memory: number; disk: number }
  usage: {
    calls: number
    total_tokens: number
    estimated_cost_usd: string
    unmetered_calls: number
    users: UserUsage[]
  }
  prompts: Event[]
  tools: Event[]
}

const count = new Intl.NumberFormat('en-US')
const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 8 })
const timestamp = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
})

function Activity({ title, rows }: { title: string; rows: Event[] }) {
  return <section className="panel obs-activity">
    <h2>{title}</h2>
    {rows.length ? <ol>
      {rows.map((row, index) => (
        <li key={row.trace_id + ':' + index}>
          <div className="obs-event-heading">
            <strong>{row.description ?? 'Event recorded'}</strong>
            <time dateTime={row.timestamp}>{timestamp.format(new Date(row.timestamp))}</time>
          </div>
          <p>{row.user_id ?? 'Unauthenticated'}{row.session_id && ' · Session ' + row.session_id}</p>
        </li>
      ))}
    </ol> : <p className="muted">No events recorded yet.</p>}
  </section>
}

interface Props {
  token: string
  onExpire: () => void
  onSignOut: () => Promise<void>
}

export default function ObservabilityPage({ token, onExpire, onSignOut }: Props) {
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [version, setVersion] = useState(0)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'denied' | 'error'>('loading')
  const [signingOut, setSigningOut] = useState(false)
  const [signOutError, setSignOutError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading')
    request<Snapshot>('/admin/observability?day=' + encodeURIComponent(day), { token, signal: controller.signal })
      .then(data => {
        if (!controller.signal.aborted) {
          setSnapshot(data)
          setStatus('ready')
        }
      }).catch(error => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) onExpire()
        else {
          setSnapshot(null)
          setStatus(error instanceof ApiError && error.status === 403 ? 'denied' : 'error')
        }
      })
    return () => controller.abort()
  }, [day, version, token, onExpire])

  async function signOut() {
    setSigningOut(true)
    setSignOutError(false)
    try {
      await onSignOut()
    } catch {
      setSigningOut(false)
      setSignOutError(true)
    }
  }

  return <main className="dashboard observability" id="observability">
    <div className="page-title obs-page-title">
      <h1>Observability</h1>
      <div className="obs-actions">
        {status !== 'denied' && <button className="secondary" type="button" onClick={() => setVersion(value => value + 1)}
          disabled={status === 'loading'}>Refresh</button>}
        <button className="secondary" type="button" onClick={signOut} disabled={signingOut}>
          {signingOut ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
    </div>
    {signOutError && <p className="error message" role="alert">We couldn’t sign you out. Try again.</p>}
    {status === 'loading' && <p className="muted" role="status">Loading observability data…</p>}
    {status === 'denied' && <p className="error message" role="alert">Observability is available to administrators.</p>}
    {status === 'error' && <p className="error message" role="alert">We couldn’t load observability data. Try refreshing.</p>}
    {status === 'ready' && snapshot && <>
      <section aria-labelledby="obs-resources">
        <h2 id="obs-resources">Server utilization</h2>
        <div className="obs-cards">
          {([
            ['CPU', snapshot.resources.cpu], ['Memory', snapshot.resources.memory], ['Disk', snapshot.resources.disk],
          ] as const).map(([label, value]) => (
            <article className="panel obs-stat" key={label}>
              <h3>{label}</h3>
              <strong>{value.toFixed(1)}%</strong>
              <meter min={0} max={100} value={value} aria-label={label + ' utilization'} />
            </article>
          ))}
        </div>
      </section>
      <section className="panel obs-usage" aria-labelledby="obs-usage">
        <div className="obs-usage-heading">
          <h2 id="obs-usage">LLM usage</h2>
          <label>UTC day<input type="date" value={day} onChange={event => {
            if (event.target.value) setDay(event.target.value)
          }} /></label>
        </div>
        <dl className="obs-cards obs-totals">
          <div><dt>LLM calls</dt><dd>{count.format(snapshot.usage.calls)}</dd></div>
          <div><dt>Total tokens</dt><dd>{count.format(snapshot.usage.total_tokens)}</dd></div>
          <div><dt>Estimated cost</dt><dd>{dollars.format(Number(snapshot.usage.estimated_cost_usd))}</dd></div>
        </dl>
        {snapshot.usage.unmetered_calls > 0 &&
          <p className="muted">{count.format(snapshot.usage.unmetered_calls)} calls have incomplete usage data.</p>}
        {snapshot.usage.users.length > 0 && <div className="obs-table-wrap">
          <table>
            <thead><tr><th scope="col">User ID</th><th scope="col">Calls</th><th scope="col">Tokens</th><th scope="col">Est. cost</th></tr></thead>
            <tbody>{snapshot.usage.users.map(user => <tr key={user.user_id ?? 'anonymous'}>
              <th scope="row">{user.user_id ?? 'Unauthenticated'}</th>
              <td>{count.format(user.calls)}</td><td>{count.format(user.total_tokens)}</td>
              <td>{dollars.format(Number(user.estimated_cost_usd))}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      </section>
      <div className="obs-events">
        <Activity title="Last 20 prompts" rows={snapshot.prompts} />
        <Activity title="Last 20 tool calls" rows={snapshot.tools} />
      </div>
    </>}
  </main>
}
