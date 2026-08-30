  const findGeminiControlHost = () => {
    if (!isGeminiCodeAssistDocument()) return null;
    const existingSlot = document.getElementById(GEMINI_CONTROL_SLOT_ID);
    let slot = existingSlot;
    const contextDrawer = [...document.querySelectorAll("context-drawer")]
      .filter(isVisibleElement)[0] || document.querySelector("context-drawer");
    if (contextDrawer) {
      if (!slot) {
        slot = document.createElement("div");
        slot.id = GEMINI_CONTROL_SLOT_ID;
      }
      const drawerHeader = contextDrawer.querySelector(".context-drawer-header");
      if (drawerHeader?.parentElement === contextDrawer) {
        if (slot.parentElement !== contextDrawer || slot.previousElementSibling !== drawerHeader) drawerHeader.after(slot);
      } else if (slot.parentElement !== contextDrawer) {
        contextDrawer.prepend(slot);
      }
      return { host: slot, wrapInActionItem: false, context: "gemini" };
    }
    const inputBox = document.querySelector(".input-box.input-box-new") || document.querySelector(".input-box");
    if (!inputBox) return null;
    if (!slot) {
      slot = document.createElement("div");
      slot.id = GEMINI_CONTROL_SLOT_ID;
    }
    const buttonContainer = inputBox.querySelector(".button-container");
    if (buttonContainer?.parentElement === inputBox) {
      if (slot.parentElement !== inputBox || slot.nextElementSibling !== buttonContainer) inputBox.insertBefore(slot, buttonContainer);
    } else if (slot.parentElement !== inputBox) {
      inputBox.append(slot);
    }
    return { host: slot, wrapInActionItem: false, context: "gemini" };
  };
