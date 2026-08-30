  const getAntigravityNativeInputElement = () =>
    getAntigravityInputBox()?.querySelector("[role='textbox']") || null;
  const getAntigravityNativeInputText = () => {
    const inputElement = getAntigravityNativeInputElement();
    return compactText(inputElement?.innerText || inputElement?.textContent || "");
  };
  const getAntigravityNativeSubmitButton = () =>
    [...(getAntigravityInputBox()?.querySelectorAll("button") || [])]
      .find((button) => ANTIGRAVITY_NATIVE_SUBMIT_BUTTON_LABELS.has(button.getAttribute("aria-label") || ""));
  const isAntigravityNativeInputEventTarget = (target) => {
    const inputElement = getAntigravityNativeInputElement();
    return Boolean(inputElement && target instanceof Element && (target === inputElement || inputElement.contains(target)));
  };
  const createAntigravityNativeEnterFallbackKeydownListener = () => (event) => {
    if (!isAntigravityNativeDocument()) return;
    if (event.key !== "Enter") return;
    if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.repeat || event.isComposing) return;
    if (!isAntigravityNativeInputEventTarget(event.target)) return;
    const expectedText = getAntigravityNativeInputText();
    if (!expectedText) return;
    setTimeout(() => {
      if (!isAntigravityNativeDocument()) return;
      if (getAntigravityNativeInputText() !== expectedText) return;
      const submitButton = getAntigravityNativeSubmitButton();
      if (!submitButton || submitButton.disabled || submitButton.getAttribute("aria-disabled") === "true") return;
      submitButton.click();
    }, ANTIGRAVITY_NATIVE_ENTER_FALLBACK_DELAY_MS);
  };
  const removeAntigravityNativeEnterFallback = () => {
    const listener = window[KEY]?.antigravityNativeEnterFallbackKeydownListener;
    if (!listener) return;
    window.removeEventListener("keydown", listener, true);
    window[KEY].antigravityNativeEnterFallbackKeydownListener = null;
  };
  const installAntigravityNativeEnterFallback = () => {
    removeAntigravityNativeEnterFallback();
    if (!isAntigravityNativeDocument()) return;
    const listener = createAntigravityNativeEnterFallbackKeydownListener();
    window.addEventListener("keydown", listener, true);
    if (window[KEY]) window[KEY].antigravityNativeEnterFallbackKeydownListener = listener;
  };
