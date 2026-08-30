  const pruneCodexConversationFromCacheValue = (value, conversationId, visitedObjects = new WeakSet()) => {
    const normalizedConversationId = normalizeCodexConversationId(conversationId);
    if (!normalizedConversationId) return { value, changed: false };
    if (Array.isArray(value)) {
      let changed = false;
      const nextValue = [];
      for (const item of value) {
        if (typeof item === "string" && normalizeCodexConversationId(item) === normalizedConversationId) {
          changed = true;
          continue;
        }
        if (codexCacheObjectLooksLikeConversation(item) && codexCacheConversationId(item) === normalizedConversationId) {
          changed = true;
          continue;
        }
        const prunedItem = pruneCodexConversationFromCacheValue(item, normalizedConversationId, visitedObjects);
        if (prunedItem.changed) changed = true;
        nextValue.push(prunedItem.value);
      }
      return { value: changed ? nextValue : value, changed };
    }
    if (!isPlainCodexCacheObject(value)) return { value, changed: false };
    if (visitedObjects.has(value)) return { value, changed: false };
    visitedObjects.add(value);
    let nextObject = null;
    for (const [key, childValue] of Object.entries(value)) {
      const prunedChildValue = pruneCodexConversationFromCacheValue(childValue, normalizedConversationId, visitedObjects);
      if (!prunedChildValue.changed) continue;
      if (nextObject === null) nextObject = { ...value };
      nextObject[key] = prunedChildValue.value;
    }
    return nextObject === null
      ? { value, changed: false }
      : { value: nextObject, changed: true };
  };
