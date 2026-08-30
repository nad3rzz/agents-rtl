  const storedCodexChatTabOrder = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_TAB_ORDER_STORAGE_KEY);
    const localOrder = storedValue === null ? [] : JSON.parse(storedValue);
    if (!Array.isArray(localOrder)) return [];
    const pendingOrderRequests = storedCodexChatTabOrderRequests();
    if (pendingOrderRequests.length > 0) return pendingOrderRequests[pendingOrderRequests.length - 1].ids;
    const sharedOrder = sharedCodexChatTabOrder();
    if (sharedOrder.length > 0) return sharedOrder;
    return localOrder.map(compactText).filter(Boolean);
  };
  const saveCodexChatTabOrder = (conversationIds) => {
    const compactConversationIds = [...new Set(conversationIds.map(compactText).filter(Boolean))];
    const sharedOrder = sharedCodexChatTabOrder();
    const pendingOrderRequests = storedCodexChatTabOrderRequests();
    const latestPendingOrder = pendingOrderRequests[pendingOrderRequests.length - 1]?.ids || [];
    const compactOrderKey = compactConversationIds.join("|");
    localStorage.setItem(CODEX_CHAT_TAB_ORDER_STORAGE_KEY, JSON.stringify(compactConversationIds));
    if (compactOrderKey === sharedOrder.join("|") || compactOrderKey === latestPendingOrder.join("|")) return;
    localStorage.setItem(CODEX_CHAT_TAB_ORDER_REQUESTS_STORAGE_KEY, JSON.stringify([{
      ids: compactConversationIds,
      requestedAt: Date.now(),
    }]));
  };
  const storedCodexConversationIdArray = (storageKey) => {
    const storedValue = localStorage.getItem(storageKey);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) return [];
    return [...new Set(parsedValue.map(compactText).filter(Boolean))];
  };
  const saveCodexConversationIdArray = (storageKey, conversationIds) => {
    const compactConversationIds = [...new Set(conversationIds.map(compactText).filter(Boolean))];
    localStorage.setItem(storageKey, JSON.stringify(compactConversationIds));
  };
  const storedCodexRecentConversationIds = () => storedCodexConversationIdArray(CODEX_CHAT_RECENT_STORAGE_KEY);
  const saveCodexRecentConversationIds = (conversationIds) =>
    saveCodexConversationIdArray(CODEX_CHAT_RECENT_STORAGE_KEY, conversationIds);
  const rememberCodexRecentConversation = (conversationId, conversations) => {
    const compactConversationId = compactText(conversationId);
    if (!compactConversationId) return;
    const validConversationIds = new Set(conversations.map((conversation) => conversation.id));
    if (!validConversationIds.has(compactConversationId)) return;
    const nextRecentConversationIds = [
      compactConversationId,
      ...storedCodexRecentConversationIds().filter((candidate) =>
        candidate !== compactConversationId && validConversationIds.has(candidate)
      ),
    ];
    if (nextRecentConversationIds.join("|") !== storedCodexRecentConversationIds().join("|")) {
      saveCodexRecentConversationIds(nextRecentConversationIds);
    }
  };
