  const isAntigravityNativeSelectionTarget = (element) => {
    const inputBox = getAntigravityInputBox();
    if (!inputBox || !element) return false;
    if (!(inputBox === element || inputBox.contains(element) || element.closest?.("[id='" + ANTIGRAVITY_INPUT_BOX_ID + "']"))) {
      return false;
    }
    return Boolean(
      element.tagName === "TEXTAREA" ||
      element.tagName === "INPUT" ||
      element.isContentEditable ||
      element.getAttribute?.("role") === "textbox" ||
      element.closest?.("[contenteditable],textarea,input,[role='textbox']")
    );
  };
  const createSelectAllFixKeydownListener = () => (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key?.toLowerCase() !== "a" && event.code !== "KeyA") return;
    if (!isAntigravityNativeSelectionTarget(document.activeElement)) return;
    event.stopPropagation();
  };
  const removeSelectAllFix = () => {
    const listener = window[KEY]?.selectAllFixKeydownListener;
    if (!listener) return;
    window.removeEventListener("keydown", listener, true);
    window[KEY].selectAllFixKeydownListener = null;
  };
  const installSelectAllFix = () => {
    removeSelectAllFix();
    if (!isAntigravityNativeDocument()) return;
    const listener = createSelectAllFixKeydownListener();
    window.addEventListener("keydown", listener, true);
    if (window[KEY]) window[KEY].selectAllFixKeydownListener = listener;
  };
