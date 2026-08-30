  const sanitizeCodexConversationRecords = (rawConversations, titleFallbacksById = new Map()) => {
    const seenConversationIds = new Set();
    return (Array.isArray(rawConversations) ? rawConversations : [])
      .map((conversation) => {
        const lastActivity = codexLastActivityFromConversationRecord(conversation);
        return {
          id: codexConversationIdFromRecord(conversation),
          title: codexConversationTitleFromRecord(conversation),
          hostId: compactText(conversation?.hostId || conversation?.thread?.hostId || conversation?.conversation?.hostId),
          path: conversation?.path || "",
          activityKey: lastActivity.activityKey,
          activityIsAgentReply: lastActivity.isAgentReply,
          archived: conversation?.archived === true,
        };
      })
      .map((conversation) => ({
        id: conversation.id,
        title: conversation.title || titleFallbacksById.get(conversation.id) || "",
        hostId: conversation.hostId,
        path: conversation.path,
        activityKey: conversation.activityKey,
        activityIsAgentReply: conversation.activityIsAgentReply,
        archived: conversation.archived,
      }))
      .filter((conversation) => conversation.id && conversation.title && !conversation.archived)
      .filter((conversation) => {
        if (seenConversationIds.has(conversation.id)) return false;
        seenConversationIds.add(conversation.id);
        return true;
      });
  };
  const sanitizeCodexHelperConversations = () =>
    sanitizeCodexConversationRecords(window.__agentsRtlCodexConversations);
  const sanitizeCodexReactConversations = (titleFallbacksById) => {
    const rawConversations = codexConversationListFromReactQueryCache();
    if (!Array.isArray(rawConversations)) return [];
    return sanitizeCodexConversationRecords(rawConversations, titleFallbacksById);
  };
  const mergeCodexConversationSources = () => {
    const helperConversations = sanitizeCodexHelperConversations();
    const titleFallbacksById = new Map(helperConversations.map((conversation) => [conversation.id, conversation.title]));
    const pathFallbacksById = new Map(helperConversations.map((conversation) => [conversation.id, conversation.path]));
    const hostIdFallbacksById = new Map(helperConversations.map((conversation) => [conversation.id, conversation.hostId]));
    const activityFallbacksById = new Map(helperConversations.map((conversation) => [conversation.id, conversation]));
    const reactConversations = sanitizeCodexReactConversations(titleFallbacksById);
    if (reactConversations.length === 0) return helperConversations;
    const reactConversationIds = new Set(reactConversations.map((conversation) => conversation.id));
    const mergedConversations = reactConversations.map((conversation) => ({
      id: conversation.id,
      title: conversation.title || titleFallbacksById.get(conversation.id) || "",
      hostId: conversation.hostId || hostIdFallbacksById.get(conversation.id) || "",
      path: conversation.path || pathFallbacksById.get(conversation.id) || "",
      activityKey: conversation.activityKey || activityFallbacksById.get(conversation.id)?.activityKey || "",
      activityIsAgentReply: conversation.activityIsAgentReply === true ||
        activityFallbacksById.get(conversation.id)?.activityIsAgentReply === true,
    }));
    helperConversations.forEach((conversation) => {
      if (reactConversationIds.has(conversation.id)) return;
      mergedConversations.push(conversation);
    });
    return mergedConversations.filter((conversation) => conversation.id && conversation.title);
  };
  const sanitizeCodexConversations = () => mergeCodexConversationSources();
  const updateCodexConversations = () => {
    consumeCodexProcessedArchiveIds();
    const conversations = sanitizeCodexConversations();
    if (window[KEY]) window[KEY].codexConversations = conversations;
    return conversations;
  };
