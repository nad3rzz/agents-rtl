  const dispatchNativeChatWheel = (target, deltaY, eventInit) => {
    for (let eventIndex = 0; eventIndex < NATIVE_CHAT_WHEEL_EVENT_COUNT; eventIndex += 1) {
      target.dispatchEvent(new WheelEvent("wheel", { ...eventInit, deltaY }));
    }
  };
  const scrollNativeChatBy = (deltaY) => {
    const scrollContainer = findNativeChatScrollContainer();
    if (!scrollContainer) return false;
    const nativeChatPanel = getNativeChatPanel();
    const chatList = scrollContainer.closest(".monaco-list") || nativeChatPanel?.querySelector(NATIVE_CHAT_LIST_SELECTOR) || scrollContainer;
    if (!chatList) return false;
    const direction = Math.sign(deltaY);
    if (direction === 0) return true;
    const scrollContainerRect = scrollContainer.getBoundingClientRect();
    const eventInit = {
      bubbles: true,
      cancelable: true,
      view: window,
      deltaX: 0,
      deltaMode: 0,
      clientX: Math.round(scrollContainerRect.left + Math.min(20, scrollContainerRect.width / 2)),
      clientY: Math.round(scrollContainerRect.top + Math.min(120, scrollContainerRect.height / 2)),
    };
    const wheelDeltaY = -direction * NATIVE_CHAT_WHEEL_DELTA_PX;
    dispatchNativeChatWheel(scrollContainer, wheelDeltaY, eventInit);
    dispatchNativeChatWheel(chatList, wheelDeltaY, eventInit);
    return true;
  };
