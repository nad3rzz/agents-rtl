  const compareCodexConversationOrderEntriesByLatestReply = (leftEntry, rightEntry) => {
    const timestampDifference =
      codexConversationLastReplyTimestampMs(rightEntry.conversation) -
      codexConversationLastReplyTimestampMs(leftEntry.conversation);
    if (timestampDifference !== 0) return timestampDifference;
    return leftEntry.stableOrderIndex - rightEntry.stableOrderIndex;
  };
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
    const stableOrderEntries = [];
    for (let stableOrderIndex = 0; stableOrderIndex < orderedConversationIds.length; stableOrderIndex += 1) {
      const conversation = conversationsById.get(orderedConversationIds[stableOrderIndex]);
      if (!conversation) continue;
      stableOrderEntries.push({ conversation, stableOrderIndex });
    }
    stableOrderEntries.sort(compareCodexConversationOrderEntriesByLatestReply);
    return stableOrderEntries.map((entry) => entry.conversation);
  };
