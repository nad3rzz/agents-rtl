  const createCodexConversationRenameButton = (conversation) => {
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.className = CODEX_CHAT_RENAME_BUTTON_CLASS_NAME;
    renameButton.textContent = "\u270E";
    renameButton.title = "Rename tab";
    renameButton.setAttribute("aria-label", "Rename Codex chat tab");
    renameButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openCodexConversationRenameEditor(conversation, renameButton);
    }, { capture: true });
    return renameButton;
  };
  const setCodexClipboardButtonFeedback = (button, feedbackText) => {
    const originalText = button.textContent;
    button.textContent = feedbackText;
    setTimeout(() => { button.textContent = originalText; }, CODEX_CLIPBOARD_FEEDBACK_DURATION_MS);
  };
  const copyCodexTextWithButtonFeedback = (button, text, description) => {
    if (typeof text !== "string" || text.length === 0) {
      setCodexClipboardButtonFeedback(button, "❌");
      console.error(new Error("Cannot copy missing " + description + "."));
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      setCodexClipboardButtonFeedback(button, "✔️");
    }).catch((error) => {
      setCodexClipboardButtonFeedback(button, "❌");
      console.error("Agents RTL could not copy " + description + ".", error);
    });
  };
  const personalSessionDoctorScriptPath = () => {
    const scriptPath = window.__agentsRtlPersonalSessionDoctorScriptPath;
    if (scriptPath === undefined || scriptPath === null || scriptPath === "") return "";
    if (typeof scriptPath !== "string" || !scriptPath.startsWith("/")) {
      throw new Error("Invalid personal session Doctor script path.");
    }
    return scriptPath;
  };
  const personalSessionDoctorIsEnabled = () => personalSessionDoctorScriptPath() !== "";
  const quotePosixShellArgument = (value) => "'" + String(value).replaceAll("'", "'\"'\"'") + "'";
  const codexSessionDoctorCommand = (conversation) => {
    const scriptPath = personalSessionDoctorScriptPath();
    if (!scriptPath) throw new Error("Personal session Doctor is not enabled.");
    if (typeof conversation?.path !== "string" || !conversation.path.startsWith("/")) {
      throw new Error("Codex conversation path is missing or invalid.");
    }
    return "python3 " + quotePosixShellArgument(scriptPath) +
      " clean --session " + quotePosixShellArgument(conversation.path) +
      " --apply --allow-open-session";
  };
  const createCodexConversationPathButton = (conversation) => {
    const pathButton = document.createElement("button");
    pathButton.type = "button";
    pathButton.className = CODEX_CHAT_PATH_BUTTON_CLASS_NAME;
    pathButton.textContent = "📋";
    pathButton.title = "Copy conversation path";
    pathButton.setAttribute("aria-label", "Copy Codex conversation path");
    pathButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      copyCodexTextWithButtonFeedback(pathButton, conversation.path, "Codex conversation path");
    }, { capture: true });
    return pathButton;
  };
  const createCodexConversationDoctorButton = (conversation, buttonClassName = CODEX_CHAT_DOCTOR_BUTTON_CLASS_NAME) => {
    if (!personalSessionDoctorIsEnabled()) {
      throw new Error("Cannot create a session Doctor button while the personal integration is disabled.");
    }
    const doctorButton = document.createElement("button");
    doctorButton.type = "button";
    doctorButton.className = buttonClassName;
    doctorButton.dataset.conversationId = conversation.id;
    doctorButton.textContent = "🩺";
    doctorButton.title = "Copy session Doctor command";
    doctorButton.setAttribute("aria-label", "Copy Codex session Doctor command");
    doctorButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      copyCodexTextWithButtonFeedback(
        doctorButton,
        codexSessionDoctorCommand(conversation),
        "Codex session Doctor command"
      );
    }, { capture: true });
    return doctorButton;
  };
  const createCodexConversationActionButtons = (conversation) => {
    const actionButtons = [
      createCodexConversationPathButton(conversation),
      createCodexConversationRenameButton(conversation),
    ];
    if (personalSessionDoctorIsEnabled()) {
      actionButtons.push(createCodexConversationDoctorButton(conversation));
    }
    actionButtons.push(createCodexConversationArchiveButton(conversation));
    return actionButtons;
  };
  const createCodexConversationArchiveButton = (conversation) => {
    const archiveButton = document.createElement("button");
    const archiveIsPending = pendingCodexArchiveConversationIdSet().has(conversation.id);
    archiveButton.type = "button";
    archiveButton.className = CODEX_CHAT_ARCHIVE_BUTTON_CLASS_NAME;
    archiveButton.textContent = archiveIsPending ? "\u2026" : "\u00D7";
    archiveButton.title = archiveIsPending ? "Archive pending" : "Archive tab";
    archiveButton.disabled = archiveIsPending;
    archiveButton.setAttribute("aria-label", "Archive Codex chat tab");
    archiveButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      if (archiveIsPending) return;
      cancelCodexFloatingConversationActionsHide();
      confirmCodexConversationArchive(conversation, archiveButton);
    }, { capture: true });
    return archiveButton;
  };
