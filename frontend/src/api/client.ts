const configuredApiUrl = import.meta.env.VITE_API_URL?.trim()
const apiBaseUrl = (configuredApiUrl || '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(readonly status: number, readonly code?: string, readonly attemptsRemaining?: number) {
    super(code ?? 'REQUEST_FAILED')
  }
}

export async function request<T>(
  path: string,
  options: { token?: string; body?: object; method?: 'GET' | 'POST'; signal?: AbortSignal } = {},
): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' })
  if (options.token) headers.set('Authorization', 'Bearer ' + options.token)
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(apiBaseUrl + path, {
    method: options.method ?? (options.body ? 'POST' : 'GET'),
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new ApiError(response.status, data?.detail?.code, data?.detail?.attempts_remaining)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}
