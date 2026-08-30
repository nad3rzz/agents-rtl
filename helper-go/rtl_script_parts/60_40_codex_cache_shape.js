  const isPlainCodexCacheObject = (value) =>
    value !== null &&
    typeof value === "object" &&
    Object.prototype.toString.call(value) === "[object Object]";
  const codexCacheConversationId = (value) => {
    if (!isPlainCodexCacheObject(value)) return "";
    return [
      value.id,
      value.threadId,
      value.conversationId,
      value.key,
      value.thread?.id,
      value.conversation?.id,
      value.item?.id,
      value.item?.conversationId,
      value.item?.conversation?.id,
    ].map(normalizeCodexConversationId).find(Boolean) || "";
  };
  const codexCacheObjectLooksLikeConversation = (value) =>
    Boolean(codexCacheConversationId(value)) &&
    (
      typeof value.title === "string" ||
      typeof value.threadName === "string" ||
      typeof value.cwd === "string" ||
      Array.isArray(value.turns) ||
      Boolean(value.threadRuntimeStatus) ||
      isPlainCodexCacheObject(value.thread) ||
      isPlainCodexCacheObject(value.conversation)
    );
