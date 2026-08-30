  const storedCodexPendingApprovalTitles = () => {
    const storedValue = localStorage.getItem(CODEX_PENDING_APPROVAL_TITLES_STORAGE_KEY);
    if (storedValue === null) return [];
    const parsedValue = JSON.parse(storedValue);
    if (!Array.isArray(parsedValue)) return [];
    return parsedValue.map(compactText).filter(Boolean);
  };
  const saveCodexPendingApprovalTitles = (titles) => {
    const uniqueTitles = [...new Set(titles.map(compactText).filter(Boolean))];
    localStorage.setItem(CODEX_PENDING_APPROVAL_TITLES_STORAGE_KEY, JSON.stringify(uniqueTitles));
    return uniqueTitles;
  };
