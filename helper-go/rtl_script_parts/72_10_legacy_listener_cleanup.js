  window[KEY]?.removeSelectAllFix?.();
  window[KEY]?.removeAntigravityNativeEnterFallback?.();
  window[KEY]?.removeCodexOverflowListeners?.();
  window[KEY]?.removeCodexConversationListRenameListeners?.();
  window[KEY]?.removeCodexTransientListeners?.();
  window[KEY]?.removeCodexConversationListRenameControls?.();
  window[KEY]?.removeCodexPendingApprovalRefreshTimer?.();
  window[KEY]?.removeGeminiHistoryTrim?.();
  window[KEY]?.disconnectApplyObserver?.();
  window[KEY]?.stop?.();
  [
    "__agentsRtlToolbarSlotDryInterval",
    "__agentsRtlInlineDryInterval",
    "__agentsRtlToolbarMiddleDryInterval",
    "__agentsRtlEdgeButtonsDryInterval",
    "__agentsRtlNativeDryInterval",
    "__agentsRtlAntigravityNativeDryInterval",
  ].forEach((intervalName) => {
    clearInterval(window[intervalName]);
    window[intervalName] = null;
  });
  window.__agentsRtlAntigravityLegacyDryLayer?.cleanup?.();
  window.__agentsRtlAntigravityLegacyDryLayer = null;
  window.__agentsRtlAntigravityNativeDry = null;
  window.__agentsRtlNativeVscodeComposerDry?.stop?.();
  window.__agentsRtlNativeVscodeComposerDry = null;
  window.__agentsRtlNativeVscodeComposerDry2?.stop?.();
  window.__agentsRtlNativeVscodeComposerDry2 = null;
  window.__agentsRtlResponseAnnotationRtlDry?.stop?.();
  window.__agentsRtlResponseAnnotationRtlDry = null;
