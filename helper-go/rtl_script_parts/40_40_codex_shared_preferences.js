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
  const sharedCodexLatestAgentReplyActivities = () => {
    const sharedActivities = sharedCodexPreferences().codexLatestAgentReplyActivities;
    if (sharedActivities === undefined) return {};
    if (!sharedActivities || typeof sharedActivities !== "object" || Array.isArray(sharedActivities)) {
      throw new Error("Shared Codex latest agent reply activities must be an object.");
    }
    return Object.fromEntries(Object.entries(sharedActivities).map(([conversationId, activity]) => {
      const compactConversationId = compactText(conversationId);
      const activityKey = compactText(activity?.activityKey);
      const occurredAtMs = Number(activity?.occurredAtMs);
      if (!compactConversationId || !activityKey || !Number.isFinite(occurredAtMs) || occurredAtMs <= 0) {
        throw new Error("Shared Codex latest agent reply activity is invalid.");
      }
      return [compactConversationId, { activityKey, occurredAtMs }];
    }));
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
