  const compactText = (value) => String(value || "").replace(/^\s*/, "").replace(/\s*$/, "").replace(/\s+/g, " ");
  const compactCodexConversationId = (value) => {
    const conversationId = compactText(value);
    if (!conversationId) return "";
    return conversationId.startsWith("local:") ? conversationId.slice("local:".length) : conversationId;
  };
  const codexConversationIdFromRecord = (conversation) =>
    [
      conversation?.id,
      conversation?.threadId,
      conversation?.conversationId,
      conversation?.key,
      conversation?.thread?.id,
      conversation?.conversation?.id,
    ].map(compactCodexConversationId).find(Boolean) || "";
  const codexConversationTitleFromRecord = (conversation) =>
    [
      conversation?.title,
      conversation?.threadName,
      conversation?.thread?.title,
      conversation?.conversation?.title,
    ].map(compactText).find(Boolean) || "";
  const codexConversationTurnsFromTurnHistory = (turnHistory) => {
    if (!turnHistory) return [];
    const history = turnHistory.history;
    if (!history || typeof history !== "object") {
      throw new Error("Codex turnHistory is missing history.");
    }
    if (!history.entitiesByKey || typeof history.entitiesByKey !== "object" || Array.isArray(history.entitiesByKey)) {
      throw new Error("Codex turnHistory is missing entitiesByKey.");
    }
    if (!Array.isArray(history.islands)) {
      throw new Error("Codex turnHistory is missing islands.");
    }
    const orderedTurns = [];
    const seenEntityKeys = new Set();
    for (const island of history.islands) {
      if (!Array.isArray(island?.entries)) {
        throw new Error("Codex turnHistory island is missing entries.");
      }
      for (const entry of island.entries) {
        const entityKey = compactText(entry?.value || entry?.key);
        if (!entityKey || seenEntityKeys.has(entityKey)) continue;
        const turn = history.entitiesByKey[entityKey];
        if (!turn || typeof turn !== "object" || !Array.isArray(turn.items)) {
          throw new Error("Codex turnHistory references an invalid turn entity: " + entityKey);
        }
        seenEntityKeys.add(entityKey);
        orderedTurns.push(turn);
      }
    }
    return orderedTurns;
  };
  const codexConversationTurnsFromRecord = (conversation) => {
    const directTurns = [
      conversation?.turns,
      conversation?.thread?.turns,
      conversation?.conversation?.turns,
    ].find((turns) => Array.isArray(turns) && turns.length > 0);
    if (directTurns) return directTurns;
    const turnHistory = [
      conversation?.turnHistory,
      conversation?.thread?.turnHistory,
      conversation?.conversation?.turnHistory,
    ].find((candidate) => candidate && typeof candidate === "object");
    return codexConversationTurnsFromTurnHistory(turnHistory);
  };
  const codexNativeUnreadStateFromConversationRecord = (conversation) => {
    const hasUnreadTurnValues = [
      conversation?.hasUnreadTurn,
      conversation?.thread?.hasUnreadTurn,
      conversation?.conversation?.hasUnreadTurn,
    ].filter((value) => typeof value === "boolean");
    const unreadMessageCountValues = [
      conversation?.unreadMessageCount,
      conversation?.thread?.unreadMessageCount,
      conversation?.conversation?.unreadMessageCount,
    ].filter(Number.isFinite);
    return {
      isKnown: hasUnreadTurnValues.length > 0 || unreadMessageCountValues.length > 0,
      hasUnreadTurn: hasUnreadTurnValues.some(Boolean) ||
        unreadMessageCountValues.some((unreadMessageCount) => unreadMessageCount > 0),
    };
  };
  const codexItemIsAgentReply = (item) =>
    item?.type === "agentMessage" ||
    item?.type === "assistant-message" ||
    item?.role === "assistant" ||
    item?.author?.role === "assistant";
  const codexItemIsFinalAgentReply = (item) =>
    codexItemIsAgentReply(item) && (!item?.phase || item.phase === "final_answer");
  const codexLatestCompletedAgentReplyFromConversationRecord = (conversation) => {
    const turns = codexConversationTurnsFromRecord(conversation);
    for (let turnIndex = turns.length - 1; turnIndex >= 0; turnIndex -= 1) {
      const turn = turns[turnIndex];
      if (turn?.status !== "completed" || !Array.isArray(turn.items)) continue;
      for (let itemIndex = turn.items.length - 1; itemIndex >= 0; itemIndex -= 1) {
        const item = turn.items[itemIndex];
        if (!codexItemIsFinalAgentReply(item)) continue;
        const turnId = compactText(turn.turnId || turn.id);
        const itemId = compactText(item.id);
        const occurredAtMs = Number(turn.finalAssistantStartedAtMs || turn.turnStartedAtMs);
        if (!turnId || !itemId || !Number.isFinite(occurredAtMs) || occurredAtMs <= 0) {
          throw new Error("Codex completed agent reply is missing its identity or timestamp.");
        }
        return {
          activityKey: ["agent-reply", turnId, itemId].join(":"),
          occurredAtMs,
          isAgentReply: true,
        };
      }
    }
    return { activityKey: "", occurredAtMs: 0, isAgentReply: false };
  };
