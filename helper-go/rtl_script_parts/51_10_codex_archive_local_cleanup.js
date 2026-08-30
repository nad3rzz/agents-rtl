  const removeCodexConversationLocallyAfterArchive = (conversationId) => {
    saveCodexChatTabOrder(storedCodexChatTabOrder().filter((storedConversationId) => storedConversationId !== conversationId));
    if (window[KEY]) {
      window[KEY].codexConversations = (window[KEY].codexConversations || []).filter((candidate) => candidate.id !== conversationId);
    }
    if (Array.isArray(window.__agentsRtlCodexConversations)) {
      window.__agentsRtlCodexConversations = window.__agentsRtlCodexConversations.filter((candidate) => candidate?.id !== conversationId);
    }
    removeCodexConversationFromReactQueryCache(conversationId);
  };
  const consumeCodexProcessedArchiveIds = () => {
    const processedConversationIds = storedCodexProcessedArchiveIds();
    if (processedConversationIds.length === 0) return;
    processedConversationIds.forEach(removeCodexConversationLocallyAfterArchive);
    saveCodexProcessedArchiveIds([]);
  };
