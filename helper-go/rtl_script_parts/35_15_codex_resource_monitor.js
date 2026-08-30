  const codexResourceMonitorIsSupported = () =>
    window.__agentsRtlCodexResourceMetrics?.supported === true;
  const createControlToggleContent = (button, labelText) => {
    const label = document.createElement("span");
    label.setAttribute(CONTROL_TOGGLE_LABEL_ATTRIBUTE_NAME, "");
    label.textContent = labelText;
    const track = document.createElement("span");
    track.setAttribute(CONTROL_TOGGLE_TRACK_ATTRIBUTE_NAME, "");
    const thumb = document.createElement("span");
    thumb.setAttribute(CONTROL_TOGGLE_THUMB_ATTRIBUTE_NAME, "");
    track.append(thumb);
    button.replaceChildren(label, track);
    button.setAttribute("role", "switch");
  };
  const setControlToggleState = (button, isActive, title) => {
    if (!button) return;
    setAttributeIfChanged(button, "data-active", isActive ? "1" : "0");
    setAttributeIfChanged(button, "title", title);
    setAttributeIfChanged(button, "aria-checked", isActive ? "true" : "false");
  };
  const formatCodexResourceBytes = (byteCount) => {
    if (!Number.isFinite(byteCount) || byteCount < 0) {
      throw new Error("Codex resource byte count must be a non-negative finite number");
    }
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let unitIndex = 0;
    let displayedValue = byteCount;
    while (displayedValue >= RESOURCE_MONITOR_BYTES_PER_UNIT && unitIndex < units.length - 1) {
      displayedValue /= RESOURCE_MONITOR_BYTES_PER_UNIT;
      unitIndex += 1;
    }
    const decimalPlaces = displayedValue >= 10 || unitIndex === 0 ? 0 : RESOURCE_MONITOR_NUMBER_DECIMAL_PLACES;
    return {
      numericText: displayedValue.toFixed(decimalPlaces),
      unitText: units[unitIndex],
    };
  };
  const formatCodexResourceCPUPercent = (cpuPercent) => {
    if (!Number.isFinite(cpuPercent) || cpuPercent < 0) {
      throw new Error("Codex CPU percentage must be a non-negative finite number");
    }
    return cpuPercent.toFixed(RESOURCE_MONITOR_NUMBER_DECIMAL_PLACES) + "%";
  };
  const createCodexResourceMetric = (metricName, metricLabel, title, usesByteUnit = false) => {
    const metric = document.createElement("span");
    metric.setAttribute(CODEX_RESOURCE_MONITOR_METRIC_ATTRIBUTE_NAME, metricName);
    metric.title = title;
    const label = document.createElement("span");
    label.textContent = metricLabel;
    label.setAttribute("data-agents-rtl-codex-resource-metric-label", "");
    const value = document.createElement("strong");
    value.setAttribute("data-agents-rtl-codex-resource-metric-value", "");
    if (usesByteUnit) {
      const numericValue = document.createElement("span");
      numericValue.setAttribute("data-agents-rtl-codex-resource-metric-number", "");
      const unit = document.createElement("span");
      unit.setAttribute("data-agents-rtl-codex-resource-metric-unit", "");
      value.append(numericValue, unit);
    }
    metric.append(label, value);
    return metric;
  };
  const createCodexResourceMonitorResetButton = () => {
    const resetButton = document.createElement("button");
    resetButton.id = CODEX_RESOURCE_MONITOR_RESET_BUTTON_ID;
    resetButton.type = "button";
    resetButton.textContent = "↺";
    resetButton.title = "Reset upload and download totals";
    resetButton.setAttribute("aria-label", "Reset Codex resource monitor totals");
    resetButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openCodexResourceMonitorResetConfirmation(resetButton);
    });
    return resetButton;
  };
  const createCodexResourceMonitorControl = () => {
    const control = document.createElement("span");
    control.id = CODEX_RESOURCE_MONITOR_CONTROL_ID;
    const toggleButton = document.createElement("button");
    toggleButton.id = CODEX_RESOURCE_MONITOR_TOGGLE_ID;
    toggleButton.type = "button";
    toggleButton.setAttribute("aria-label", "Show or hide Codex resource monitor");
    createControlToggleContent(toggleButton, "📊");
    toggleButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      window[KEY]?.toggleCodexResourceMonitorVisibility?.();
    });

    const strip = document.createElement("span");
    strip.id = CODEX_RESOURCE_MONITOR_STRIP_ID;
    strip.hidden = true;
    const status = document.createElement("span");
    status.id = CODEX_RESOURCE_MONITOR_STATUS_ID;
    status.hidden = true;
    const values = document.createElement("span");
    values.id = CODEX_RESOURCE_MONITOR_VALUES_ID;
    values.append(
      createCodexResourceMetric("uploadSpeed", "↑/s", "Current upload speed", true),
      createCodexResourceMetric("uploadTotal", "↑Σ", "Uploaded since the last reset", true),
      createCodexResourceMetric("downloadSpeed", "↓/s", "Current download speed", true),
      createCodexResourceMetric("downloadTotal", "↓Σ", "Downloaded since the last reset", true),
      createCodexResourceMetric("memory", "🧠", "Codex backend resident memory", true),
      createCodexResourceMetric("cpu", "⚙", "Codex backend CPU; 100% equals one CPU core"),
      createCodexResourceMonitorResetButton()
    );
    strip.append(status, values);
    control.append(toggleButton, strip);
    return control;
  };
  const codexResourceMetricValueElement = (metricName) => {
    const metric = document.querySelector(
      "[" + CODEX_RESOURCE_MONITOR_METRIC_ATTRIBUTE_NAME + "='" + metricName + "']"
    );
    return metric?.querySelector("[data-agents-rtl-codex-resource-metric-value]") || null;
  };
  const setCodexResourceMetricValue = (metricName, value) => {
    const valueElement = codexResourceMetricValueElement(metricName);
    if (valueElement && valueElement.textContent !== value) valueElement.textContent = value;
  };
  const setCodexResourceByteMetricValue = (metricName, formattedByteCount) => {
    const valueElement = codexResourceMetricValueElement(metricName);
    const numericValueElement = valueElement?.querySelector("[data-agents-rtl-codex-resource-metric-number]");
    const unitElement = valueElement?.querySelector("[data-agents-rtl-codex-resource-metric-unit]");
    if (!numericValueElement || !unitElement) {
      throw new Error("Codex byte metric DOM is incomplete for " + metricName);
    }
    if (numericValueElement.textContent !== formattedByteCount.numericText) {
      numericValueElement.textContent = formattedByteCount.numericText;
    }
    if (unitElement.textContent !== formattedByteCount.unitText) {
      unitElement.textContent = formattedByteCount.unitText;
    }
    if (unitElement.getAttribute("data-agents-rtl-codex-resource-metric-unit") !== formattedByteCount.unitText) {
      unitElement.setAttribute("data-agents-rtl-codex-resource-metric-unit", formattedByteCount.unitText);
    }
  };
  const updateCodexResourceMonitor = () => {
    const control = document.getElementById(CODEX_RESOURCE_MONITOR_CONTROL_ID);
    if (!codexResourceMonitorIsSupported()) {
      control?.remove();
      return;
    }
    const monitorIsVisible = Boolean(window[KEY]?.codexResourceMonitorVisible);
    const strip = document.getElementById(CODEX_RESOURCE_MONITOR_STRIP_ID);
    const status = document.getElementById(CODEX_RESOURCE_MONITOR_STATUS_ID);
    const values = document.getElementById(CODEX_RESOURCE_MONITOR_VALUES_ID);
    if (!strip || !status || !values) return;
    strip.hidden = !monitorIsVisible;
    if (!monitorIsVisible) return;

    const metrics = window.__agentsRtlCodexResourceMetrics;
    if (typeof metrics?.error === "string" && metrics.error) {
      status.textContent = "Monitor error: " + metrics.error;
      status.hidden = false;
      values.hidden = true;
      return;
    }
    if (!metrics?.samplingEnabled || metrics.initializing) {
      status.textContent = "Starting monitor…";
      status.hidden = false;
      values.hidden = true;
      return;
    }
    if (metrics.processedResetRequestId !== window[KEY].codexResourceMonitorResetRequestId) {
      status.textContent = "Resetting totals…";
      status.hidden = false;
      values.hidden = true;
      return;
    }

    status.hidden = true;
    values.hidden = false;
    setCodexResourceByteMetricValue("uploadSpeed", formatCodexResourceBytes(metrics.uploadBytesPerSecond));
    setCodexResourceByteMetricValue("uploadTotal", formatCodexResourceBytes(metrics.uploadedBytesTotal));
    setCodexResourceByteMetricValue("downloadSpeed", formatCodexResourceBytes(metrics.downloadBytesPerSecond));
    setCodexResourceByteMetricValue("downloadTotal", formatCodexResourceBytes(metrics.downloadedBytesTotal));
    setCodexResourceByteMetricValue("memory", formatCodexResourceBytes(metrics.residentMemoryBytes));
    setCodexResourceMetricValue("cpu", formatCodexResourceCPUPercent(metrics.cpuPercent));
  };
  const toggleCodexResourceMonitorVisibility = () => {
    if (!codexResourceMonitorIsSupported()) {
      throw new Error("Codex resource monitoring is not supported in this environment");
    }
    window[KEY].codexResourceMonitorVisible = !window[KEY].codexResourceMonitorVisible;
    saveBoolean(CODEX_RESOURCE_MONITOR_VISIBLE_STORAGE_KEY, window[KEY].codexResourceMonitorVisible);
    updateControlButtons();
    updateCodexResourceMonitor();
  };
  const resetCodexResourceMonitorTotals = () => {
    if (typeof crypto?.randomUUID !== "function") {
      throw new Error("crypto.randomUUID is required to reset Codex resource totals");
    }
    const resetRequestId = crypto.randomUUID();
    window[KEY].codexResourceMonitorResetRequestId = resetRequestId;
    localStorage.setItem(CODEX_RESOURCE_MONITOR_RESET_REQUEST_ID_STORAGE_KEY, resetRequestId);
    updateCodexResourceMonitor();
  };
  const openCodexResourceMonitorResetConfirmation = (anchorElement) => {
    openCodexConversationConfirmation({
      anchorElement,
      title: "Reset monitor totals?",
      detail: "Reset upload and download totals to zero?",
      confirmLabel: "Yes",
      cancelLabel: "No",
      onConfirm: resetCodexResourceMonitorTotals,
    });
  };
