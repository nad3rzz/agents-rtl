  const closeCodexConversationConfirmation = () => {
    document.getElementById(CODEX_CHAT_CONFIRMATION_ID)?.remove();
  };
  const closeCodexConversationConfirmationUnlessOpenedFromList = () => {
    const confirmationElement = document.getElementById(CODEX_CHAT_CONFIRMATION_ID);
    if (!confirmationElement || codexTransientElementWasOpenedFromList(confirmationElement)) return;
    confirmationElement.remove();
  };
  const positionCodexConversationConfirmation = (confirmationElement, anchorElement) => {
    const anchorRect = anchorElement?.getBoundingClientRect?.();
    const confirmationRect = confirmationElement.getBoundingClientRect();
    const viewportMargin = CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX;
    const preferredLeft = anchorRect
      ? anchorRect.left
      : (window.innerWidth - confirmationRect.width) / 2;
    const preferredTop = anchorRect
      ? anchorRect.bottom + CODEX_CHAT_RENAME_EDITOR_OFFSET_PX
      : (window.innerHeight - confirmationRect.height) / 2;
    const left = Math.min(
      Math.max(viewportMargin, preferredLeft),
      Math.max(viewportMargin, window.innerWidth - confirmationRect.width - viewportMargin)
    );
    const top = Math.min(
      Math.max(viewportMargin, preferredTop),
      Math.max(viewportMargin, window.innerHeight - confirmationRect.height - viewportMargin)
    );
    confirmationElement.style.left = Math.round(left) + "px";
    confirmationElement.style.top = Math.round(top) + "px";
  };
  const openCodexConversationConfirmation = ({ anchorElement, title, detail, confirmLabel, cancelLabel = "Cancel", closeOnConfirmStart = false, onConfirm }) => {
    if (!document.body) throw new Error("document.body is unavailable for Codex confirmation");
    closeCodexConversationConfirmation();
    const confirmationElement = document.createElement("form");
    confirmationElement.id = CODEX_CHAT_CONFIRMATION_ID;
    confirmationElement.dataset.agentsRtlSource = codexTransientSourceFromAnchor(anchorElement);
    const titleElement = document.createElement("div");
    titleElement.dataset.agentsRtlConfirmTitle = "1";
    titleElement.textContent = title;
    const detailElement = document.createElement("div");
    detailElement.dataset.agentsRtlConfirmDetail = "1";
    detailElement.textContent = detail;
    const actionsElement = document.createElement("div");
    actionsElement.dataset.agentsRtlConfirmActions = "1";
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = cancelLabel;
    const confirmButton = document.createElement("button");
    confirmButton.type = "submit";
    confirmButton.textContent = confirmLabel;
    confirmationElement.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    }, { capture: true });
    cancelButton.addEventListener("click", (event) => {
      event.preventDefault();
      closeCodexConversationConfirmation();
    });
    confirmationElement.addEventListener("submit", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (confirmationElement.dataset.agentsRtlSubmitting === "1") return;
      confirmationElement.dataset.agentsRtlSubmitting = "1";
      confirmButton.disabled = true;
      cancelButton.disabled = true;
      if (closeOnConfirmStart) {
        closeCodexConversationConfirmation();
      }
      try {
        await onConfirm();
        if (!closeOnConfirmStart) {
          closeCodexConversationConfirmation();
        }
      } catch (error) {
        if (closeOnConfirmStart) {
          globalThis.reportError?.(error);
          return;
        }
        detailElement.dataset.agentsRtlConfirmError = "1";
        detailElement.textContent = "Action failed: " + (error instanceof Error ? error.message : String(error));
        confirmButton.disabled = false;
        cancelButton.disabled = false;
        delete confirmationElement.dataset.agentsRtlSubmitting;
        globalThis.reportError?.(error);
      }
    });
    actionsElement.append(cancelButton, confirmButton);
    confirmationElement.append(titleElement, detailElement, actionsElement);
    document.body.append(confirmationElement);
    positionCodexConversationConfirmation(confirmationElement, anchorElement);
    confirmButton.focus();
  };
