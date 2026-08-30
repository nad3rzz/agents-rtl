  const shouldInstallControls = () =>
    !isWorkbenchDocument() ||
    Boolean(getNativeChatPanel()) ||
    isAntigravityNativeDocument();
