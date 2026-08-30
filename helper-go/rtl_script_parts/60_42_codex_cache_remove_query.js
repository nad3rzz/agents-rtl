  const removeCodexConversationFromReactQueryCache = (conversationId) => {
    const normalizedConversationId = normalizeCodexConversationId(conversationId);
    if (!normalizedConversationId) return 0;
    const queryClient = findCodexReactQueryClient();
    if (!queryClient || typeof queryClient.setQueryData !== "function") return 0;
    const queries = queryClient.getQueryCache?.().getAll?.();
    if (!Array.isArray(queries)) return 0;
    let changedQueryCount = 0;
    queries.forEach((query) => {
      const queryKey = query?.queryKey;
      const data = query?.state?.data;
      const prunedData = pruneCodexConversationFromCacheValue(data, normalizedConversationId);
      if (!prunedData.changed) return;
      queryClient.setQueryData(queryKey, prunedData.value);
      changedQueryCount += 1;
    });
    queryClient.invalidateQueries?.({ queryKey: ["recent-conversations"] });
    queryClient.invalidateQueries?.({ queryKey: ["recent-tasks"] });
    return changedQueryCount;
  };
