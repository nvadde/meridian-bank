import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError, request } from './api/client'
import DashboardPage from './pages/DashboardPage'
import MiraChat from './chatbot/MiraChat'
import ObservabilityPage from './pages/ObservabilityPage'

const TOKEN_KEY = 'meridian.session'

function loginMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'ACCOUNT_LOCKED') return 'Your account is locked. Try again in 15 minutes or contact an administrator.'
    if (error.code === 'INVALID_CREDENTIALS') {
      const remaining = error.attemptsRemaining
      const attempts = remaining === 1 ? 'attempt' : 'attempts'
      return 'Email or password is incorrect.' + (remaining == null ? '' : ' ' + remaining + ' ' + attempts + ' remaining.')
    }
    if (error.code === 'INVALID_REQUEST') return 'Enter a valid email and password.'
  }
  return 'We couldn’t sign you in. Try again.'
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY))
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [showObservability, setShowObservability] = useState(() => window.location.hash === '#observability')

  useEffect(() => {
    const navigate = () => setShowObservability(window.location.hash === '#observability')
    window.addEventListener('hashchange', navigate)
    return () => window.removeEventListener('hashchange', navigate)
  }, [])

  const expire = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setError('Your session ended. Sign in again to continue.')
  }, [])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const fields = new FormData(form)
    const password = form.elements.namedItem('password') as HTMLInputElement
    setPending(true)
    setError('')
    try {
      const result = await request<{ session_token: string }>('/login', {
        body: { email: fields.get('email'), password: fields.get('password') },
      })
      sessionStorage.setItem(TOKEN_KEY, result.session_token)
      setToken(result.session_token)
    } catch (error) {
      setError(loginMessage(error))
      password.focus()
    } finally {
      password.value = ''
      setPending(false)
    }
  }

  async function signOut() {
    if (!token) return
    try {
      await request<void>('/logout', { token, method: 'POST' })
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error
    }
    sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setError('')
  }

  return <>
    <header className="site-header">
      <div className="header-inner">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>Meridian <span>Trust Bank</span></div>
        </div>
        {token && <nav className="header-nav" aria-label="Main navigation">
          <a className="header-link" href="#dashboard" aria-current={showObservability ? undefined : 'page'}>Overview</a>
          <a className="header-link" href="#observability" aria-current={showObservability ? 'page' : undefined}>Observability</a>
        </nav>}
      </div>
    </header>
    {token ? (
      showObservability
        ? <ObservabilityPage key={token} token={token} onExpire={expire} onSignOut={signOut} />
        : <DashboardPage key={token} token={token} onExpire={expire} onSignOut={signOut} />
    ) : (
      <main className="signin">
        <section className="panel signin-panel">
          <h1>Sign in</h1>
          <form onSubmit={signIn}>
            <label>Email<input id="meridian-sign-in-email" name="email" type="email" placeholder="you@example.com" autoComplete="username" maxLength={150} required /></label>
            <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
            {error && <p className="message error" role="alert">{error}</p>}
            <button className="primary" type="submit" disabled={pending}>{pending ? 'Signing in…' : 'Sign in'}</button>
          </form>
        </section>
      </main>
    )}
    <MiraChat token={token} />
  </>
}
