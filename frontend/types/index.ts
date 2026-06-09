export interface DigestSettings {
  digest_prefs: string;
  schedule: "morning" | "evening" | "both";
  enabled: boolean;
}

export interface ProvidersResponse {
  sources: string[];
  destinations: string[];
}

export interface SourceToken {
  provider: string;
  provider_email: string;
}

export interface DestinationConfig {
  provider: string;
}

export interface LinkCodeResponse {
  code: string;
  bot_username: string;
}

export interface TelegramStatusResponse {
  linked: boolean;
}

export interface DigestEmailItem {
  subject: string;
  sender: string;
  summary: string;
  reason: string;
  suggested_action?: string;
}

export interface DigestTodo {
  item: string;
  source_email: string;
}

export interface DigestResult {
  urgent: DigestEmailItem[];
  action_required: DigestEmailItem[];
  fyi: DigestEmailItem[];
  todos: DigestTodo[];
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface SendResult {
  status: "sent" | "error";
  destination: string;
  error?: string;
}

export interface PreviewResponse {
  digest: DigestResult;
  token_usage: TokenUsage;
  send_result?: SendResult;
}
