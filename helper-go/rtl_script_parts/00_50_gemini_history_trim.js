  const trimGeminiHistoryPayload = (messageData) => {
    if (!messageData || typeof messageData !== "object") return;
    if (!GEMINI_HISTORY_MESSAGE_TYPES.has(messageData.type)) return;
    if (!Array.isArray(messageData.history)) return;
    if (messageData.history.length <= GEMINI_HISTORY_KEEP_COUNT) return;
    messageData.history = messageData.history.slice(-GEMINI_HISTORY_KEEP_COUNT);
  };
  const removeGeminiHistoryTrim = () => {
    const state = window[KEY];
    if (!state?.geminiHistoryTrimOriginalInvokes) return;
    state.geminiHistoryTrimOriginalInvokes.forEach(({ task, originalInvoke }) => {
      if (task && typeof originalInvoke === "function") task.invoke = originalInvoke;
    });
    state.geminiHistoryTrimOriginalInvokes = [];
    state.geminiHistoryTrimWrappedTasks = new WeakSet();
    state.geminiHistoryTrimInstalled = false;
  };
  const installGeminiHistoryTrim = () => {
    const state = window[KEY];
    if (!state) return;
    if (!GEMINI_HISTORY_TRIM_ENABLED || !isGeminiCodeAssistDocument()) {
      removeGeminiHistoryTrim();
      return;
    }
    if (!state.geminiHistoryTrimOriginalInvokes) state.geminiHistoryTrimOriginalInvokes = [];
    if (!state.geminiHistoryTrimWrappedTasks) state.geminiHistoryTrimWrappedTasks = new WeakSet();
    const messageTasks = window[getZoneSymbolName("messagefalse")] || window.__zone_symbol__messagefalse || [];
    messageTasks.forEach((task) => {
      if (!task || typeof task.invoke !== "function") return;
      if (state.geminiHistoryTrimWrappedTasks.has(task)) return;
      const originalInvoke = task.invoke;
      state.geminiHistoryTrimWrappedTasks.add(task);
      state.geminiHistoryTrimOriginalInvokes.push({ task, originalInvoke });
      task.invoke = function(...args) {
        trimGeminiHistoryPayload(getGeminiMessageData(args));
        return originalInvoke.apply(this, args);
      };
    });
    state.geminiHistoryTrimInstalled = state.geminiHistoryTrimOriginalInvokes.length > 0;
  };
