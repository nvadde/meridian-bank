import { request } from '../api/client'

export interface MiraReply {
  text: string
  agent_used: string
  tools_used: string[]
}

export function getMiraSession(token: string, signal: AbortSignal) {
  return request<{ display_name: string }>('/chat/session', { token, signal })
}

export function sendMiraMessage(token: string, message: string, signal: AbortSignal) {
  return request<MiraReply>('/chat', { body: { session_token: token, message }, signal })
}
