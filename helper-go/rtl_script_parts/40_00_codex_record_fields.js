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
  const codexConversationTurnsFromRecord = (conversation) =>
    [
      conversation?.turns,
      conversation?.thread?.turns,
      conversation?.conversation?.turns,
    ].find(Array.isArray) || [];
  const codexLastActivityFromConversationRecord = (conversation) => {
    const turns = codexConversationTurnsFromRecord(conversation);
    const lastTurn = turns.at(-1) || null;
    const lastItems = Array.isArray(lastTurn?.items) ? lastTurn.items : [];
    const lastItem = lastItems.at(-1) || null;
    const lastItemType = compactText(lastItem?.type || "");
    const activityKey = [
      turns.length,
      lastTurn?.turnId || lastTurn?.id || "",
      lastTurn?.status || "",
      lastItem?.id || "",
      lastItemType,
    ].map(compactText).join(":");
    return {
      activityKey: activityKey === "::::" ? "" : activityKey,
      isAgentReply: lastItemType === "agentMessage" ||
        lastItemType === "assistant-message" ||
        lastItem?.role === "assistant" ||
        lastItem?.author?.role === "assistant",
    };
  };
