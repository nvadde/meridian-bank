import { request } from './client'

export type CardStatus = 'ACTIVE' | 'FROZEN'

export interface Account {
  id: number
  user_id: string
  account_type: string
  masked_number: string
  balance: number
  card_status: CardStatus | null
}

export interface Transaction {
  id: number
  account_id: number
  description: string | null
  amount: number
  txn_date: string | null
}

export interface TransferRequest {
  from_account: number
  to_account: number
  amount: string
  request_id: string
}

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const money = (value: number | string) => currency.format(Number(value))

export function accountName(account: Account) {
  switch (account.account_type) {
    case 'CHECKING': return 'Checking'
    case 'SAVINGS': return 'Savings'
    case 'CREDIT_CARD': return 'Rewards Card'
    default: return account.account_type.replaceAll('_', ' ')
  }
}

export const lastFour = (account: Account) => account.masked_number.slice(-4)
export const getAccounts = (token: string) => request<Account[]>('/accounts', { token })
export function getTransactions(token: string, accountId?: number) {
  const path = accountId === undefined ? '/transactions' : '/accounts/' + accountId + '/transactions'
  return request<Transaction[]>(path + '?limit=10', { token })
}

export const submitTransfer = (token: string, body: TransferRequest) =>
  request<{ request_id: string; amount: string }>('/transfer', { token, body })

export const setCardFrozen = (token: string, accountId: number, frozen: boolean) =>
  request<{ account_id: number; card_status: CardStatus }>('/freeze-card', {
    token, body: { account_id: accountId, frozen },
  })
