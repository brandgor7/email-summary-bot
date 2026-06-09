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
