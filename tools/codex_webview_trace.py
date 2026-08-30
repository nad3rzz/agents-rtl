#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path

from codex_webview_profiler import (
    collect_runtime_contexts,
    command as send_cdp_command,
    connect_websocket,
    evaluate_expression,
    find_target,
    read_json_url,
)


DEFAULT_TARGET_MARKER = "extensionId=openai.chatgpt"
TRACE_KEY = "__agentsRtlReplyTrace"
RTL_SCRIPT_PARTS_DIRECTORY = Path(__file__).resolve().parent.parent / "helper-go" / "rtl_script_parts"


PROBE_EXPRESSION = r"""
(() => {
  const text = document.body?.innerText || "";
  const fiberElements = [...document.querySelectorAll("*")]
    .filter((element) => Object.keys(element).some((key) => key.startsWith("__reactFiber$")))
    .length;
  return {
    title: document.title,
    href: location.href,
    bodyTextLength: text.length,
    bodyTextStart: text.slice(0, 1200),
    hasAgentsRtl: Boolean(window.__agentsRtl),
    agentsRtlVersion: window.__agentsRtl?.version || null,
    codexConversationsLength: Array.isArray(window.__agentsRtl?.codexConversations)
      ? window.__agentsRtl.codexConversations.length
      : null,
    tabsText: [...document.querySelectorAll("#agents-rtl-codex-chat-tabs button")].map((button) => ({
      text: button.textContent,
      active: button.dataset.active,
      id: button.dataset.conversationId || "",
      unread: button.dataset.agentsRtlUnread || "0",
      pendingApproval: button.dataset.agentsRtlPendingApproval || "0",
    })),
    localStorageKeys: Object.keys(localStorage)
      .filter((key) => key.includes("agentsRtl") || key.includes("codex"))
      .sort(),
    reactFiberElements: fiberElements,
  };
})()
"""


TOKEN_USAGE_PROBE_EXPRESSION = r"""
(() => {
  const activeConversationId = document.querySelector(
    "#agents-rtl-codex-chat-tabs button[data-active='1']"
  )?.dataset?.conversationId || "";
  if (!activeConversationId) {
    throw new Error("Active Codex conversation id is unavailable");
  }

  const queryClient = window.__agentsRtl?.codexReactQueryClient;
  if (!queryClient?.getQueryCache) {
    throw new Error("Codex React Query client is unavailable");
  }

  const matchingQueryRecords = queryClient.getQueryCache().getAll()
    .map((query) => ({
      queryKey: query.queryKey,
      records: Array.isArray(query.state?.data)
        ? query.state.data.filter((record) => record?.id === activeConversationId)
        : [],
    }))
    .filter((query) => query.records.length > 0)
    .map((query) => ({
      queryKey: query.queryKey,
      records: query.records.map((record) => ({
        id: record.id,
        title: record.title,
        hostId: record.hostId,
        updatedAt: record.updatedAt,
        recencyAt: record.recencyAt,
        turnCount: Array.isArray(record.turns) ? record.turns.length : null,
        latestTokenUsageInfo: record.latestTokenUsageInfo ?? null,
        lastTurnStatus: Array.isArray(record.turns)
          ? record.turns.at(-1)?.status ?? null
          : null,
      })),
    }));

  const contextWindowElements = [...document.querySelectorAll("*")]
    .filter((element) => String(element.textContent || "").trim().startsWith("Context window:"))
    .filter((element) => ![...element.children].some((child) =>
      String(child.textContent || "").trim().startsWith("Context window:")
    ))
    .map((element) => ({
      tag: element.tagName,
      text: String(element.textContent || "").replace(/\s+/g, " ").trim(),
      ariaLabel: element.getAttribute("aria-label") || "",
      title: element.getAttribute("title") || "",
      className: String(element.className || "").slice(0, 300),
    }));

  return {
    activeConversationId,
    matchingQueryRecords,
    contextWindowElements,
  };
})()
"""


CONTROLS_PROBE_EXPRESSION = r"""
(() => {
  const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const attributesOf = (element) => Object.fromEntries(
    [...(element?.attributes || [])]
      .filter((attribute) =>
        attribute.name === "aria-label" ||
        attribute.name === "title" ||
        attribute.name === "role" ||
        attribute.name.startsWith("data-")
      )
      .map((attribute) => [attribute.name, attribute.value])
  );
  const reactKeysOf = (element) => Object.keys(element || {})
    .filter((key) => key.startsWith("__reactFiber$") || key.startsWith("__reactProps$"));
  const conversationIdFromFiber = (element) => {
    const fiberKey = Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
    let fiber = fiberKey ? element[fiberKey] : null;
    let depth = 0;
    while (fiber && depth < 18) {
      const props = fiber.memoizedProps || fiber.pendingProps || {};
      const candidates = [
        props.conversationId,
        props.item?.conversation?.id,
        props.item?.id,
        props.item?.conversationId,
        props.item?.key,
        fiber.key,
      ].map((value) => String(value || "").replace(/^local:/, "").trim()).filter(Boolean);
      if (candidates.length > 0) return candidates[0];
      fiber = fiber.return;
      depth += 1;
    }
    return "";
  };
  const describe = (element) => ({
    tag: element?.tagName || "",
    text: compact(element?.innerText || element?.textContent || "").slice(0, 240),
    className: compact(element?.className || "").slice(0, 500),
    attributes: attributesOf(element),
    reactKeys: reactKeysOf(element),
    parentTag: element?.parentElement?.tagName || "",
    parentClassName: compact(element?.parentElement?.className || "").slice(0, 500),
  });
  const describeAncestors = (element, maximumDepth = 8) => {
    const ancestors = [];
    let current = element;
    while (current && ancestors.length < maximumDepth) {
      ancestors.push(describe(current));
      current = current.parentElement;
    }
    return ancestors;
  };
  const conversationRows = [...document.querySelectorAll("[role='button']")]
    .filter((element) =>
      compact(element.className).includes("token-nav-row") ||
      element.hasAttribute("data-agents-rtl-codex-chat-list-rename-row")
    );
  const allButtons = [...document.querySelectorAll("button")];
  const renameCandidates = allButtons.filter((button) =>
    /rename/i.test([
      button.innerText,
      button.textContent,
      button.getAttribute("aria-label"),
      button.getAttribute("title"),
    ].map(compact).join(" "))
  );
  const actionElements = [...document.querySelectorAll("[role='menu'],[role='menuitem'],[role='dialog'],[data-radix-menu-content]")];
  const renameTextElements = [...document.querySelectorAll("*")].filter((element) =>
    /^rename(?: chat| conversation)?$/i.test(compact(element.innerText || element.textContent || ""))
  );
  const archiveButtons = allButtons.filter((button) =>
    compact(button.getAttribute("aria-label")) === "Archive chat"
  );
  const semanticConversationRows = [...new Set(
    archiveButtons.map((button) => button.closest("[role='button']")).filter(Boolean)
  )];
  return {
    bodyTextStart: compact(document.body?.innerText || "").slice(0, 1200),
    bodyTextEnd: compact(document.body?.innerText || "").slice(-1200),
    conversationRows: conversationRows.map((row) => ({
      ...describe(row),
      buttons: [...row.querySelectorAll("button")].map(describe),
      directChildren: [...row.children].map(describe),
    })),
    semanticConversationRows: semanticConversationRows.map((row) => ({
      ...describe(row),
      conversationId: conversationIdFromFiber(row),
      archiveButtonCount: row.querySelectorAll("button[aria-label='Archive chat']").length,
      titleCandidates: [...row.querySelectorAll("div,span")]
        .map((element) => describe(element))
        .filter((element) => element.text)
        .slice(0, 24),
    })),
    renameCandidates: renameCandidates.map(describe),
    actionElements: actionElements.map((element) => ({
      ...describe(element),
      ancestors: describeAncestors(element, 5),
    })),
    renameTextElements: renameTextElements.map((element) => ({
      ...describe(element),
      ancestors: describeAncestors(element, 8),
    })),
    archiveButtonAncestors: archiveButtons.map((button) => describeAncestors(button)),
    agentsRtlListRenameButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-rename-button").length,
    agentsRtlListPathButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-path-button").length,
    allButtons: allButtons.map(describe),
  };
})()
"""


APPLY_LIST_CONTROLS_PROBE_EXPRESSION = r"""
(() => {
  const agentsRtl = window.__agentsRtl;
  if (typeof agentsRtl?.updateCodexConversations !== "function") {
    throw new Error("Agents RTL conversation updater is unavailable");
  }
  if (typeof agentsRtl?.applyCodexConversationListRenameControls !== "function") {
    throw new Error("Agents RTL list controls function is unavailable");
  }
  const before = {
    conversations: agentsRtl.codexConversations?.length || 0,
    renameButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-rename-button").length,
    pathButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-path-button").length,
  };
  try {
    const conversations = agentsRtl.updateCodexConversations();
    agentsRtl.applyCodexConversationListRenameControls(conversations);
  } catch (error) {
    return {
      before,
      errorName: error?.name || "Error",
      errorMessage: error?.message || String(error),
      errorStack: error?.stack || "",
    };
  }
  return {
    before,
    after: {
      conversations: agentsRtl.codexConversations?.length || 0,
      renameButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-rename-button").length,
      pathButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-path-button").length,
    },
  };
})()
"""


TEST_LIST_RENAME_OPEN_EXPRESSION = r"""
(() => {
  const renameButton = document.querySelector(".agents-rtl-codex-chat-list-rename-button");
  if (!renameButton) throw new Error("No Agents RTL list rename button was found");
  document.getElementById("agents-rtl-codex-chat-rename-editor")?.remove();
  const pointerEvent = new PointerEvent("pointerdown", {
    bubbles: true,
    cancelable: true,
    button: 0,
    pointerId: 1,
    pointerType: "mouse",
  });
  const dispatchResult = renameButton.dispatchEvent(pointerEvent);
  const editor = document.getElementById("agents-rtl-codex-chat-rename-editor");
  const editorRect = editor?.getBoundingClientRect?.();
  const editorStyle = editor ? getComputedStyle(editor) : null;
  return {
    conversationId: renameButton.dataset.conversationId || "",
    dispatchResult,
    defaultPrevented: pointerEvent.defaultPrevented,
    editorExistsAfterDispatch: Boolean(editor),
    editorHost: editor?.parentElement?.tagName || "",
    editorRect: editorRect ? {
      left: editorRect.left,
      top: editorRect.top,
      width: editorRect.width,
      height: editorRect.height,
      right: editorRect.right,
      bottom: editorRect.bottom,
    } : null,
    editorStyle: editorStyle ? {
      display: editorStyle.display,
      visibility: editorStyle.visibility,
      opacity: editorStyle.opacity,
      zIndex: editorStyle.zIndex,
    } : null,
    editorInputValue: editor?.querySelector("input")?.value || "",
    activeElement: document.activeElement?.getAttribute?.("aria-label") || document.activeElement?.tagName || "",
    listenerState: {
      renamePointerdown: typeof window.__agentsRtl?.codexConversationListRenamePointerdownListener,
      transientPointerdown: typeof window.__agentsRtl?.codexTransientPointerdownListener,
    },
  };
})()
"""


LIST_BINDINGS_PROBE_EXPRESSION = r"""
(() => {
  const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const conversationIdFromFiber = (element) => {
    const fiberKey = Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
    let fiber = fiberKey ? element[fiberKey] : null;
    let depth = 0;
    while (fiber && depth < 18) {
      const props = fiber.memoizedProps || fiber.pendingProps || {};
      const conversationId = [
        props.conversationId,
        props.item?.conversation?.id,
        props.item?.id,
        props.item?.conversationId,
        props.item?.key,
        fiber.key,
      ].map((value) => compact(value).replace(/^local:/, "")).find(Boolean);
      if (conversationId) return conversationId;
      fiber = fiber.return;
      depth += 1;
    }
    return "";
  };
  const conversations = window.__agentsRtl?.codexConversations || [];
  const conversationsById = new Map(conversations.map((conversation) => [conversation.id, conversation]));
  const targetConversationId = "019ea131-9ac7-75d1-9709-550f32043af4";
  const queryClient = window.__agentsRtl?.codexReactQueryClient;
  const queryRecords = (queryClient?.getQueryCache?.().getAll?.() || [])
    .map((query) => ({
      queryKey: query.queryKey,
      records: Array.isArray(query.state?.data)
        ? query.state.data.filter((record) => compact(record?.id).replace(/^local:/, "") === targetConversationId)
        : [],
    }))
    .filter((query) => query.records.length > 0);
  const helperRecords = (Array.isArray(window.__agentsRtlCodexConversations)
    ? window.__agentsRtlCodexConversations
    : []).filter((record) => compact(record?.id).replace(/^local:/, "") === targetConversationId);
  const rows = [...new Set(
    [...document.querySelectorAll("button[aria-label='Archive chat']")]
      .map((archiveButton) => archiveButton.closest("[role='button']"))
      .filter(Boolean)
  )];
  return {
    rows: rows.map((row) => {
      const rowConversationId = conversationIdFromFiber(row);
      const conversation = conversationsById.get(rowConversationId);
      return {
        rowConversationId,
        nativeTitle: compact(row.querySelector("[data-thread-title='true']")?.textContent),
        stateTitle: compact(conversation?.title),
        renameButtonConversationId: row.querySelector(".agents-rtl-codex-chat-list-rename-button")?.dataset.conversationId || "",
        pathButtonConversationId: row.querySelector(".agents-rtl-codex-chat-list-path-button")?.dataset.conversationId || "",
      };
    }),
    relevantConversations: conversations
      .filter((conversation) => /firefox|فايرفوكس|new chat/i.test(conversation.title))
      .map((conversation) => ({
        id: conversation.id,
        title: conversation.title,
        hostId: conversation.hostId,
        path: conversation.path,
      })),
    targetSources: {
      targetConversationId,
      queryRecords: queryRecords.map((query) => ({
        queryKey: query.queryKey,
        records: query.records.map((record) => ({
          id: record.id,
          title: record.title,
          threadName: record.threadName,
          hostId: record.hostId,
          updatedAt: record.updatedAt,
        })),
      })),
      helperRecords: helperRecords.map((record) => ({
        id: record.id,
        title: record.title,
        path: record.path,
      })),
    },
  };
})()
"""


INSTALL_RENAME_EVENT_TRACER_EXPRESSION = r"""
(() => {
  const tracerKey = "__agentsRtlRenameEventTracer";
  window[tracerKey]?.stop?.();
  const events = [];
  const eventTypes = ["pointerdown", "mousedown", "mouseup", "click"];
  const describeElement = (element) => ({
    tag: element?.tagName || "",
    className: String(element?.className || "").slice(0, 500),
    ariaLabel: element?.getAttribute?.("aria-label") || "",
    title: element?.getAttribute?.("title") || "",
    text: String(element?.textContent || "").trim().slice(0, 120),
  });
  const eventHandler = (event) => {
    const renameButtons = [...document.querySelectorAll(
      ".agents-rtl-codex-chat-list-rename-button,.agents-rtl-codex-chat-rename-button"
    )];
    events.push({
      type: event.type,
      isTrusted: event.isTrusted,
      defaultPrevented: event.defaultPrevented,
      x: event.clientX,
      y: event.clientY,
      target: describeElement(event.target),
      pointElement: describeElement(document.elementFromPoint(event.clientX, event.clientY)),
      path: event.composedPath().slice(0, 8).map(describeElement),
      renameButtonsAtPoint: renameButtons.filter((button) => {
        const rect = button.getBoundingClientRect();
        return event.clientX >= rect.left && event.clientX <= rect.right &&
          event.clientY >= rect.top && event.clientY <= rect.bottom;
      }).map(describeElement),
    });
    if (events.length > 100) events.shift();
  };
  eventTypes.forEach((eventType) => document.addEventListener(eventType, eventHandler, true));
  window[tracerKey] = {
    events,
    stop: () => eventTypes.forEach((eventType) => document.removeEventListener(eventType, eventHandler, true)),
  };
  return {
    installed: true,
    listRenameButtons: document.querySelectorAll(".agents-rtl-codex-chat-list-rename-button").length,
    tabRenameButtons: document.querySelectorAll(".agents-rtl-codex-chat-rename-button").length,
  };
})()
"""


RENAME_EVENT_TRACER_SUMMARY_EXPRESSION = r"""
(() => {
  const tracer = window.__agentsRtlRenameEventTracer;
  if (!tracer) throw new Error("Rename event tracer is not installed");
  return {
    events: tracer.events,
    editorExists: Boolean(document.getElementById("agents-rtl-codex-chat-rename-editor")),
    confirmationExists: Boolean(document.getElementById("agents-rtl-codex-chat-confirmation")),
  };
})()
"""


LIST_RENAME_BUTTON_CENTER_EXPRESSION = r"""
(() => {
  document.getElementById("agents-rtl-codex-chat-rename-editor")?.remove();
  const renameButton = document.querySelector(".agents-rtl-codex-chat-list-rename-button");
  if (!renameButton) throw new Error("No Agents RTL list rename button was found");
  const rect = renameButton.getBoundingClientRect();
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    conversationId: renameButton.dataset.conversationId || "",
  };
})()
"""


LIST_RENAME_CLICK_RESULT_EXPRESSION = r"""
(() => {
  const editor = document.getElementById("agents-rtl-codex-chat-rename-editor");
  return {
    editorExists: Boolean(editor),
    editorInputValue: editor?.querySelector("input")?.value || "",
    activeElement: document.activeElement?.getAttribute?.("aria-label") || document.activeElement?.tagName || "",
  };
})()
"""


LIST_RENAME_LIFECYCLE_RESULT_EXPRESSION = r"""
(() => {
  const editorId = "agents-rtl-codex-chat-rename-editor";
  const confirmationId = "agents-rtl-codex-chat-confirmation";
  return {
    editorExists: Boolean(document.getElementById(editorId)),
    confirmationExists: Boolean(document.getElementById(confirmationId)),
    editorInputValue: document.querySelector("#" + editorId + " input")?.value || "",
    activeElement: document.activeElement?.getAttribute?.("aria-label") || document.activeElement?.tagName || "",
    removeEvents: window.__agentsRtlRenameLifecycleProbe?.events || [],
  };
})()
"""


INSTALL_RENAME_SUBMIT_PROBE_EXPRESSION = r"""
(() => {
  window.__agentsRtlRenameSubmitProbe?.stop?.();
  const editorId = "agents-rtl-codex-chat-rename-editor";
  const confirmationId = "agents-rtl-codex-chat-confirmation";
  const events = [];
  const describe = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    events.push({
      type: event.type,
      targetTag: target?.tagName || "",
      targetText: String(target?.textContent || "").slice(0, 80),
      targetId: target?.id || "",
      inEditor: Boolean(target?.closest?.("#" + editorId)),
      inConfirmation: Boolean(target?.closest?.("#" + confirmationId)),
      defaultPrevented: event.defaultPrevented,
    });
    if (events.length > 80) events.shift();
  };
  const eventNames = ["pointerdown", "pointerup", "click", "submit"];
  eventNames.forEach((name) => document.addEventListener(name, describe, true));
  window.__agentsRtlRenameSubmitProbe = {
    events,
    stop: () => eventNames.forEach((name) => document.removeEventListener(name, describe, true)),
  };
  return true;
})()
"""


PREPARE_RENAME_SUBMIT_EXPRESSION = r"""
(() => {
  const editorId = "agents-rtl-codex-chat-rename-editor";
  const editor = document.getElementById(editorId);
  if (!editor) throw new Error("Rename editor is not open");
  const input = editor.querySelector("input");
  const saveButton = editor.querySelector("button[type='submit']");
  if (!input) throw new Error("Rename editor input is missing");
  if (!saveButton) throw new Error("Rename editor save button is missing");
  const originalValue = input.value;
  const nextValue = originalValue + " UI";
  input.focus();
  input.value = nextValue;
  input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: " UI" }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  const rect = saveButton.getBoundingClientRect();
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  const topElement = document.elementFromPoint(centerX, centerY);
  return {
    originalValue,
    nextValue,
    saveButtonText: saveButton.textContent,
    saveButtonCenter: { x: centerX, y: centerY },
    topElement: {
      tag: topElement?.tagName || "",
      id: topElement?.id || "",
      text: String(topElement?.textContent || "").slice(0, 80),
      className: String(topElement?.className || "").slice(0, 160),
    },
  };
})()
"""


RENAME_SUBMIT_RESULT_EXPRESSION = r"""
(() => {
  const editorId = "agents-rtl-codex-chat-rename-editor";
  const confirmationId = "agents-rtl-codex-chat-confirmation";
  const confirmation = document.getElementById(confirmationId);
  return {
    editorExists: Boolean(document.getElementById(editorId)),
    confirmationExists: Boolean(confirmation),
    confirmationText: String(confirmation?.innerText || "").replace(/\s+/g, " ").trim(),
    events: window.__agentsRtlRenameSubmitProbe?.events || [],
  };
})()
"""


INSTALL_LIST_RENAME_LIFECYCLE_PROBE_EXPRESSION = r"""
(() => {
  window.__agentsRtlRenameLifecycleProbe?.stop?.();
  const editorId = "agents-rtl-codex-chat-rename-editor";
  const confirmationId = "agents-rtl-codex-chat-confirmation";
  const events = [];
  const originalElementRemove = Element.prototype.remove;
  const originalRemoveChild = Node.prototype.removeChild;
  const record = (kind, element) => {
    if (![editorId, confirmationId].includes(element?.id)) return;
    events.push({
      kind,
      id: element.id,
      atMs: Math.round(performance.now()),
      stack: String(new Error().stack || "").split("\n").slice(0, 10),
    });
    if (events.length > 40) events.shift();
  };
  Element.prototype.remove = function (...args) {
    record("Element.remove", this);
    return originalElementRemove.apply(this, args);
  };
  Node.prototype.removeChild = function (child, ...args) {
    record("Node.removeChild", child);
    return originalRemoveChild.call(this, child, ...args);
  };
  window.__agentsRtlRenameLifecycleProbe = {
    events,
    stop: () => {
      Element.prototype.remove = originalElementRemove;
      Node.prototype.removeChild = originalRemoveChild;
    },
  };
  return true;
})()
"""


REINSTALL_LIST_RENAME_LISTENERS_EXPRESSION = r"""
(() => {
  if (typeof window.__agentsRtl?.installCodexConversationListRenameListeners !== "function") {
    throw new Error("Agents RTL list rename listener installer is unavailable");
  }
  window.__agentsRtl.installCodexConversationListRenameListeners();
  return true;
})()
"""


INVALIDATE_RTL_VERSION_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtl?.installed) throw new Error("Agents RTL is not installed in this context");
  const previousVersion = window.__agentsRtl.version;
  window.__agentsRtl.version = previousVersion + "-invalidated";
  return { previousVersion, invalidatedVersion: window.__agentsRtl.version };
})()
"""


NATIVE_IPC_PROBE_EXPRESSION = r"""
(async () => {
  const entryScriptUrls = [...document.scripts]
    .map((scriptElement) => scriptElement.src)
    .filter((scriptUrl) => /\/index-[^/]+\.js(?:\?|$)/.test(scriptUrl));
  const uniqueEntryScriptUrls = [...new Set(entryScriptUrls)];
  if (uniqueEntryScriptUrls.length !== 1) {
    throw new Error("Expected exactly one Codex entry script, found " + uniqueEntryScriptUrls.length);
  }
  const entryScriptResponse = await fetch(uniqueEntryScriptUrls[0]);
  if (!entryScriptResponse.ok) {
    throw new Error("Failed to read Codex entry script: HTTP " + entryScriptResponse.status);
  }
  const entryScriptSource = await entryScriptResponse.text();
  const bridgeModuleImports = [...entryScriptSource.matchAll(/["']\.\/(thread-context-inputs-[^"']+\.js)["']/g)]
    .map((match) => match[1]);
  const uniqueBridgeModuleImports = [...new Set(bridgeModuleImports)];
  if (uniqueBridgeModuleImports.length !== 1) {
    throw new Error("Expected exactly one thread-context-inputs import, found " + uniqueBridgeModuleImports.length);
  }
  const moduleUrl = new URL("./" + uniqueBridgeModuleImports[0], uniqueEntryScriptUrls[0]).href;
  const bridgeModuleResponse = await fetch(moduleUrl);
  if (!bridgeModuleResponse.ok) {
    throw new Error("Failed to read thread-context-inputs module: HTTP " + bridgeModuleResponse.status);
  }
  const bridgeModuleSource = await bridgeModuleResponse.text();
  const appServerBridgeMatches = [...bridgeModuleSource.matchAll(
    /function ([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*),([A-Za-z_$][\w$]*)\)\{return ([A-Za-z_$][\w$]*)\.sendRequest\(\2,\3\)\}/g
  )].filter((match) => {
    const functionStart = match.index || 0;
    const precedingSource = bridgeModuleSource.slice(Math.max(0, functionStart - 1200), functionStart);
    return precedingSource.includes("Missing AppServer request message handler");
  });
  if (appServerBridgeMatches.length !== 1) {
    throw new Error("Expected exactly one AppServer bridge function, found " + appServerBridgeMatches.length);
  }
  const localFunctionName = appServerBridgeMatches[0][1];
  const escapedLocalFunctionName = localFunctionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const exportBlockStart = bridgeModuleSource.lastIndexOf("export{");
  if (exportBlockStart < 0) {
    throw new Error("thread-context-inputs module has no export block");
  }
  const exportBlockSource = bridgeModuleSource.slice(exportBlockStart);
  const exportMatches = [...exportBlockSource.matchAll(
    new RegExp("\\b" + escapedLocalFunctionName + " as ([A-Za-z_$][\\w$]*)\\b", "g")
  )].map((match) => match[1]);
  const uniqueExportNames = [...new Set(exportMatches)];
  if (uniqueExportNames.length === 0) {
    throw new Error("AppServer bridge function has no module export");
  }
  const moduleNamespace = await import(moduleUrl);
  const exportedRequestFunctions = uniqueExportNames.map((exportName) => moduleNamespace[exportName]);
  const uniqueRequestFunctions = [...new Set(exportedRequestFunctions)];
  if (uniqueRequestFunctions.length !== 1) {
    throw new Error("AppServer bridge exports do not reference one function");
  }
  const requestFunction = uniqueRequestFunctions[0];
  if (typeof requestFunction !== "function") {
    throw new Error("AppServer bridge export is not a function: " + uniqueExportNames[0]);
  }
  window.__agentsRtlNativeIpcProbe = {
    moduleUrl,
    exportNames: uniqueExportNames,
    request: requestFunction,
  };
  return {
    moduleUrl,
    localFunctionName,
    exportNames: uniqueExportNames,
  };
})()
"""


NATIVE_RENAME_SAME_TITLE_EXPRESSION = r"""
(async () => {
  const targetTitle = "الرد على التحية";
  const nativeIpcProbe = window.__agentsRtlNativeIpcProbe;
  if (typeof nativeIpcProbe?.request !== "function") {
    throw new Error("Native AppServer bridge probe is not installed");
  }
  const queryClient = window.__agentsRtl?.codexReactQueryClient;
  if (!queryClient?.getQueryCache) {
    throw new Error("Codex React Query client is unavailable");
  }
  const conversationQueries = queryClient.getQueryCache().getAll()
    .filter((query) =>
      Array.isArray(query.state?.data) &&
      query.state.data.some((item) => item && typeof item.title === "string" && Array.isArray(item.turns))
    );
  if (conversationQueries.length === 0) {
    throw new Error("No Codex conversation queries were found");
  }
  const matchingConversations = conversationQueries
    .flatMap((query) => query.state.data)
    .filter((conversation) => conversation.title === targetTitle);
  const matchingConversationIds = [...new Set(matchingConversations.map((conversation) => conversation.id))];
  if (matchingConversationIds.length !== 1) {
    throw new Error(
      "Expected one conversation id for title " + targetTitle +
      ", found " + JSON.stringify(matchingConversationIds)
    );
  }
  const matchingHostIds = [...new Set(
    matchingConversations
      .filter((conversation) => conversation.id === matchingConversationIds[0])
      .map((conversation) => conversation.hostId)
  )];
  if (matchingHostIds.length !== 1) {
    throw new Error(
      "Expected one host id for conversation " + matchingConversationIds[0] +
      ", found " + JSON.stringify(matchingHostIds)
    );
  }
  const conversation = matchingConversations.find((candidate) =>
    candidate.id === matchingConversationIds[0] && candidate.hostId === matchingHostIds[0]
  );
  if (typeof conversation.id !== "string" || !conversation.id.trim()) {
    throw new Error("Native rename target has no conversation id");
  }
  if (typeof conversation.hostId !== "string" || !conversation.hostId.trim()) {
    throw new Error("Native rename target has no host id");
  }
  const originalTitle = conversation.title;
  const temporaryTitle = originalTitle + " [Agents RTL native test]";
  const conflictingTemporaryTitles = conversationQueries
    .flatMap((query) => query.state.data)
    .filter((candidate) => candidate.id !== conversation.id && candidate.title === temporaryTitle);
  if (conflictingTemporaryTitles.length > 0) {
    throw new Error("Temporary native rename title is already used by another conversation");
  }
  let temporaryTitleWasObserved = false;
  try {
    await nativeIpcProbe.request("set-thread-title", {
      conversationId: conversation.id,
      hostId: conversation.hostId,
      title: temporaryTitle,
    });
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const observedTitles = [...new Set(
        conversationQueries
          .flatMap((query) => query.state.data)
          .filter((candidate) => candidate.id === conversation.id)
          .map((candidate) => candidate.title)
      )];
      if (observedTitles.length === 1 && observedTitles[0] === temporaryTitle) {
        temporaryTitleWasObserved = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (!temporaryTitleWasObserved) {
      throw new Error("Native temporary title was not observed in every Codex conversation cache");
    }
  } finally {
    await nativeIpcProbe.request("set-thread-title", {
      conversationId: conversation.id,
      hostId: conversation.hostId,
      title: originalTitle,
    });
  }
  let originalTitleWasRestored = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const observedTitles = [...new Set(
      conversationQueries
        .flatMap((query) => query.state.data)
        .filter((candidate) => candidate.id === conversation.id)
        .map((candidate) => candidate.title)
    )];
    if (observedTitles.length === 1 && observedTitles[0] === originalTitle) {
      originalTitleWasRestored = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (!originalTitleWasRestored) {
    throw new Error("Native title restoration was not observed in every Codex conversation cache");
  }
  return {
    id: conversation.id,
    hostId: conversation.hostId,
    originalTitle,
    temporaryTitle,
    temporaryTitleWasObserved,
    originalTitleWasRestored,
  };
})()
"""


REPLY_TRACER_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlReplyTrace";
  if (window[KEY]?.stop) window[KEY].stop();

  const compact = (value) => String(value || "").replace(/^\s*/, "").replace(/\s*$/, "").replace(/\s+/g, " ");
  const idOf = (conversation) => [
    conversation?.id,
    conversation?.threadId,
    conversation?.conversationId,
    conversation?.key,
    conversation?.thread?.id,
    conversation?.conversation?.id,
  ].map(compact).find(Boolean) || "";
  const titleOf = (conversation) => [
    conversation?.title,
    conversation?.threadName,
    conversation?.thread?.title,
    conversation?.conversation?.title,
  ].map(compact).find(Boolean) || "";
  const turnsOf = (conversation) => [
    conversation?.turns,
    conversation?.thread?.turns,
    conversation?.conversation?.turns,
  ].find(Array.isArray) || [];
  const itemText = (item) => [
    item?.content,
    item?.text,
    item?.message,
    item?.markdown,
    item?.output,
  ].filter((value) => typeof value === "string").map(compact).find(Boolean) || "";
  const isAssistant = (item) =>
    item?.type === "assistant-message" ||
    item?.type === "agentMessage" ||
    item?.role === "assistant" ||
    item?.author?.role === "assistant";
  const signatureOf = (conversation) => {
    const signatures = [];
    turnsOf(conversation).forEach((turn, turnIndex) => {
      const items = Array.isArray(turn?.items) ? turn.items : [];
      items.forEach((item, itemIndex) => {
        if (!isAssistant(item)) return;
        const text = itemText(item);
        if (!text && !item?.id && !turn?.turnId && !turn?.id) return;
        signatures.push([
          turn?.turnId || turn?.id || turnIndex,
          item?.id || itemIndex,
          item?.completed === true ? "1" : "0",
          item?.status || turn?.status || "",
          text.length,
          text.slice(-60),
        ].map(compact).join(":"));
      });
    });
    return signatures.at(-1) || "";
  };
  const fiberKey = (element) => Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
  const findReactQueryClient = () => {
    if (window.__agentsRtl?.codexReactQueryClient?.getQueryCache) return window.__agentsRtl.codexReactQueryClient;
    const roots = new Set();
    document.querySelectorAll("*").forEach((element) => {
      const key = fiberKey(element);
      if (!key) return;
      let fiber = element[key];
      while (fiber?.return) fiber = fiber.return;
      if (fiber) roots.add(fiber);
    });
    const stack = [...roots].map((root) => root.child).filter(Boolean);
    const seenFibers = new Set();
    while (stack.length > 0) {
      const fiber = stack.pop();
      if (!fiber || seenFibers.has(fiber)) continue;
      seenFibers.add(fiber);
      const propObjects = [fiber.memoizedProps, fiber.pendingProps].filter(Boolean);
      for (const props of propObjects) {
        for (const candidate of [props.queryClient, props.client]) {
          if (candidate?.getQueryCache) return candidate;
        }
      }
      let hook = fiber.memoizedState;
      let hookDepth = 0;
      while (hook && hookDepth < 10) {
        for (const candidate of [hook.memoizedState, hook.memoizedState?.current?.queryClient]) {
          if (candidate?.getQueryCache) return candidate;
        }
        hook = hook.next;
        hookDepth += 1;
      }
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }
    return null;
  };
  const getConversationList = () => {
    const queryClient = findReactQueryClient();
    const queries = queryClient?.getQueryCache?.().getAll?.() || [];
    const query = queries.find((candidate) => {
      const data = candidate?.state?.data;
      return Array.isArray(data) && data.some((item) =>
        item && typeof item === "object" && typeof item.title === "string" && Array.isArray(item.turns)
      );
    });
    return Array.isArray(query?.state?.data) ? query.state.data : [];
  };
  const getActiveId = (conversationIds) => {
    const activeButtonId = document.querySelector("#agents-rtl-codex-chat-tabs button[data-active='1']")
      ?.dataset?.conversationId;
    if (activeButtonId && conversationIds.has(activeButtonId)) return activeButtonId;
    const pathMatch = String(location.pathname || "").match(/\/local\/([^/?#]+)/);
    if (!pathMatch) return "";
    try {
      const decoded = decodeURIComponent(pathMatch[1]);
      return conversationIds.has(decoded) ? decoded : "";
    } catch (error) {
      return "";
    }
  };
  const state = {
    startedAt: new Date().toISOString(),
    href: location.href,
    samples: [],
    changes: [],
    previousById: new Map(),
    maxSamples: 240,
  };
  const sample = (label = "tick") => {
    const rows = getConversationList().map((conversation) => ({
      id: idOf(conversation),
      title: titleOf(conversation),
      turnCount: turnsOf(conversation).length,
      hasUnreadTurn: conversation?.hasUnreadTurn === true,
      unreadMessageCount: Number.isFinite(conversation?.unreadMessageCount) ? conversation.unreadMessageCount : 0,
      signature: signatureOf(conversation),
      runtime: compact(conversation?.threadRuntimeStatus || conversation?.status || ""),
    })).filter((row) => row.id);
    const conversationIds = new Set(rows.map((row) => row.id));
    const activeId = getActiveId(conversationIds);
    const changes = [];
    rows.forEach((row) => {
      const previous = state.previousById.get(row.id);
      if (previous && previous.signature !== row.signature) {
        changes.push({
          at: Date.now(),
          id: row.id,
          title: row.title,
          active: row.id === activeId,
          from: previous.signature,
          to: row.signature,
        });
      }
      state.previousById.set(row.id, { signature: row.signature, title: row.title });
    });
    state.changes.push(...changes);
    const sampleValue = { at: Date.now(), label, activeId, rows, changes };
    state.samples.push(sampleValue);
    if (state.samples.length > state.maxSamples) state.samples.shift();
    return sampleValue;
  };
  const intervalId = setInterval(() => sample(), 500);
  window[KEY] = {
    state,
    sample,
    stop: () => clearInterval(intervalId),
    summary: () => ({
      href: state.href,
      samples: state.samples.length,
      latest: state.samples.at(-1) || null,
      changes: state.changes,
    }),
  };
  return window[KEY].sample("install");
})()
"""


SUMMARY_EXPRESSION = f"""
(() => {{
  if (!window.{TRACE_KEY}) throw new Error("Reply tracer is not installed");
  return window.{TRACE_KEY}.summary();
}})()
"""


STOP_EXPRESSION = f"""
(() => {{
  if (!window.{TRACE_KEY}) throw new Error("Reply tracer is not installed");
  const summary = window.{TRACE_KEY}.summary();
  window.{TRACE_KEY}.stop();
  return summary;
}})()
"""


RENAME_RUNTIME_PROBE_EXPRESSION = r"""
(() => {
  const buttonClassName = "agents-rtl-codex-chat-list-rename-button";
  const buttons = [...document.querySelectorAll("." + buttonClassName)];
  const listener = window.__agentsRtl?.codexConversationListRenameDocumentListener;
  const describeButton = (button, index) => {
    const rect = button.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const center = document.elementFromPoint(centerX, centerY);
    return {
      index,
      id: button.dataset.conversationId || "",
      binding: button.dataset.agentsRtlBindingVersion || "",
      rect: {
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      centerTag: center?.tagName || "",
      centerClassName: String(center?.className || "").slice(0, 160),
      hitByDocumentMath: buttons.some((candidate) => {
        const candidateRect = candidate.getBoundingClientRect();
        return (
          centerX >= candidateRect.left &&
          centerX <= candidateRect.right &&
          centerY >= candidateRect.top &&
          centerY <= candidateRect.bottom
        );
      }),
    };
  };
  return {
    version: window.__agentsRtl?.version || "",
    hasInstallFunction: typeof window.__agentsRtl?.installCodexConversationListRenameListeners === "function",
    hasRemoveFunction: typeof window.__agentsRtl?.removeCodexConversationListRenameListeners === "function",
    hasDocumentListener: typeof listener === "function",
    listenerName: listener?.name || "",
    listRenameButtonCount: buttons.length,
    buttons: buttons.map(describeButton),
    editorExists: Boolean(document.getElementById("agents-rtl-codex-chat-rename-editor")),
  };
})()
"""


def parse_args():
    parser = argparse.ArgumentParser(
        prog="codex-webview-trace",
        description="Reusable DevTools probes for Codex webviews.",
    )
    parser.add_argument(
        "command",
        choices=[
            "list",
            "probe",
            "inspect-token-usage",
            "inspect-controls",
            "apply-list-controls",
            "test-list-rename-open",
            "inspect-list-bindings",
            "install-rename-event-tracer",
            "rename-event-tracer-summary",
            "click-list-rename",
            "trace-list-rename-lifecycle",
            "trace-list-rename-submit",
            "reinstall-and-click-list-rename",
            "inspect-native-ipc",
            "inject-local-rtl",
            "test-native-rename",
            "invalidate-rtl-version",
            "inspect-rename-runtime",
            "install-reply-tracer",
            "summary",
            "stop",
        ],
    )
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--target-marker", default=DEFAULT_TARGET_MARKER)
    parser.add_argument("--delay-sec", type=float, default=0)
    parser.add_argument("--all-targets", action="store_true")
    parser.add_argument("--require-body", action="store_true")
    return parser.parse_args()


def print_json(label, value):
    print(label + " " + json.dumps(value, ensure_ascii=False, indent=2))


def target_summary(target):
    return {
        "type": target.get("type"),
        "title": target.get("title"),
        "url": target.get("url"),
        "hasWebSocket": bool(target.get("webSocketDebuggerUrl")),
    }


def list_targets(args):
    targets = read_json_url(f"http://127.0.0.1:{args.port}/json/list")
    print_json("TARGETS", [target_summary(target) for target in targets])


def target_matches(args):
    targets = read_json_url(f"http://127.0.0.1:{args.port}/json/list")
    matches = [
        target for target in targets
        if target.get("webSocketDebuggerUrl") and args.target_marker in target.get("url", "")
    ]
    if not matches:
        raise RuntimeError(f"No DevTools target matched {args.target_marker!r} on port {args.port}")
    if args.all_targets:
        return matches
    return [matches[0]]


def context_probe_expression():
    return """
(() => ({
  href: location.href,
  title: document.title,
  bodyTextLength: document.body?.innerText?.length || 0,
  hasAgentsRtl: Boolean(window.__agentsRtl),
  hasReplyTracer: Boolean(window.__agentsRtlReplyTrace),
  reactFiberElements: [...document.querySelectorAll("*")]
    .filter((element) => Object.keys(element).some((key) => key.startsWith("__reactFiber$")))
    .length
}))()
"""


def local_rtl_expression():
    part_paths = sorted(RTL_SCRIPT_PARTS_DIRECTORY.glob("*.js"))
    if not part_paths:
        raise RuntimeError(f"No RTL script parts found in {RTL_SCRIPT_PARTS_DIRECTORY}")
    force_reload_expression = """
if (window.__agentsRtl?.installed) {
  window.__agentsRtl.version = String(window.__agentsRtl.version || "") + "-local-reload";
}
"""
    return force_reload_expression + "".join(
        part_path.read_text(encoding="utf-8") for part_path in part_paths
    )


def context_score(probe):
    return (
        int(probe.get("hasAgentsRtl") is True) * 1000
        + min(int(probe.get("bodyTextLength") or 0), 500)
        + min(int(probe.get("reactFiberElements") or 0), 200)
    )


def select_context(sock, next_id, events, require_body):
    next_id, contexts = collect_runtime_contexts(sock, next_id, events)
    if not contexts:
        raise RuntimeError("No runtime contexts were reported by DevTools")

    probes = []
    for context in contexts:
        next_id, probe = evaluate_expression(sock, next_id, events, context["id"], context_probe_expression())
        probes.append({"context": context, "probe": probe, "score": context_score(probe)})

    probes.sort(key=lambda item: item["score"], reverse=True)
    selected = probes[0]
    if require_body and int(selected["probe"].get("bodyTextLength") or 0) <= 0:
        raise RuntimeError("Selected Codex context has empty body text")
    return next_id, selected["context"], selected["probe"], probes


def evaluate_on_target(args, target, expression):
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, context, selected_probe, probes = select_context(sock, next_id, events, args.require_body)
        next_id, value = evaluate_expression(sock, next_id, events, context["id"], expression)
        return {
            "target": target_summary(target),
            "selectedContext": selected_probe,
            "contextCandidates": [item["probe"] for item in probes],
            "value": value,
        }
    finally:
        sock.close()


def run_expression_command(args, expression, label):
    if args.delay_sec < 0:
        raise RuntimeError("--delay-sec must be >= 0")
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)
    results = [evaluate_on_target(args, target, expression) for target in target_matches(args)]
    print_json(label, results)


def click_list_rename_on_target(args, target, reinstall_listeners):
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, context, selected_probe, probes = select_context(sock, next_id, events, args.require_body)
        if reinstall_listeners:
            next_id, _ = evaluate_expression(
                sock,
                next_id,
                events,
                context["id"],
                REINSTALL_LIST_RENAME_LISTENERS_EXPRESSION,
            )
        next_id, button_center = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            LIST_RENAME_BUTTON_CENTER_EXPRESSION,
        )
        x = float(button_center["x"])
        y = float(button_center["y"])
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        time.sleep(0.1)
        next_id, click_result = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            LIST_RENAME_CLICK_RESULT_EXPRESSION,
        )
        return {
            "target": target_summary(target),
            "selectedContext": selected_probe,
            "contextCandidates": [item["probe"] for item in probes],
            "reinstalledListeners": reinstall_listeners,
            "button": button_center,
            "result": click_result,
        }
    finally:
        sock.close()


def run_click_list_rename_command(args, reinstall_listeners):
    if args.delay_sec < 0:
        raise RuntimeError("--delay-sec must be >= 0")
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)
    results = [
        click_list_rename_on_target(args, target, reinstall_listeners)
        for target in target_matches(args)
    ]
    print_json("CLICK_LIST_RENAME", results)


def trace_list_rename_lifecycle_on_target(args, target):
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, context, selected_probe, probes = select_context(sock, next_id, events, args.require_body)
        next_id, _ = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            INSTALL_LIST_RENAME_LIFECYCLE_PROBE_EXPRESSION,
        )
        next_id, button_center = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            LIST_RENAME_BUTTON_CENTER_EXPRESSION,
        )
        x = float(button_center["x"])
        y = float(button_center["y"])
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        time.sleep(4)
        next_id, lifecycle_result = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            LIST_RENAME_LIFECYCLE_RESULT_EXPRESSION,
        )
        return {
            "target": target_summary(target),
            "selectedContext": selected_probe,
            "contextCandidates": [item["probe"] for item in probes],
            "button": button_center,
            "result": lifecycle_result,
        }
    finally:
        sock.close()


def run_trace_list_rename_lifecycle_command(args):
    if args.delay_sec < 0:
        raise RuntimeError("--delay-sec must be >= 0")
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)
    results = [
        trace_list_rename_lifecycle_on_target(args, target)
        for target in target_matches(args)
    ]
    print_json("TRACE_LIST_RENAME_LIFECYCLE", results)


def trace_list_rename_submit_on_target(args, target):
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, context, selected_probe, probes = select_context(sock, next_id, events, args.require_body)
        next_id, _ = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            INSTALL_RENAME_SUBMIT_PROBE_EXPRESSION,
        )
        next_id, button_center = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            LIST_RENAME_BUTTON_CENTER_EXPRESSION,
        )
        x = float(button_center["x"])
        y = float(button_center["y"])
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        time.sleep(0.1)
        next_id, save_button_probe = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            PREPARE_RENAME_SUBMIT_EXPRESSION,
        )
        save_x = float(save_button_probe["saveButtonCenter"]["x"])
        save_y = float(save_button_probe["saveButtonCenter"]["y"])
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": save_x, "y": save_y, "button": "left", "clickCount": 1},
        )
        next_id, _ = send_cdp_command(
            sock,
            next_id,
            events,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": save_x, "y": save_y, "button": "left", "clickCount": 1},
        )
        time.sleep(0.1)
        next_id, submit_result = evaluate_expression(
            sock,
            next_id,
            events,
            context["id"],
            RENAME_SUBMIT_RESULT_EXPRESSION,
        )
        return {
            "target": target_summary(target),
            "selectedContext": selected_probe,
            "contextCandidates": [item["probe"] for item in probes],
            "renameButton": button_center,
            "saveButton": save_button_probe,
            "result": submit_result,
        }
    finally:
        sock.close()


def run_trace_list_rename_submit_command(args):
    if args.delay_sec < 0:
        raise RuntimeError("--delay-sec must be >= 0")
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)
    results = [
        trace_list_rename_submit_on_target(args, target)
        for target in target_matches(args)
    ]
    print_json("TRACE_LIST_RENAME_SUBMIT", results)


def run_command(args):
    if args.command == "list":
        list_targets(args)
        return
    if args.command == "probe":
        run_expression_command(args, PROBE_EXPRESSION, "PROBE")
        return
    if args.command == "inspect-token-usage":
        run_expression_command(args, TOKEN_USAGE_PROBE_EXPRESSION, "TOKEN_USAGE_PROBE")
        return
    if args.command == "inspect-controls":
        run_expression_command(args, CONTROLS_PROBE_EXPRESSION, "CONTROLS_PROBE")
        return
    if args.command == "apply-list-controls":
        run_expression_command(args, APPLY_LIST_CONTROLS_PROBE_EXPRESSION, "APPLY_LIST_CONTROLS_PROBE")
        return
    if args.command == "test-list-rename-open":
        run_expression_command(args, TEST_LIST_RENAME_OPEN_EXPRESSION, "TEST_LIST_RENAME_OPEN")
        return
    if args.command == "inspect-list-bindings":
        run_expression_command(args, LIST_BINDINGS_PROBE_EXPRESSION, "LIST_BINDINGS_PROBE")
        return
    if args.command == "install-rename-event-tracer":
        run_expression_command(args, INSTALL_RENAME_EVENT_TRACER_EXPRESSION, "RENAME_EVENT_TRACER_INSTALLED")
        return
    if args.command == "rename-event-tracer-summary":
        run_expression_command(args, RENAME_EVENT_TRACER_SUMMARY_EXPRESSION, "RENAME_EVENT_TRACER_SUMMARY")
        return
    if args.command == "click-list-rename":
        run_click_list_rename_command(args, False)
        return
    if args.command == "trace-list-rename-lifecycle":
        run_trace_list_rename_lifecycle_command(args)
        return
    if args.command == "trace-list-rename-submit":
        run_trace_list_rename_submit_command(args)
        return
    if args.command == "reinstall-and-click-list-rename":
        run_click_list_rename_command(args, True)
        return
    if args.command == "inspect-native-ipc":
        run_expression_command(args, NATIVE_IPC_PROBE_EXPRESSION, "NATIVE_IPC_PROBE")
        return
    if args.command == "inject-local-rtl":
        run_expression_command(args, local_rtl_expression(), "LOCAL_RTL_INJECTED")
        return
    if args.command == "test-native-rename":
        run_expression_command(args, NATIVE_RENAME_SAME_TITLE_EXPRESSION, "NATIVE_RENAME_SAME_TITLE")
        return
    if args.command == "invalidate-rtl-version":
        run_expression_command(args, INVALIDATE_RTL_VERSION_EXPRESSION, "RTL_VERSION_INVALIDATED")
        return
    if args.command == "inspect-rename-runtime":
        run_expression_command(args, RENAME_RUNTIME_PROBE_EXPRESSION, "RENAME_RUNTIME_PROBE")
        return
    if args.command == "install-reply-tracer":
        run_expression_command(args, REPLY_TRACER_EXPRESSION, "REPLY_TRACER_INSTALLED")
        return
    if args.command == "summary":
        run_expression_command(args, SUMMARY_EXPRESSION, "REPLY_TRACER_SUMMARY")
        return
    if args.command == "stop":
        run_expression_command(args, STOP_EXPRESSION, "REPLY_TRACER_STOPPED")
        return
    raise RuntimeError(f"Unsupported command: {args.command}")


def main():
    try:
        run_command(parse_args())
    except Exception as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
