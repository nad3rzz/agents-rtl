  const markCodexConversationActivitySeen = (conversation) => {
    if (!conversation?.id || !conversation.activityKey) return;
    const activityKeys = storedCodexActivityKeys();
    if (activityKeys[conversation.id] === conversation.activityKey) return;
    activityKeys[conversation.id] = conversation.activityKey;
    saveCodexActivityKeys(activityKeys);
    queueCodexActivityKeyRequest(conversation.id, conversation.activityKey);
  };
  const codexConversationHasUnreadAgentReply = (conversation) =>
    conversation.nativeUnreadStateKnown === true
      ? conversation.nativeHasUnreadTurn === true
      : conversation.activityIsAgentReply === true;
  const updateCodexUnreadConversationIds = (conversations, activeConversationId) => {
    const validConversationIds = new Set(conversations.map((conversation) => conversation.id));
    const activityKeys = storedCodexActivityKeys();
    const unreadConversationIds = new Set();
    const changedActivityKeyRequests = [];
    let activityKeysChanged = false;
    Object.keys(activityKeys).forEach((conversationId) => {
      if (validConversationIds.has(conversationId)) return;
      delete activityKeys[conversationId];
      activityKeysChanged = true;
    });
    conversations.forEach((conversation) => {
      if (!conversation.activityKey) return;
      const storedActivityKey = activityKeys[conversation.id] || "";
      const hasUnreadAgentReply = codexConversationHasUnreadAgentReply(conversation);
      if (conversation.id === activeConversationId) {
        if (storedActivityKey !== conversation.activityKey) {
          activityKeys[conversation.id] = conversation.activityKey;
          changedActivityKeyRequests.push({ id: conversation.id, activityKey: conversation.activityKey });
          activityKeysChanged = true;
        }
        return;
      }
      if (!storedActivityKey) {
        if (hasUnreadAgentReply) {
          unreadConversationIds.add(conversation.id);
          return;
        }
        activityKeys[conversation.id] = conversation.activityKey;
        changedActivityKeyRequests.push({ id: conversation.id, activityKey: conversation.activityKey });
        activityKeysChanged = true;
        return;
      }
      if (storedActivityKey !== conversation.activityKey && hasUnreadAgentReply) {
        unreadConversationIds.add(conversation.id);
      }
    });
    if (activityKeysChanged) {
      saveCodexActivityKeys(activityKeys);
      changedActivityKeyRequests.forEach((request) =>
        queueCodexActivityKeyRequest(request.id, request.activityKey)
      );
    }
    return unreadConversationIds;
  };
