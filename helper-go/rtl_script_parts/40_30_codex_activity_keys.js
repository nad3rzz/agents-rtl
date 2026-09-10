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
  const storedCodexLatestAgentReplyActivityRequests = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_LATEST_AGENT_REPLY_ACTIVITY_REQUESTS_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) {
      throw new Error("Codex latest agent reply activity requests must be an array.");
    }
    return parsedValue.map((request) => ({
      id: compactText(request?.id),
      activityKey: compactText(request?.activityKey),
      occurredAtMs: Number(request?.occurredAtMs),
      nativeUnreadStateKnown: request?.nativeUnreadStateKnown === true,
      nativeHasUnreadTurn: request?.nativeHasUnreadTurn === true,
    }));
  };
  const saveCodexLatestAgentReplyActivityRequests = (requests) => {
    localStorage.setItem(
      CODEX_CHAT_LATEST_AGENT_REPLY_ACTIVITY_REQUESTS_STORAGE_KEY,
      JSON.stringify(requests)
    );
  };
  const queueCodexLatestAgentReplyActivityRequest = (conversation) => {
    if (!conversation?.id || !conversation.activityKey || !Number.isFinite(conversation.activityOccurredAtMs) ||
      conversation.activityOccurredAtMs <= 0) return;
    const sharedActivity = sharedCodexLatestAgentReplyActivities()[conversation.id];
    if (sharedActivity) {
      if (sharedActivity.occurredAtMs > conversation.activityOccurredAtMs) return;
      if (sharedActivity.occurredAtMs === conversation.activityOccurredAtMs) {
        if (sharedActivity.activityKey !== conversation.activityKey) {
          throw new Error("Conflicting local and shared agent reply activity for conversation " + conversation.id);
        }
        return;
      }
    }
    const storedRequests = storedCodexLatestAgentReplyActivityRequests();
    const existingRequest = storedRequests.find((request) => request.id === conversation.id);
    if (existingRequest?.activityKey === conversation.activityKey &&
      existingRequest.occurredAtMs === conversation.activityOccurredAtMs) return;
    const nextRequests = [
      ...storedRequests.filter((request) => request.id !== conversation.id),
      {
        id: conversation.id,
        activityKey: conversation.activityKey,
        occurredAtMs: conversation.activityOccurredAtMs,
        nativeUnreadStateKnown: conversation.nativeUnreadStateKnown === true,
        nativeHasUnreadTurn: conversation.nativeHasUnreadTurn === true,
      },
    ];
    saveCodexLatestAgentReplyActivityRequests(nextRequests);
  };
