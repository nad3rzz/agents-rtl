  const findAntigravityScrollContainer = () => {
    const rootCandidates = [
      getAntigravityConversation(),
      getAntigravityAgentPanel(),
      document.querySelector('[class*="react-scroll-to-bottom"]'),
      document.querySelector("[data-content-search-unit-key]"),
    ].filter(Boolean);
    for (const rootCandidate of rootCandidates) {
      let currentElement = rootCandidate;
      while (currentElement && currentElement !== document.body) {
        if (isScrollableElement(currentElement)) return currentElement;
        currentElement = currentElement.parentElement;
      }
    }
    return [...document.querySelectorAll("div,main,section")]
      .filter((element) => {
        if (!isScrollableElement(element)) return false;
        const rect = element.getBoundingClientRect();
        return rect.height > 180 && rect.width > 240;
      })
      .sort((leftElement, rightElement) =>
        (rightElement.scrollHeight - rightElement.clientHeight) - (leftElement.scrollHeight - leftElement.clientHeight)
      )[0] || null;
  };
  const findAntigravityScrollAnchor = () =>
    findAntigravityScrollContainer() ||
    getAntigravityConversation()?.querySelector("[class*='overflow-y-auto']") ||
    getAntigravityConversation() ||
    getAntigravityAgentPanel();
