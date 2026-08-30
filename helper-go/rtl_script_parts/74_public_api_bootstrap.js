  window[KEY] = {
    installed: true,
    version: SCRIPT_VERSION,
    stopped: !initialRtlEnabled,
    scrollButtonsEnabled: initialScrollButtonsEnabled,
    codexResourceMonitorVisible: initialCodexResourceMonitorVisible,
    codexResourceMonitorResetRequestId: initialCodexResourceMonitorResetRequestId,
    apply,
    start,
    stop,
    toggle,
    toggleScrollButtons,
    toggleCodexResourceMonitorVisibility,
    resetCodexResourceMonitorTotals,
    updateCodexResourceMonitor,
    codexConversations: sanitizeCodexConversations(),
    updateCodexConversations,
    renderCodexChatTabs,
    applyCodexConversationListRenameControls,
    removeCodexConversationListRenameControls,
    openCodexConversationListRenameEditorForButton,
    installCodexConversationListRenameListeners,
    removeCodexConversationListRenameListeners,
    installCodexTransientListeners,
    removeCodexTransientListeners,
    updateCodexPendingApprovalRefreshTimer,
    removeCodexPendingApprovalRefreshTimer,
    installStyle,
    installControlButtons,
    installFloatingButtons,
    removeFloatingButtons,
    syncScrollButtons,
    installGeminiHistoryTrim,
    removeGeminiHistoryTrim,
    updateControlButtons,
    disconnectApplyObserver,
    installSelectAllFix,
    removeSelectAllFix,
    installAntigravityNativeEnterFallback,
    removeAntigravityNativeEnterFallback,
    installCodexOverflowListeners,
    removeCodexOverflowListeners,
    selectAllFixKeydownListener: null,
    antigravityNativeEnterFallbackKeydownListener: null,
    codexOverflowPointerdownListener: null,
    codexOverflowKeydownListener: null,
    codexOverflowResizeListener: null,
    codexOverflowScrollListener: null,
    codexConversationListRenameDocumentListener: null,
    codexTransientPointerdownListener: null,
    codexTransientKeydownListener: null,
    codexPendingApprovalRefreshIntervalId: null,
    codexReactQueryClient: null,
    codexPendingApprovalConversationIds: [],
    applyMutationObserver: null,
    geminiHistoryTrimInstalled: false,
    geminiHistoryTrimOriginalInvokes: [],
    geminiHistoryTrimWrappedTasks: new WeakSet(),
  };
  installSelectAllFix();
  installAntigravityNativeEnterFallback();
  installCodexOverflowListeners();
  installCodexConversationListRenameListeners();
  installCodexTransientListeners();
  installGeminiHistoryTrim();
  installStyle();
  installControlButtons();
  syncScrollButtons();
  if (initialRtlEnabled) {
    start();
  } else {
    stop();
  }
})();
