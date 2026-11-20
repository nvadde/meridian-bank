import { useCallback, useEffect, useState } from 'react'
import {
  getAccounts, getTransactions, money, setCardFrozen, submitTransfer,
  type Account, type Transaction, type TransferRequest,
} from '../api/accounts'
import { ApiError } from '../api/client'
import Dashboard, { type DashboardOperation } from '../components/Dashboard'

interface Props {
  token: string
  onExpire: () => void
  onSignOut: () => Promise<void>
}

interface Snapshot {
  accounts: Account[]
  transactions: Transaction[]
}

function operationMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.code === 'INSUFFICIENT_FUNDS') return 'The amount exceeds your available balance.'
    if (error.code === 'FORBIDDEN') return 'This action is available only for your own accounts.'
    if (error.code === 'BALANCE_LIMIT') return 'This amount would exceed the destination account’s balance limit.'
    if (error.code === 'TRANSFER_REQUEST_CONFLICT') return 'This transfer confirmation has already been used. Start a new transfer.'
  }
  return fallback
}

export default function DashboardPage({ token, onExpire, onSignOut }: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loadError, setLoadError] = useState('')
  const [pending, setPending] = useState<DashboardOperation | null>(null)
  const [transferError, setTransferError] = useState('')
  const [cardError, setCardError] = useState('')
  const [logoutError, setLogoutError] = useState('')
  const [notice, setNotice] = useState('')
  const handleSession = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.code === 'INVALID_SESSION') {
      onExpire()
      return true
    }
    return false
  }, [onExpire])

  const refresh = useCallback(async () => {
    setLoadError('')
    try {
      const [accounts, transactions] = await Promise.all([getAccounts(token), getTransactions(token)])
      setSnapshot({ accounts, transactions })
    } catch (error) {
      if (!handleSession(error)) {
        setLoadError(error instanceof ApiError && error.status === 403
          ? 'The customer dashboard is available to customer accounts.'
          : 'We couldn’t load your accounts and activity.')
      }
    }
  }, [token, handleSession])

  useEffect(() => { void refresh() }, [refresh])

  async function transfer(draft: TransferRequest) {
    setPending('transfer')
    setTransferError('')
    setNotice('')
    try {
      const receipt = await submitTransfer(token, draft)
      await refresh()
      setNotice(money(receipt.amount) + ' transferred.')
      return true
    } catch (error) {
      if (!handleSession(error)) {
        setTransferError(operationMessage(error, 'We couldn’t confirm the transfer. Retry this confirmation to check its status.'))
      }
      return false
    } finally {
      setPending(null)
    }
  }

  async function toggleCard(card: Account) {
    setPending('card')
    setCardError('')
    setNotice('')
    try {
      const updated = await setCardFrozen(token, card.id, card.card_status !== 'FROZEN')
      setSnapshot(current => current ? {
        ...current,
        accounts: current.accounts.map(account => account.id === card.id
          ? { ...account, card_status: updated.card_status }
          : account),
      } : current)
      setNotice(updated.card_status === 'FROZEN' ? 'Your Rewards Card is frozen.' : 'Your Rewards Card is active.')
    } catch (error) {
      if (!handleSession(error)) setCardError(operationMessage(error, 'We couldn’t update your card. Try again.'))
    } finally {
      setPending(null)
    }
  }

  async function signOut() {
    setPending('logout')
    setLogoutError('')
    try {
      await onSignOut()
    } catch {
      setLogoutError('We couldn’t sign you out. Try again.')
      setPending(null)
    }
  }

  return <main className="dashboard" id="dashboard">
    <div className="page-title">
      <h1>Account overview</h1>
      <button type="button" className="secondary" onClick={signOut} disabled={pending !== null}>
        {pending === 'logout' ? 'Signing out…' : 'Sign out'}
      </button>
    </div>
    {logoutError && <p className="message error" role="alert">{logoutError}</p>}
    {loadError && <div className="message error load-error" role="alert">
      <span>{loadError}</span><button type="button" className="secondary" onClick={refresh}>Retry</button>
    </div>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {!snapshot && !loadError && <p className="muted" role="status">Loading your dashboard…</p>}
    {snapshot && <Dashboard
      accounts={snapshot.accounts}
      transactions={snapshot.transactions}
      pending={pending}
      transfersDisabled={!!loadError}
      transferError={transferError}
      cardError={cardError}
      onTransfer={transfer}
      onToggleCard={toggleCard}
    />}
  </main>
}
