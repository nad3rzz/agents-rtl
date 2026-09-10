  const sanitizeCodexConversationRecords = (rawConversations, titleFallbacksById = new Map()) => {
    const seenConversationIds = new Set();
    return (Array.isArray(rawConversations) ? rawConversations : [])
      .map((conversation) => {
        const latestCompletedAgentReply = codexLatestCompletedAgentReplyFromConversationRecord(conversation);
        const nativeUnreadState = codexNativeUnreadStateFromConversationRecord(conversation);
        return {
          id: codexConversationIdFromRecord(conversation),
          title: codexConversationTitleFromRecord(conversation),
          hostId: compactText(conversation?.hostId || conversation?.thread?.hostId || conversation?.conversation?.hostId),
          path: conversation?.path || "",
          activityKey: latestCompletedAgentReply.activityKey,
          activityOccurredAtMs: latestCompletedAgentReply.occurredAtMs,
          activityIsAgentReply: latestCompletedAgentReply.isAgentReply,
          nativeUnreadStateKnown: nativeUnreadState.isKnown,
          nativeHasUnreadTurn: nativeUnreadState.hasUnreadTurn,
          archived: conversation?.archived === true,
        };
      })
      .map((conversation) => ({
        id: conversation.id,
        title: conversation.title || titleFallbacksById.get(conversation.id) || "",
        hostId: conversation.hostId,
        path: conversation.path,
        activityKey: conversation.activityKey,
        activityOccurredAtMs: conversation.activityOccurredAtMs,
        activityIsAgentReply: conversation.activityIsAgentReply,
        nativeUnreadStateKnown: conversation.nativeUnreadStateKnown,
        nativeHasUnreadTurn: conversation.nativeHasUnreadTurn,
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
      activityOccurredAtMs: conversation.activityOccurredAtMs ||
        activityFallbacksById.get(conversation.id)?.activityOccurredAtMs || 0,
      activityIsAgentReply: conversation.activityIsAgentReply === true ||
        activityFallbacksById.get(conversation.id)?.activityIsAgentReply === true,
      nativeUnreadStateKnown: conversation.nativeUnreadStateKnown === true ||
        activityFallbacksById.get(conversation.id)?.nativeUnreadStateKnown === true,
      nativeHasUnreadTurn: conversation.nativeUnreadStateKnown === true
        ? conversation.nativeHasUnreadTurn === true
        : activityFallbacksById.get(conversation.id)?.nativeHasUnreadTurn === true,
    }));
    helperConversations.forEach((conversation) => {
      if (reactConversationIds.has(conversation.id)) return;
      mergedConversations.push(conversation);
    });
    return mergedConversations.filter((conversation) => conversation.id && conversation.title);
  };
  const synchronizeCodexLatestAgentReplyActivities = (conversations) => {
    const sharedActivities = sharedCodexLatestAgentReplyActivities();
    return conversations.map((conversation) => {
      queueCodexLatestAgentReplyActivityRequest(conversation);
      const sharedActivity = sharedActivities[conversation.id];
      if (!sharedActivity || sharedActivity.occurredAtMs < conversation.activityOccurredAtMs) {
        return conversation;
      }
      if (sharedActivity.occurredAtMs === conversation.activityOccurredAtMs) {
        if (conversation.activityKey && sharedActivity.activityKey !== conversation.activityKey) {
          throw new Error("Conflicting latest agent reply activity for conversation " + conversation.id);
        }
        return conversation;
      }
      return {
        ...conversation,
        activityKey: sharedActivity.activityKey,
        activityOccurredAtMs: sharedActivity.occurredAtMs,
        activityIsAgentReply: true,
        nativeUnreadStateKnown: false,
        nativeHasUnreadTurn: false,
      };
    });
  };
  const sanitizeCodexConversations = () =>
    synchronizeCodexLatestAgentReplyActivities(mergeCodexConversationSources());
  const updateCodexConversations = () => {
    consumeCodexProcessedArchiveIds();
    const conversations = sanitizeCodexConversations();
    if (window[KEY]) window[KEY].codexConversations = conversations;
    return conversations;
  };
