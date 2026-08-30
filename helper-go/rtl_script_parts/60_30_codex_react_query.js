  const findCodexReactQueryClient = () => {
    const cachedClient = window[KEY]?.codexReactQueryClient;
    if (cachedClient && typeof cachedClient.getQueryCache === "function") return cachedClient;
    const roots = new Set();
    document.querySelectorAll("*").forEach((element) => {
      const fiberKey = codexReactFiberKey(element);
      if (!fiberKey) return;
      let fiber = element[fiberKey];
      while (fiber?.return) fiber = fiber.return;
      if (fiber) roots.add(fiber);
    });
    const stack = [...roots].map((root) => root.child).filter(Boolean);
    const visitedFibers = new Set();
    while (stack.length > 0) {
      const fiber = stack.pop();
      if (!fiber || visitedFibers.has(fiber)) continue;
      visitedFibers.add(fiber);
      const memoizedProps = fiber.memoizedProps || {};
      const pendingProps = fiber.pendingProps || {};
      const directCandidates = [
        memoizedProps.queryClient,
        memoizedProps.client,
        pendingProps.queryClient,
        pendingProps.client,
      ];
      const directClient = directCandidates.find((candidate) => candidate && typeof candidate.getQueryCache === "function");
      if (directClient) {
        if (window[KEY]) window[KEY].codexReactQueryClient = directClient;
        return directClient;
      }
      let hook = fiber.memoizedState;
      let hookIndex = 0;
      while (hook && hookIndex < 10) {
        const hookValue = hook.memoizedState;
        const hookClient = [hookValue, hookValue?.current?.queryClient]
          .find((candidate) => candidate && typeof candidate.getQueryCache === "function");
        if (hookClient) {
          if (window[KEY]) window[KEY].codexReactQueryClient = hookClient;
          return hookClient;
        }
        hook = hook.next;
        hookIndex += 1;
      }
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }
    return null;
  };
  const codexConversationListFromReactQueryCache = () => {
    const queryClient = findCodexReactQueryClient();
    if (!queryClient) return null;
    const queries = queryClient.getQueryCache?.().getAll?.();
    if (!Array.isArray(queries)) return null;
    const conversationListQuery = queries.find((query) => {
      const data = query?.state?.data;
      return Array.isArray(data) && data.some((item) =>
        item &&
        typeof item === "object" &&
        typeof item.title === "string" &&
        item.threadRuntimeStatus &&
        Array.isArray(item.turns)
      );
    });
    return conversationListQuery?.state?.data || null;
  };
