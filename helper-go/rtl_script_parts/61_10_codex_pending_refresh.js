  const updateCodexPendingApprovalTitles = () => {
    const cachePendingApprovalConversations = codexPendingApprovalConversationsFromReactQueryCache();
    if (cachePendingApprovalConversations !== null) {
      if (window[KEY]) {
        window[KEY].codexPendingApprovalConversationIds = cachePendingApprovalConversations.map((conversation) => conversation.id);
      }
      return saveCodexPendingApprovalTitles(cachePendingApprovalConversations.map((conversation) => conversation.title));
    }
    if (window[KEY]) window[KEY].codexPendingApprovalConversationIds = [];
    if (!codexTasksListIsVisible()) {
      const pendingApprovalTitles = storedCodexPendingApprovalTitles();
      const currentTitle = findCodexCurrentConversationTitle();
      if (!currentTitle) return pendingApprovalTitles;
      const nextPendingApprovalTitleSet = new Set(pendingApprovalTitles);
      if (codexApprovalPromptIsVisible()) {
        nextPendingApprovalTitleSet.add(currentTitle);
      } else {
        nextPendingApprovalTitleSet.delete(currentTitle);
      }
      return saveCodexPendingApprovalTitles([...nextPendingApprovalTitleSet]);
    }
    return saveCodexPendingApprovalTitles(
      codexTaskRows().map(extractCodexPendingApprovalTitleFromTaskRow).filter(Boolean)
    );
  };
  const updateCodexPendingApprovalRefreshTimer = () => {
    const state = window[KEY];
    if (!state) return;
    const shouldRefresh = codexHasActiveTaskInReactQueryCache() || codexActiveTaskCountFromTaskHistoryButton() > 0;
    if (!shouldRefresh) {
      if (state.codexPendingApprovalRefreshIntervalId !== null) {
        clearInterval(state.codexPendingApprovalRefreshIntervalId);
        state.codexPendingApprovalRefreshIntervalId = null;
      }
      return;
    }
    if (state.codexPendingApprovalRefreshIntervalId !== null) return;
    state.codexPendingApprovalRefreshIntervalId = setInterval(() => {
      const previousTitles = storedCodexPendingApprovalTitles().join("|");
      const nextTitles = updateCodexPendingApprovalTitles().join("|");
      updateCodexPendingApprovalRefreshTimer();
      if (previousTitles !== nextTitles) renderCodexChatTabs();
    }, CODEX_PENDING_APPROVAL_REFRESH_INTERVAL_MS);
  };
  const removeCodexPendingApprovalRefreshTimer = () => {
    const state = window[KEY];
    if (!state?.codexPendingApprovalRefreshIntervalId) return;
    clearInterval(state.codexPendingApprovalRefreshIntervalId);
    state.codexPendingApprovalRefreshIntervalId = null;
  };
