interface BridgeContext {
  pluginName?: string;
  displayName?: string;
  pageName?: string;
  pageTitle?: string;
  locale?: string;
  isDark?: boolean;
}

interface AstrBotPluginBridge {
  ready(): Promise<BridgeContext>;
  getContext(): BridgeContext | null;
  getLocale(): string;
  apiGet<T = unknown>(
    endpoint: string,
    params?: Record<string, string | number | boolean>,
  ): Promise<T>;
  apiPost<T = unknown>(endpoint: string, body?: Record<string, unknown>): Promise<T>;
  onContext(handler: () => void): () => void;
}

declare global {
  interface Window {
    AstrBotPluginPage?: AstrBotPluginBridge;
  }
}

export async function initBridge(): Promise<BridgeContext> {
  if (typeof window !== "undefined" && window.AstrBotPluginPage) {
    return await window.AstrBotPluginPage.ready();
  }
  return {
    pluginName: "astrbot_plugin_identity_directory",
    displayName: "通讯录",
    pageName: "directory",
    pageTitle: "通讯录",
    locale: "zh-CN",
    isDark: false,
  };
}

export async function apiGet<T = unknown>(
  endpoint: string,
  params: Record<string, string | number | boolean> = {},
): Promise<T> {
  if (typeof window !== "undefined" && window.AstrBotPluginPage) {
    return await window.AstrBotPluginPage.apiGet<T>(endpoint, params);
  }
  throw new Error("AstrBotPluginPage bridge unavailable");
}

export async function apiPost<T = unknown>(
  endpoint: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  if (typeof window !== "undefined" && window.AstrBotPluginPage) {
    return await window.AstrBotPluginPage.apiPost<T>(endpoint, body);
  }
  throw new Error("AstrBotPluginPage bridge unavailable");
}
