  const codexReactFiberKey = (element) =>
    Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
  const normalizeCodexConversationId = (value) => compactCodexConversationId(value);
  const codexConversationIdFromListRow = (row) => {
    const fiberKey = codexReactFiberKey(row);
    let fiber = fiberKey ? row[fiberKey] : null;
    let depth = 0;
    while (fiber && depth < 18) {
      const props = fiber.memoizedProps || fiber.pendingProps || {};
      const candidates = [
        props.conversationId,
        props.item?.conversation?.id,
        props.item?.id,
        props.item?.conversationId,
        props.item?.key,
        fiber.key,
      ];
      const conversationId = candidates.map(normalizeCodexConversationId).find(Boolean);
      if (conversationId) return conversationId;
      fiber = fiber.return;
      depth += 1;
    }
    return "";
  };
  const codexConversationIdFromElementFiber = (element, validConversationIds) => {
    const fiberKey = codexReactFiberKey(element);
    let fiber = fiberKey ? element[fiberKey] : null;
    let depth = 0;
    while (fiber && depth < 40) {
      const props = fiber.memoizedProps || fiber.pendingProps || {};
      const candidates = [
        props.conversationId,
        props.item?.conversation?.id,
        props.item?.id,
        props.item?.conversationId,
        props.item?.key,
        fiber.key,
      ];
      const conversationId = candidates
        .map(normalizeCodexConversationId)
        .find((candidate) => candidate && validConversationIds.has(candidate));
      if (conversationId) return conversationId;
      fiber = fiber.return;
      depth += 1;
    }
    return "";
  };
  const findCurrentCodexConversationIdFromReact = (validConversationIds) => {
    const candidateElements = [
      findCodexCurrentTitleElement(),
      document.querySelector(".thread-scroll-container"),
      document.querySelector("[data-thread-find-target='conversation']"),
    ].filter(Boolean);
    return candidateElements
      .map((element) => codexConversationIdFromElementFiber(element, validConversationIds))
      .find(Boolean) || "";
  };
