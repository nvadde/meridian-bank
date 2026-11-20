import { accountName, lastFour, money, type Account } from '../api/accounts'

export default function AccountCard({ account }: { account: Account }) {
  return <article className={'account-tile ' + account.account_type.toLowerCase()}>
    <h3>{accountName(account)}</h3>
    <span className="masked-number">•••• {lastFour(account)}</span>
    <div className="account-balance">{money(account.balance)}</div>
    <div className="balance-label">
      {account.account_type === 'CREDIT_CARD' ? 'Current balance' : 'Available balance'}
    </div>
  </article>
}
