import { useState, type FormEvent } from 'react'
import { accountName, lastFour, money, type Account, type TransferRequest } from '../api/accounts'

interface Props {
  accounts: Account[]
  pending: boolean
  disabled: boolean
  onTransfer: (transfer: TransferRequest) => Promise<boolean>
}

function optionLabel(account: Account) {
  return accountName(account) + ' · ' + lastFour(account)
}

export default function TransferForm({ accounts, pending, disabled, onTransfer }: Props) {
  const eligible = accounts.filter(account => ['CHECKING', 'SAVINGS'].includes(account.account_type))
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [amount, setAmount] = useState('')
  const [review, setReview] = useState<TransferRequest | null>(null)
  const [error, setError] = useState('')
  const source = eligible.find(account => account.id === Number(fromId))
  const destination = eligible.find(account => account.id === Number(toId))

  function reviewTransfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!source || !destination || source.id === destination.id) {
      setError('Choose two different accounts.')
      return
    }
    const value = amount.trim()
    if (!/^\d+(?:\.\d{1,2})?$/.test(value) || Number(value) <= 0) {
      setError('Enter an amount greater than $0 with up to two decimal places.')
      return
    }
    if (Number(value) > source.balance) {
      setError('The amount exceeds your available balance.')
      return
    }

    setError('')
    setReview({
      from_account: source.id, to_account: destination.id,
      amount: value, request_id: crypto.randomUUID(),
    })
  }

  async function confirm() {
    if (review && await onTransfer(review)) {
      setReview(null)
      setAmount('')
    }
  }

  if (eligible.length < 2) return <p className="muted">You need two eligible accounts to make a transfer.</p>
  if (review && source && destination) {
    return <section className="transfer-review" aria-labelledby="review-title">
      <h3 id="review-title">Confirm transfer</h3>
      <dl>
        <div><dt>From</dt><dd>{optionLabel(source)}</dd></div>
        <div><dt>To</dt><dd>{optionLabel(destination)}</dd></div>
        <div><dt>Amount</dt><dd>{money(review.amount)}</dd></div>
      </dl>
      <div className="button-row">
        <button type="button" className="secondary" onClick={() => setReview(null)} disabled={pending}>Back</button>
        <button type="button" className="primary" onClick={confirm} disabled={disabled}>{pending ? 'Sending…' : 'Confirm transfer'}</button>
      </div>
    </section>
  }

  return <form onSubmit={reviewTransfer} className="transfer-form" noValidate>
    <label><span id="transfer-from-label">From account</span><select aria-labelledby="transfer-from-label" value={fromId} onChange={event => {
      setFromId(event.target.value)
      if (event.target.value === toId) setToId('')
      setError('')
    }}>
      <option value="">Select an account</option>
      {eligible.map(account => <option key={account.id} value={account.id}>{optionLabel(account)}</option>)}
    </select></label>
    <label><span id="transfer-to-label">To account</span><select aria-labelledby="transfer-to-label" value={toId} onChange={event => {
      setToId(event.target.value)
      setError('')
    }}>
      <option value="">Select an account</option>
      {eligible.filter(account => account.id !== source?.id).map(account =>
        <option key={account.id} value={account.id}>{optionLabel(account)}</option>)}
    </select></label>
    <label><span id="transfer-amount-label">Amount</span>
      <span className="amount-field"><span aria-hidden="true">$</span>
        <input aria-labelledby="transfer-amount-label" value={amount} onChange={event => { setAmount(event.target.value); setError('') }} inputMode="decimal" placeholder="0.00" />
      </span>
    </label>
    {source && <p className="field-hint">Available {money(source.balance)}</p>}
    {error && <p className="message error" role="alert">{error}</p>}
    <button className="primary" type="submit" disabled={disabled}>Review transfer <span aria-hidden="true">→</span></button>
  </form>
}
