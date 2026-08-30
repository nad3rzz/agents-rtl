  const storedBoolean = (storageKey, defaultValue) => {
    const storedValue = localStorage.getItem(storageKey);
    if (storedValue === null) return defaultValue;
    return storedValue === "1";
  };
  const saveBoolean = (storageKey, value) => localStorage.setItem(storageKey, value ? "1" : "0");
