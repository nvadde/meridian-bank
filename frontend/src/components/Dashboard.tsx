import { accountName, lastFour, money, type Account, type Transaction, type TransferRequest } from '../api/accounts'
import AccountCard from './AccountCard'
import TransferForm from './TransferForm'

export type DashboardOperation = 'transfer' | 'card' | 'logout'

interface Props {
  accounts: Account[]
  transactions: Transaction[]
  pending: DashboardOperation | null
  transfersDisabled: boolean
  transferError: string
  cardError: string
  onTransfer: (transfer: TransferRequest) => Promise<boolean>
  onToggleCard: (card: Account) => Promise<void>
}

const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

export default function Dashboard({
  accounts, transactions, pending, transfersDisabled, transferError, cardError, onTransfer, onToggleCard,
}: Props) {
  const cards = accounts.filter(account => account.account_type === 'CREDIT_CARD')
  const byId = new Map(accounts.map(account => [account.id, account]))

  return <>
    <section className="accounts" aria-labelledby="accounts-title">
      <h2 id="accounts-title">Your accounts</h2>
      {accounts.length === 0 && <p className="muted">There are no accounts to display.</p>}
      <div className="account-grid">
        {accounts.map(account => <AccountCard key={account.id} account={account} />)}
      </div>
    </section>
    <div className="dashboard-columns">
      <section className="panel activity" aria-labelledby="activity-title">
        <div className="panel-heading">
          <h2 id="activity-title">Recent transactions</h2>
          <span className="muted">Last 10</span>
        </div>
        {transactions.length ? <ul className="activity-list">
          {transactions.map(transaction => {
            const account = byId.get(transaction.account_id)
            const date = transaction.txn_date ? dateFormat.format(new Date(transaction.txn_date)) : ''
            return <li key={transaction.id}>
              <span className="activity-mark" aria-hidden="true">{transaction.amount >= 0 ? '↙' : '↗'}</span>
              <div className="transaction-label">
                <strong>{transaction.description ?? 'Transaction'}</strong>
                <small>{[account && accountName(account), date].filter(Boolean).join(' · ')}</small>
              </div>
              <span className={'transaction-amount ' + (transaction.amount >= 0 ? 'incoming' : '')}>
                {transaction.amount > 0 ? '+' : ''}{money(transaction.amount)}
              </span>
            </li>
          })}
        </ul> : <p className="muted">No recent transactions.</p>}
      </section>
      <aside className="dashboard-actions">
        <section className="panel" aria-labelledby="transfer-title">
          <div className="panel-heading"><h2 id="transfer-title">Transfer money</h2></div>
          <TransferForm accounts={accounts} pending={pending === 'transfer'} disabled={pending !== null || transfersDisabled} onTransfer={onTransfer} />
          {transferError && <p className="message error" role="alert">{transferError}</p>}
        </section>
        {cards.length > 0 && <section className="panel" aria-labelledby="cards-title">
          <div className="panel-heading"><h2 id="cards-title">Card controls</h2></div>
          {cards.map(card => <div className="card-control" key={card.id}>
            <div className="card-visual">
              <div className="card-chip" aria-hidden="true"></div>
              <strong>Rewards Card</strong>
              <span>•••• {lastFour(card)}</span>
            </div>
            <div className="card-actions">
              <span className={'card-status ' + (card.card_status === 'FROZEN' ? 'frozen' : '')} aria-live="polite">
                {card.card_status ?? 'ACTIVE'}
              </span>
              <button className="secondary" type="button" onClick={() => onToggleCard(card)} disabled={pending !== null}>
                {card.card_status === 'FROZEN' ? 'Unfreeze card' : 'Freeze card'}
              </button>
            </div>
          </div>)}
          {cardError && <p className="message error" role="alert">{cardError}</p>}
        </section>}
      </aside>
    </div>
  </>
}
