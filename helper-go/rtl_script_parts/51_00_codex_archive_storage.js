  const storedCodexChatArchiveRequests = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_ARCHIVE_REQUESTS_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) return [];
    return parsedValue
      .map((request) => ({
        id: compactText(request?.id),
        title: compactText(request?.title),
        requestedAt: Number.isFinite(request?.requestedAt) ? request.requestedAt : Date.now(),
      }))
      .filter((request) => request.id);
  };
  const saveCodexChatArchiveRequests = (archiveRequests) =>
    localStorage.setItem(CODEX_CHAT_ARCHIVE_REQUESTS_STORAGE_KEY, JSON.stringify(archiveRequests));
  const pendingCodexArchiveConversationIdSet = () =>
    new Set(storedCodexChatArchiveRequests().map((request) => request.id));
  const storedCodexProcessedArchiveIds = () => {
    const storedValue = localStorage.getItem(CODEX_CHAT_PROCESSED_ARCHIVES_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) throw new Error("Invalid Codex processed archive ids payload");
    return [...new Set(parsedValue.map(compactText).filter(Boolean))];
  };
  const saveCodexProcessedArchiveIds = (conversationIds) => {
    const compactConversationIds = [...new Set(conversationIds.map(compactText).filter(Boolean))];
    if (compactConversationIds.length === 0) {
      localStorage.removeItem(CODEX_CHAT_PROCESSED_ARCHIVES_STORAGE_KEY);
      return;
    }
    localStorage.setItem(CODEX_CHAT_PROCESSED_ARCHIVES_STORAGE_KEY, JSON.stringify(compactConversationIds));
  };
  const saveCodexArchiveRequest = (conversation) => {
    const archiveRequests = storedCodexChatArchiveRequests();
    if (!archiveRequests.some((request) => request.id === conversation.id)) {
      archiveRequests.push({
        id: conversation.id,
        title: conversation.title,
        requestedAt: Date.now(),
      });
      saveCodexChatArchiveRequests(archiveRequests);
    }
    const savedRequestExists = storedCodexChatArchiveRequests().some((request) => request.id === conversation.id);
    if (!savedRequestExists) throw new Error("Codex archive request was not persisted for id: " + conversation.id);
  };
