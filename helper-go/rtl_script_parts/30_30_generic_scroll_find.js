  const findScrollContainer = () => {
    if (isAntigravityNativeDocument()) {
      const antigravityScrollContainer = findAntigravityScrollContainer();
      if (antigravityScrollContainer) return antigravityScrollContainer;
    }
    const preferredScrollContainer =
      document.querySelector(".thread-scroll-container") ||
      document.querySelector('[class*="react-scroll-to-bottom"]');
    if (isScrollableElement(preferredScrollContainer)) return preferredScrollContainer;
    return [...document.querySelectorAll("main,section,div")].find(isScrollableElement) ||
      document.scrollingElement ||
      document.documentElement;
  };
