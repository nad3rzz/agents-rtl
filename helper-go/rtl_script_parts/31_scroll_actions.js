  let activeScrollIntervalId = null;
  const scrollChatBy = (deltaY) => {
    if (scrollNativeChatBy(deltaY)) return;
    const scrollContainer = findScrollContainer();
    if (
      scrollContainer === document.scrollingElement ||
      scrollContainer === document.documentElement ||
      scrollContainer === document.body
    ) {
      window.scrollBy({ top: deltaY, behavior: "auto" });
      return;
    }
    scrollContainer.scrollTop += deltaY;
  };
  const scrollChatStep = (direction) => scrollChatBy(SCROLL_DELTA_PX * direction);
  const stopContinuousScroll = () => {
    if (activeScrollIntervalId === null) return;
    clearInterval(activeScrollIntervalId);
    activeScrollIntervalId = null;
  };
  const startContinuousScroll = (direction) => {
    stopContinuousScroll();
    activeScrollIntervalId = setInterval(() => scrollChatStep(direction), CONTINUOUS_SCROLL_INTERVAL_MS);
  };
