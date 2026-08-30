  const isVisibleElement = (element) => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const isVisibleViewportElement = (element) => {
    if (!isVisibleElement(element)) return false;
    const rect = element.getBoundingClientRect();
    return rect.right > 0 && rect.left < window.innerWidth && rect.bottom > 0 && rect.top < window.innerHeight;
  };
  const getVisibleViewportRect = (element) => {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    if (rect.right <= 0 || rect.left >= window.innerWidth || rect.bottom <= 0 || rect.top >= window.innerHeight) return null;
    const style = getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") return null;
    return rect;
  };
  const elementHasReadableOwnText = (element) => [...element.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.nodeValue || "")
    .join(" ")
    .trim().length > 1;
  const shouldManageAntigravityTextElement = (element) => {
    if (!isVisibleElement(element)) return false;
    if (element.closest("[id='" + ANTIGRAVITY_INPUT_BOX_ID + "']")) return false;
    if (element.closest(CODE_LIKE_SELECTOR + ",button,[role='button'],#" + CONTROL_BAR_ID)) return false;
    const textContent = (element.innerText || element.textContent || "").trim();
    if (textContent.length < 2) return false;
    if (element.children.length > 0 && !elementHasReadableOwnText(element)) return false;
    return /[\u0600-\u06FFA-Za-z]/.test(textContent);
  };
  const shouldManageGeminiTextElement = (element) => {
    if (!isVisibleElement(element)) return false;
    if (element.closest(".chat-submit-input,[contenteditable='plaintext-only']")) return false;
    if (element.closest(CODE_LIKE_SELECTOR + ",button,[role='button'],mat-icon,#" + CONTROL_BAR_ID + ",#" + GEMINI_CONTROL_SLOT_ID)) return false;
    const textContent = (element.innerText || element.textContent || "").trim();
    if (textContent.length < 2) return false;
    if (element.children.length > 0 && !elementHasReadableOwnText(element)) return false;
    return /[\u0600-\u06FFA-Za-z]/.test(textContent);
  };
  const clearHorizontalScroll = () => {
    [
      document.scrollingElement,
      document.documentElement,
      document.body,
      document.querySelector(".thread-scroll-container"),
      document.querySelector('[class*="react-scroll-to-bottom"]'),
      getNativeChatPanel(),
      getAntigravityConversation(),
      getAntigravityAgentPanel(),
      getAntigravityInputBox(),
      isAntigravityNativeDocument() ? findAntigravityScrollContainer() : null,
    ].filter(Boolean).forEach((element) => {
      element.scrollLeft = 0;
    });
  };
  const clearHorizontalScrollSoon = () => {
    clearHorizontalScroll();
    requestAnimationFrame(clearHorizontalScroll);
    requestAnimationFrame(() => requestAnimationFrame(clearHorizontalScroll));
    [50, 120, 240].forEach((delay) => setTimeout(clearHorizontalScroll, delay));
  };
