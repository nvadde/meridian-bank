import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { getMiraSession, sendMiraMessage, type MiraReply } from './coordinator_client'
import './MiraChat.css'

const QUICK_REPLIES = [
  { label: 'Check balance', message: 'What’s my balance?' },
  { label: 'Last transactions', message: 'Show last 5 transactions' },
  { label: 'Change address', message: 'Change my address' },
  { label: 'Cheque book', message: 'Request a cheque book', draftOnly: true },
] as const

type Message = { id: number; text: string; reply?: MiraReply }
type Identity =
  | { status: 'loading' }
  | { status: 'ready'; displayName: string }
  | { status: 'expired' | 'denied' | 'error' }

function ChatPanel({ token, open, close }: { token: string | null; open: boolean; close: () => void }) {
  const [identity, setIdentity] = useState<Identity>({ status: 'loading' })
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const composer = useRef<HTMLTextAreaElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const inFlight = useRef<AbortController | null>(null)
  const messageId = useRef(0)

  useEffect(() => {
    if (!open || !token) return
    const controller = new AbortController()
    setIdentity({ status: 'loading' })
    getMiraSession(token, controller.signal).then(result => {
      if (!controller.signal.aborted) setIdentity({ status: 'ready', displayName: result.display_name })
    }).catch(error => {
      if (controller.signal.aborted) return
      const status = error instanceof ApiError ? error.status : 0
      setIdentity({ status: status === 401 ? 'expired' : status === 403 ? 'denied' : 'error' })
    })
    return () => controller.abort()
  }, [open, retry, token])

  useEffect(() => {
    if (open) heading.current?.focus()
  }, [open])

  useEffect(() => {
    if (open && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }, [messages, open, pending])

  useEffect(() => () => inFlight.current?.abort(), [])

  async function send(message: string) {
    const text = message.trim()
    if (!token || identity.status !== 'ready' || !text || inFlight.current) return

    const controller = new AbortController()
    inFlight.current = controller
    setPending(true)
    setDraft('')
    setError('')
    const id = ++messageId.current
    setMessages(previous => [...previous, { id, text }])
    try {
      const reply = await sendMiraMessage(token, text, controller.signal)
      if (!controller.signal.aborted) {
        const replyId = ++messageId.current
        setMessages(previous => [...previous, { id: replyId, text: reply.text, reply }])
      }
    } catch (error) {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) {
        setMessages([])
        setIdentity({ status: 'expired' })
      } else {
        setError(error instanceof ApiError && error.status === 403
          ? 'Mira can only help with your own banking information.'
          : 'Mira couldn’t respond. If you sent a service request, check its status before sending it again.')
      }
    } finally {
      inFlight.current = null
      if (!controller.signal.aborted) setPending(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send(draft)
  }

  const ready = token !== null && identity.status === 'ready'
  return (
    <section className="mira-window" id="mira-chat-panel" hidden={!open} role="dialog"
      aria-labelledby="mira-chat-title" onKeyDown={event => {
        if (event.key === 'Escape') {
          event.stopPropagation()
          close()
        }
      }}>
      <header className="mira-header">
        <div className="mira-avatar" aria-hidden="true">M</div>
        <div className="mira-heading">
          <h2 id="mira-chat-title" ref={heading} tabIndex={-1}>Mira</h2>
          {ready && <p>Signed in as {identity.displayName}</p>}
        </div>
        <button className="mira-close" type="button" aria-label="Close Mira chat" onClick={close}>×</button>
      </header>

      {ready ? <>
        <div className="mira-transcript" role="log" aria-label="Conversation with Mira" ref={transcript}>
          <div className="mira-bubble mira-assistant">How can I help with your banking today?</div>
          {messages.map(message => (
            <div key={message.id} className={message.reply ? 'mira-turn' : 'mira-turn mira-user'}>
              <div className={message.reply ? 'mira-bubble mira-assistant' : 'mira-bubble'}>{message.text}</div>
              {message.reply && <div className="mira-agent" title={message.reply.tools_used.join(', ') || undefined}>
                {message.reply.agent_used}
              </div>}
            </div>
          ))}
          {pending && <p className="mira-wait">Mira is working on your request…</p>}
        </div>
        <div className="mira-controls">
          {error && <p className="mira-error" role="alert">{error}</p>}
          <div className="mira-quick" aria-label="Quick replies" role="group">
            {QUICK_REPLIES.map(item => (
              <button type="button" key={item.label} disabled={pending} onClick={() => {
                if ('draftOnly' in item) {
                  setDraft(item.message)
                  composer.current?.focus()
                } else {
                  void send(item.message)
                }
              }}>{item.label}</button>
            ))}
          </div>
          <form className="mira-compose" onSubmit={submit}>
            <textarea ref={composer} aria-label="Message Mira" placeholder="Message Mira" value={draft}
              rows={1} maxLength={2000} onChange={event => setDraft(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void send(draft)
                }
              }} />
            <button className="mira-send" type="submit" disabled={pending || !draft.trim()}>Send</button>
          </form>
        </div>
      </> : <div className="mira-state" aria-live="polite">
        {!token ? <>
          <h3>Sign in to chat with Mira</h3>
          <p>Your banking conversation is available after you sign in.</p>
          <a className="mira-send" href="#meridian-sign-in-email" onClick={close}>Go to sign in</a>
        </> : identity.status === 'loading' ? <p>Checking your Mira session…</p>
          : identity.status === 'expired' ? <p>Your Mira session has ended. Sign out and sign in again to continue.</p>
          : identity.status === 'denied' ? <p>Mira’s banking chat is available to customer accounts.</p>
          : <>
            <p>We couldn’t verify your Mira session.</p>
            <button type="button" className="mira-send" onClick={() => setRetry(value => value + 1)}>Try again</button>
          </>}
      </div>}
    </section>
  )
}

export default function MiraChat({ token }: { token: string | null }) {
  const [open, setOpen] = useState(false)
  const launcher = useRef<HTMLButtonElement>(null)

  function close() {
    setOpen(false)
    launcher.current?.focus()
  }

  return <div className="mira-widget">
    <ChatPanel key={token ?? 'signed-out'} token={token} open={open} close={close} />
    <button ref={launcher} className="mira-launcher" type="button" aria-expanded={open}
      aria-controls="mira-chat-panel" aria-label={open ? 'Hide Mira chat' : 'Open Mira chat'}
      onClick={() => setOpen(value => !value)}>
      <span className="mira-symbol" aria-hidden="true">···</span>
      <span>Mira</span>
    </button>
  </div>
}
