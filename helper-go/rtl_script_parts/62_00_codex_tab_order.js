  const orderCodexConversations = (conversations) => {
    const conversationsById = new Map(conversations.map((conversation) => [conversation.id, conversation]));
    const storedOrderConversationIds = storedCodexChatTabOrder();
    const storedConversationIds = storedOrderConversationIds.filter((conversationId) => conversationsById.has(conversationId));
    const storedConversationIdSet = new Set(storedConversationIds);
    const newConversationIds = conversations
      .map((conversation) => conversation.id)
      .filter((conversationId) => !storedConversationIdSet.has(conversationId));
    const orderedConversationIds = [...storedConversationIds, ...newConversationIds];
    if (orderedConversationIds.join("|") !== storedOrderConversationIds.join("|")) {
      saveCodexChatTabOrder(orderedConversationIds);
    }
    return orderedConversationIds.map((conversationId) => conversationsById.get(conversationId)).filter(Boolean);
  };
  const splitVisibleCodexConversations = (conversations, activeConversationId) => {
    const conversationsById = new Map(conversations.map((conversation) => [conversation.id, conversation]));
    const visibleConversationIds = [];
    const addVisibleConversationId = (conversationId) => {
      const compactConversationId = compactText(conversationId);
      if (!compactConversationId || !conversationsById.has(compactConversationId)) return;
      if (visibleConversationIds.includes(compactConversationId)) return;
      visibleConversationIds.push(compactConversationId);
    };
    addVisibleConversationId(activeConversationId);
    storedCodexRecentConversationIds().forEach(addVisibleConversationId);
    conversations.map((conversation) => conversation.id).forEach(addVisibleConversationId);
    const visibleConversations = visibleConversationIds
      .slice(0, CODEX_CHAT_VISIBLE_TAB_LIMIT)
      .map((conversationId) => conversationsById.get(conversationId))
      .filter(Boolean);
    const visibleConversationIdSet = new Set(visibleConversations.map((conversation) => conversation.id));
    return {
      visibleConversations,
      overflowConversations: conversations.filter((conversation) => !visibleConversationIdSet.has(conversation.id)),
    };
  };
