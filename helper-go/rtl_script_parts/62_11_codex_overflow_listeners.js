  const removeCodexOverflowListeners = () => {
    const state = window[KEY];
    if (!state) return;
    if (state.codexOverflowPointerdownListener) document.removeEventListener("pointerdown", state.codexOverflowPointerdownListener, true);
    if (state.codexOverflowKeydownListener) window.removeEventListener("keydown", state.codexOverflowKeydownListener, true);
    if (state.codexOverflowResizeListener) window.removeEventListener("resize", state.codexOverflowResizeListener, true);
    if (state.codexOverflowScrollListener) window.removeEventListener("scroll", state.codexOverflowScrollListener, true);
    state.codexOverflowPointerdownListener = null;
    state.codexOverflowKeydownListener = null;
    state.codexOverflowResizeListener = null;
    state.codexOverflowScrollListener = null;
  };
  const installCodexOverflowListeners = () => {
    removeCodexOverflowListeners();
    const pointerdownListener = (event) => {
      const menuElement = document.getElementById(CODEX_CHAT_OVERFLOW_MENU_ID);
      if (!menuElement) return;
      if (menuElement.contains(event.target)) return;
      if (eventPointIsInsideElement(event, menuElement)) return;
      if (event.target?.closest?.("#" + CODEX_CHAT_TABS_BAR_ID + " ." + CODEX_CHAT_OVERFLOW_BUTTON_CLASS_NAME)) return;
      closeCodexOverflowMenu();
    };
    const keydownListener = (event) => {
      if (event.key === "Escape") closeCodexOverflowMenu();
    };
    const resizeListener = () => closeCodexOverflowMenu();
    const scrollListener = (event) => {
      const menuElement = document.getElementById(CODEX_CHAT_OVERFLOW_MENU_ID);
      if (!menuElement) return;
      if (event.target && (event.target === menuElement || menuElement.contains(event.target))) return;
      closeCodexOverflowMenu();
    };
    document.addEventListener("pointerdown", pointerdownListener, true);
    window.addEventListener("keydown", keydownListener, true);
    window.addEventListener("resize", resizeListener, true);
    window.addEventListener("scroll", scrollListener, true);
    if (window[KEY]) {
      window[KEY].codexOverflowPointerdownListener = pointerdownListener;
      window[KEY].codexOverflowKeydownListener = keydownListener;
      window[KEY].codexOverflowResizeListener = resizeListener;
      window[KEY].codexOverflowScrollListener = scrollListener;
    }
  };
