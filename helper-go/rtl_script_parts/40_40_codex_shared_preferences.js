  const sharedCodexPreferences = () => {
    const preferences = window.__agentsRtlCodexPreferences;
    if (!preferences || typeof preferences !== "object" || Array.isArray(preferences)) return {};
    return preferences;
  };
  const sharedCodexChatTabOrder = () => {
    const sharedOrder = sharedCodexPreferences().codexChatOrder;
    if (!Array.isArray(sharedOrder)) return [];
    return sharedOrder.map(compactText).filter(Boolean);
  };
  const storedCodexChatTabOrderRequests = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_TAB_ORDER_REQUESTS_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) return [];
    return parsedValue
      .map((request) => ({
        ids: Array.isArray(request?.ids) ? [...new Set(request.ids.map(compactText).filter(Boolean))] : [],
        requestedAt: Number.isFinite(request?.requestedAt) ? request.requestedAt : Date.now(),
      }))
      .filter((request) => request.ids.length > 0);
  };
