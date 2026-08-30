  const storedCodexActivityKeys = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_ACTIVITY_STORAGE_KEY);
    const sharedActivityKeys = sharedCodexActivityKeys();
    if (storedValue === null) return sharedActivityKeys;
    const parsedValue = JSON.parse(storedValue);
    if (!parsedValue || typeof parsedValue !== "object" || Array.isArray(parsedValue)) return sharedActivityKeys;
    const localActivityKeys = Object.fromEntries(
      Object.entries(parsedValue)
        .map(([conversationId, activityKey]) => [compactText(conversationId), compactText(activityKey)])
        .filter(([conversationId, activityKey]) => conversationId && activityKey)
    );
    const pendingLocalActivityKeys = Object.fromEntries(
      storedCodexActivityKeyRequests()
        .map((request) => [request.id, localActivityKeys[request.id]])
        .filter(([conversationId, activityKey]) => conversationId && activityKey)
    );
    return { ...localActivityKeys, ...sharedActivityKeys, ...pendingLocalActivityKeys };
  };
  const saveCodexActivityKeys = (activityKeys) => {
    localStorage.setItem(CODEX_CHAT_ACTIVITY_STORAGE_KEY, JSON.stringify(activityKeys));
  };
  const sharedCodexActivityKeys = () => {
    const activityKeys = sharedCodexPreferences().codexChatActivityKeys;
    if (!activityKeys || typeof activityKeys !== "object" || Array.isArray(activityKeys)) return {};
    return Object.fromEntries(
      Object.entries(activityKeys)
        .map(([conversationId, activityKey]) => [compactText(conversationId), compactText(activityKey)])
        .filter(([conversationId, activityKey]) => conversationId && activityKey)
    );
  };
  const storedCodexActivityKeyRequests = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_ACTIVITY_REQUESTS_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) return [];
    return parsedValue
      .map((request) => ({
        id: compactText(request?.id),
        activityKey: compactText(request?.activityKey),
        requestedAt: Number(request?.requestedAt || 0),
      }))
      .filter((request) => request.id && request.activityKey);
  };
  const saveCodexActivityKeyRequests = (activityKeyRequests) => {
    localStorage.setItem(CODEX_CHAT_ACTIVITY_REQUESTS_STORAGE_KEY, JSON.stringify(activityKeyRequests));
  };
  const queueCodexActivityKeyRequest = (conversationId, activityKey) => {
    const compactConversationId = compactText(conversationId);
    const compactActivityKey = compactText(activityKey);
    if (!compactConversationId || !compactActivityKey) return;
    const sharedActivityKeys = sharedCodexActivityKeys();
    if (sharedActivityKeys[compactConversationId] === compactActivityKey) return;
    const nextRequests = [
      ...storedCodexActivityKeyRequests().filter((request) => request.id !== compactConversationId),
      { id: compactConversationId, activityKey: compactActivityKey, requestedAt: Date.now() },
    ];
    saveCodexActivityKeyRequests(nextRequests);
  };
