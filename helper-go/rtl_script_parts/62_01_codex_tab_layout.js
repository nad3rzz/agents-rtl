  let codexTabTextMeasurementContext = null;
  const requireCodexTabTextMeasurementContext = () => {
    if (codexTabTextMeasurementContext) return codexTabTextMeasurementContext;
    const measurementCanvas = document.createElement("canvas");
    const measurementContext = measurementCanvas.getContext("2d");
    if (!measurementContext) throw new Error("Cannot create a Codex tab text measurement context.");
    measurementContext.font = CODEX_CHAT_TAB_MEASUREMENT_FONT;
    codexTabTextMeasurementContext = measurementContext;
    return codexTabTextMeasurementContext;
  };
  const codexConversationEstimatedTabWidth = (
    conversation,
    pendingApprovalTitleSet,
    unreadConversationIds
  ) => {
    const measurementContext = requireCodexTabTextMeasurementContext();
    let estimatedWidth = Math.ceil(measurementContext.measureText(conversation.title).width) +
      CODEX_CHAT_TAB_HORIZONTAL_CHROME_PX;
    if (codexConversationNeedsApproval(conversation, pendingApprovalTitleSet)) {
      estimatedWidth += CODEX_CHAT_APPROVAL_BADGE_TOTAL_WIDTH_PX;
    }
    if (unreadConversationIds.has(conversation.id)) {
      estimatedWidth += CODEX_CHAT_UNREAD_BADGE_TOTAL_WIDTH_PX;
    }
    return Math.min(
      CODEX_CHAT_TAB_MAXIMUM_WIDTH_PX,
      Math.max(CODEX_CHAT_TAB_MINIMUM_WIDTH_PX, estimatedWidth)
    );
  };
  const codexTabsAvailableWidth = (headerHost) => {
    const headerWidth = Math.floor(headerHost.getBoundingClientRect().width);
    if (headerWidth <= 0) throw new Error("Codex tabs header has no measurable width.");
    return Math.max(
      CODEX_CHAT_TAB_MINIMUM_WIDTH_PX,
      headerWidth - CODEX_CHAT_HEADER_TITLE_RESERVED_WIDTH_PX - CODEX_CHAT_TABS_MARGIN_INLINE_START_PX
    );
  };
  const codexConversationsPrioritizedForVisibility = (conversations, activeConversationId) => {
    const prioritizedConversations = [];
    for (const conversation of conversations) {
      if (conversation.id === activeConversationId) {
        prioritizedConversations.push(conversation);
        break;
      }
    }
    for (const conversation of conversations) {
      if (conversation.id !== activeConversationId) prioritizedConversations.push(conversation);
    }
    return prioritizedConversations;
  };
  const calculateVisibleCodexConversationLimit = (
    conversations,
    activeConversationId,
    headerHost,
    pendingApprovalTitleSet,
    unreadConversationIds
  ) => {
    if (conversations.length === 0) return 0;
    const prioritizedConversations = codexConversationsPrioritizedForVisibility(
      conversations,
      activeConversationId
    );
    const availableWidth = codexTabsAvailableWidth(headerHost);
    let visibleConversationCount = 0;
    let occupiedWidth = 0;
    for (let conversationIndex = 0; conversationIndex < prioritizedConversations.length; conversationIndex += 1) {
      const conversation = prioritizedConversations[conversationIndex];
      const tabWidth = codexConversationEstimatedTabWidth(
        conversation,
        pendingApprovalTitleSet,
        unreadConversationIds
      );
      const gapBeforeTab = visibleConversationCount > 0 ? CODEX_CHAT_TAB_GAP_PX : 0;
      const conversationsRemain = conversationIndex < prioritizedConversations.length - 1;
      const overflowReservation = conversationsRemain
        ? CODEX_CHAT_TAB_GAP_PX + CODEX_CHAT_OVERFLOW_BUTTON_WIDTH_PX
        : 0;
      const requiredWidth = occupiedWidth + gapBeforeTab + tabWidth + overflowReservation;
      if (visibleConversationCount > 0 && requiredWidth > availableWidth) break;
      occupiedWidth += gapBeforeTab + tabWidth;
      visibleConversationCount += 1;
    }
    return visibleConversationCount;
  };
  const splitVisibleCodexConversations = (conversations, activeConversationId, visibleConversationLimit) => {
    if (!Number.isInteger(visibleConversationLimit) || visibleConversationLimit < 1) {
      throw new Error("Visible Codex conversation limit must be a positive integer.");
    }
    const prioritizedConversations = codexConversationsPrioritizedForVisibility(
      conversations,
      activeConversationId
    );
    const visibleConversationIdSet = new Set();
    for (let conversationIndex = 0;
      conversationIndex < visibleConversationLimit && conversationIndex < prioritizedConversations.length;
      conversationIndex += 1) {
      visibleConversationIdSet.add(prioritizedConversations[conversationIndex].id);
    }
    const visibleConversations = [];
    const overflowConversations = [];
    for (const conversation of conversations) {
      if (visibleConversationIdSet.has(conversation.id)) {
        visibleConversations.push(conversation);
      } else {
        overflowConversations.push(conversation);
      }
    }
    return { visibleConversations, overflowConversations };
  };
