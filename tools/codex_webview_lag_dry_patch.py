#!/usr/bin/env python3
import argparse
import json
import sys
import time

from codex_webview_profiler import (
    collect_runtime_contexts,
    connect_websocket,
    evaluate_expression,
    read_json_url,
)


DEFAULT_TARGET_MARKER = "extensionId=openai.chatgpt"


STATUS_EXPRESSION = r"""
(() => {
  const elements = [...document.querySelectorAll("*")].slice(0, 2500);
  const animatedCount = elements.filter((element) => {
    const style = getComputedStyle(element);
    return style.animationName !== "none" || style.transitionDuration !== "0s";
  }).length;
  return {
    href: location.href,
    title: document.title,
    bodyTextLength: document.body?.innerText?.length || 0,
    hasPatch: Boolean(window.__agentsRtlLagDryPatch?.installed),
    patchInstalledAt: window.__agentsRtlLagDryPatch?.installedAt || null,
    stylePresent: Boolean(document.getElementById("agents-rtl-lag-dry-patch-style")),
    sampledElements: elements.length,
    animatedCount,
  };
})()
"""


INJECT_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlLagDryPatch";
  const STYLE_ID = "agents-rtl-lag-dry-patch-style";
  if (window[KEY]?.revert) window[KEY].revert();

  const styleElement = document.createElement("style");
  styleElement.id = STYLE_ID;
  styleElement.textContent = `
    html[data-agents-rtl-lag-dry-patch="1"],
    html[data-agents-rtl-lag-dry-patch="1"] * {
      scroll-behavior: auto !important;
    }

    html[data-agents-rtl-lag-dry-patch="1"] *,
    html[data-agents-rtl-lag-dry-patch="1"] *::before,
    html[data-agents-rtl-lag-dry-patch="1"] *::after {
      animation-delay: 0s !important;
      animation-duration: 0.001ms !important;
      animation-iteration-count: 1 !important;
      transition-delay: 0s !important;
      transition-duration: 0.001ms !important;
    }

    html[data-agents-rtl-lag-dry-patch="1"] [class*="shimmer"],
    html[data-agents-rtl-lag-dry-patch="1"] [class*="Shimmer"],
    html[data-agents-rtl-lag-dry-patch="1"] [class*="animate-"],
    html[data-agents-rtl-lag-dry-patch="1"] [style*="animation"] {
      animation: none !important;
      background-image: none !important;
    }

    html[data-agents-rtl-lag-dry-patch="1"] #agents-rtl-codex-chat-tabs {
      contain: layout style paint !important;
    }
  `;
  document.documentElement.dataset.agentsRtlLagDryPatch = "1";
  document.documentElement.append(styleElement);

  const originalStartViewTransition = document.startViewTransition;
  if (typeof originalStartViewTransition === "function") {
    document.startViewTransition = (callback) => {
      const result = callback?.();
      return {
        ready: Promise.resolve(),
        updateCallbackDone: Promise.resolve(result),
        finished: Promise.resolve(result),
        skipTransition: () => {},
      };
    };
  }

  window[KEY] = {
    installed: true,
    installedAt: new Date().toISOString(),
    revert: () => {
      document.getElementById(STYLE_ID)?.remove();
      delete document.documentElement.dataset.agentsRtlLagDryPatch;
      if (typeof originalStartViewTransition === "function") {
        document.startViewTransition = originalStartViewTransition;
      }
      window[KEY] = null;
    },
  };
  return {
    installed: true,
    href: location.href,
    title: document.title,
  };
})()
"""


REVERT_EXPRESSION = r"""
(() => {
  if (window.__agentsRtlLagDryPatch?.revert) {
    window.__agentsRtlLagDryPatch.revert();
    return { reverted: true, href: location.href, title: document.title };
  }
  document.getElementById("agents-rtl-lag-dry-patch-style")?.remove();
  delete document.documentElement.dataset.agentsRtlLagDryPatch;
  return { reverted: false, href: location.href, title: document.title };
})()
"""


INSTALL_RENDER_PROBE_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlRenderProbe";
  if (window[KEY]?.stop) window[KEY].stop();

  const state = {
    installedAt: new Date().toISOString(),
    href: location.href,
    samples: [],
    longTasks: [],
    totals: {
      mutationRecords: 0,
      addedNodes: 0,
      removedNodes: 0,
      characterDataRecords: 0,
      attributeRecords: 0,
      longTaskCount: 0,
      longTaskMs: 0,
    },
  };

  const counters = {
    mutationRecords: 0,
    addedNodes: 0,
    removedNodes: 0,
    characterDataRecords: 0,
    attributeRecords: 0,
  };

  const mutationObserver = new MutationObserver((records) => {
    counters.mutationRecords += records.length;
    state.totals.mutationRecords += records.length;
    records.forEach((record) => {
      if (record.type === "childList") {
        counters.addedNodes += record.addedNodes.length;
        counters.removedNodes += record.removedNodes.length;
        state.totals.addedNodes += record.addedNodes.length;
        state.totals.removedNodes += record.removedNodes.length;
        return;
      }
      if (record.type === "characterData") {
        counters.characterDataRecords += 1;
        state.totals.characterDataRecords += 1;
        return;
      }
      if (record.type === "attributes") {
        counters.attributeRecords += 1;
        state.totals.attributeRecords += 1;
      }
    });
  });

  mutationObserver.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
  });

  let longTaskObserver = null;
  if (window.PerformanceObserver &&
      PerformanceObserver.supportedEntryTypes?.includes("longtask")) {
    longTaskObserver = new PerformanceObserver((list) => {
      list.getEntries().forEach((entry) => {
        const longTask = {
          at: Math.round(performance.now()),
          durationMs: Math.round(entry.duration * 100) / 100,
          name: entry.name || "",
        };
        state.longTasks.push(longTask);
        if (state.longTasks.length > 120) state.longTasks.shift();
        state.totals.longTaskCount += 1;
        state.totals.longTaskMs += entry.duration;
      });
    });
    longTaskObserver.observe({ entryTypes: ["longtask"] });
  }

  const activeTabText = () =>
    document.querySelector("#agents-rtl-codex-chat-tabs button[data-active='1']")?.textContent || "";

  const sample = (label = "tick") => {
    const allElements = document.getElementsByTagName("*");
    const sampleValue = {
      at: Date.now(),
      performanceNow: Math.round(performance.now()),
      label,
      activeTabText: activeTabText(),
      nodeCount: allElements.length,
      bodyTextLength: document.body?.textContent?.length || 0,
      scrollHeight: document.scrollingElement?.scrollHeight || 0,
      clientHeight: document.scrollingElement?.clientHeight || 0,
      agentsRtlNodeCount: document.querySelectorAll("[id^='agents-rtl'],[class*='agents-rtl']").length,
      mutationRecords: counters.mutationRecords,
      addedNodes: counters.addedNodes,
      removedNodes: counters.removedNodes,
      characterDataRecords: counters.characterDataRecords,
      attributeRecords: counters.attributeRecords,
      longTaskCount: state.totals.longTaskCount,
      longTaskMs: Math.round(state.totals.longTaskMs * 100) / 100,
    };
    state.samples.push(sampleValue);
    if (state.samples.length > 180) state.samples.shift();
    counters.mutationRecords = 0;
    counters.addedNodes = 0;
    counters.removedNodes = 0;
    counters.characterDataRecords = 0;
    counters.attributeRecords = 0;
    return sampleValue;
  };

  const intervalId = setInterval(() => sample(), 1000);
  window[KEY] = {
    installed: true,
    state,
    sample,
    summary: () => ({
      installedAt: state.installedAt,
      href: state.href,
      sampleCount: state.samples.length,
      latestSamples: state.samples.slice(-30),
      longTasks: state.longTasks.slice(-40),
      totals: {
        ...state.totals,
        longTaskMs: Math.round(state.totals.longTaskMs * 100) / 100,
      },
    }),
    stop: () => {
      clearInterval(intervalId);
      mutationObserver.disconnect();
      longTaskObserver?.disconnect();
    },
  };

  return window[KEY].sample("install");
})()
"""


SUMMARY_RENDER_PROBE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlRenderProbe?.summary) {
    throw new Error("Render probe is not installed");
  }
  return window.__agentsRtlRenderProbe.summary();
})()
"""


STOP_RENDER_PROBE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlRenderProbe?.summary) {
    throw new Error("Render probe is not installed");
  }
  const summary = window.__agentsRtlRenderProbe.summary();
  window.__agentsRtlRenderProbe.stop();
  window.__agentsRtlRenderProbe = null;
  return summary;
})()
"""


INSTALL_ATTRIBUTE_PROBE_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlAttributeProbe";
  if (window[KEY]?.stop) window[KEY].stop();

  const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const shortText = (value, maxLength = 120) => {
    const text = compact(value);
    return text.length > maxLength ? text.slice(0, maxLength) + "..." : text;
  };
  const elementLabel = (element) => {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return "<non-element>";
    const tag = element.tagName.toLowerCase();
    const id = element.id ? "#" + element.id : "";
    const classText = shortText(element.className || "", 90);
    const role = element.getAttribute("role") ? "[role=" + element.getAttribute("role") + "]" : "";
    const aria = element.getAttribute("aria-label") ? "[aria-label=" + shortText(element.getAttribute("aria-label"), 50) + "]" : "";
    return [tag + id, role, aria, classText ? "." + classText.replace(/\s+/g, ".") : ""].join("");
  };

  const state = {
    installedAt: new Date().toISOString(),
    href: location.href,
    attributeCounts: {},
    targetCounts: {},
    attributeTargetCounts: {},
    samples: [],
    totalRecords: 0,
    totalAttributes: 0,
    totalChildList: 0,
    totalCharacterData: 0,
  };

  const increment = (object, key, amount = 1) => {
    object[key] = (object[key] || 0) + amount;
  };
  const topEntries = (object, limit = 25) =>
    Object.entries(object)
      .sort((left, right) => right[1] - left[1])
      .slice(0, limit)
      .map(([key, count]) => ({ key, count }));

  const observer = new MutationObserver((records) => {
    state.totalRecords += records.length;
    records.forEach((record) => {
      if (record.type === "attributes") {
        state.totalAttributes += 1;
        const attributeName = record.attributeName || "<unknown>";
        const targetLabel = elementLabel(record.target);
        increment(state.attributeCounts, attributeName);
        increment(state.targetCounts, targetLabel);
        increment(state.attributeTargetCounts, attributeName + " @ " + targetLabel);
        return;
      }
      if (record.type === "childList") {
        state.totalChildList += 1;
        return;
      }
      if (record.type === "characterData") {
        state.totalCharacterData += 1;
      }
    });
  });

  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeOldValue: false,
  });

  const sample = (label = "tick") => {
    const value = {
      at: Date.now(),
      performanceNow: Math.round(performance.now()),
      label,
      totalRecords: state.totalRecords,
      totalAttributes: state.totalAttributes,
      totalChildList: state.totalChildList,
      totalCharacterData: state.totalCharacterData,
      topAttributes: topEntries(state.attributeCounts, 15),
      topTargets: topEntries(state.targetCounts, 12),
      topAttributeTargets: topEntries(state.attributeTargetCounts, 20),
    };
    state.samples.push(value);
    if (state.samples.length > 90) state.samples.shift();
    return value;
  };

  const intervalId = setInterval(() => sample(), 1000);
  window[KEY] = {
    installed: true,
    state,
    sample,
    summary: () => ({
      installedAt: state.installedAt,
      href: state.href,
      latest: state.samples.at(-1) || sample("summary"),
      samples: state.samples.slice(-20),
    }),
    stop: () => {
      clearInterval(intervalId);
      observer.disconnect();
    },
  };
  return window[KEY].sample("install");
})()
"""


SUMMARY_ATTRIBUTE_PROBE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlAttributeProbe?.summary) {
    throw new Error("Attribute probe is not installed");
  }
  return window.__agentsRtlAttributeProbe.summary();
})()
"""


STOP_ATTRIBUTE_PROBE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlAttributeProbe?.summary) {
    throw new Error("Attribute probe is not installed");
  }
  const summary = window.__agentsRtlAttributeProbe.summary();
  window.__agentsRtlAttributeProbe.stop();
  window.__agentsRtlAttributeProbe = null;
  return summary;
})()
"""


def install_conversation_cache_trim_expression(keep_turns, trim_active):
    if keep_turns < 0:
        raise RuntimeError("--keep-turns must be >= 0")
    trim_active_json = "true" if trim_active else "false"
    return f"""
(() => {{
  const KEY = "__agentsRtlConversationCacheTrimPatch";
  if (window[KEY]?.revert) window[KEY].revert();

  const keepTurns = {keep_turns};
  const trimActive = {trim_active_json};
  const fiberKey = (element) => Object.keys(element || {{}}).find((key) => key.startsWith("__reactFiber$"));
  const findQueryClient = () => {{
    if (window.__agentsRtl?.codexReactQueryClient?.getQueryCache) return window.__agentsRtl.codexReactQueryClient;
    const roots = new Set();
    document.querySelectorAll("*").forEach((element) => {{
      const key = fiberKey(element);
      if (!key) return;
      let fiber = element[key];
      while (fiber?.return) fiber = fiber.return;
      if (fiber) roots.add(fiber);
    }});
    const stack = [...roots].map((root) => root.child).filter(Boolean);
    const seenFibers = new Set();
    while (stack.length > 0) {{
      const fiber = stack.pop();
      if (!fiber || seenFibers.has(fiber)) continue;
      seenFibers.add(fiber);
      for (const props of [fiber.memoizedProps, fiber.pendingProps].filter(Boolean)) {{
        for (const candidate of [props.queryClient, props.client]) {{
          if (candidate?.getQueryCache) return candidate;
        }}
      }}
      let hook = fiber.memoizedState;
      let hookDepth = 0;
      while (hook && hookDepth < 12) {{
        for (const candidate of [hook.memoizedState, hook.memoizedState?.current?.queryClient]) {{
          if (candidate?.getQueryCache) return candidate;
        }}
        hook = hook.next;
        hookDepth += 1;
      }}
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }}
    return null;
  }};
  const queryClient = findQueryClient();
  if (!queryClient?.getQueryCache) throw new Error("React Query client was not found");
  if (typeof queryClient.setQueryData !== "function") throw new Error("React Query client does not expose setQueryData");

  const queryCache = queryClient.getQueryCache();
  const activeId =
    document.querySelector("#agents-rtl-codex-chat-tabs button[data-active='1']")?.dataset?.conversationId ||
    (() => {{
      const match = String(location.pathname || "").match(/\\/local\\/([^/?#]+)/);
      if (!match) return "";
      try {{ return decodeURIComponent(match[1]); }} catch (error) {{ return ""; }}
    }})();
  if (!activeId) throw new Error("Could not determine active Codex conversation id");

  const safeJsonSize = (value) => {{
    try {{ return JSON.stringify(value)?.length || 0; }} catch (error) {{ return -1; }}
  }};
  const conversationId = (conversation) => String(conversation?.id || conversation?.threadId || conversation?.conversationId || "");
  const isConversationArray = (value) =>
    Array.isArray(value) &&
    value.some((item) => item && typeof item === "object" && Array.isArray(item.turns));
  const queries = queryCache.getAll().filter((query) => isConversationArray(query?.state?.data));
  if (queries.length === 0) throw new Error("No conversation arrays were found in React Query cache");

  const originals = [];
  const stats = {{
    installedAt: new Date().toISOString(),
    activeId,
    keepTurns,
    trimActive,
    queryCount: queries.length,
    trimmedConversations: 0,
    removedTurns: 0,
    beforeKB: 0,
    afterKB: 0,
    queries: [],
  }};

  queries.forEach((query) => {{
    const originalData = query.state.data;
    const beforeBytes = safeJsonSize(originalData);
    let queryTrimmedConversations = 0;
    let queryRemovedTurns = 0;
    const nextData = originalData.map((conversation) => {{
      if (!Array.isArray(conversation?.turns)) return conversation;
      const id = conversationId(conversation);
      if (!trimActive && id === activeId) return conversation;
      if (conversation.turns.length <= keepTurns) return conversation;
      queryTrimmedConversations += 1;
      queryRemovedTurns += conversation.turns.length - keepTurns;
      return {{
        ...conversation,
        turns: keepTurns === 0 ? [] : conversation.turns.slice(-keepTurns),
      }};
    }});
    if (queryRemovedTurns === 0) return;
    originals.push({{ queryKey: query.queryKey, data: originalData }});
    queryClient.setQueryData(query.queryKey, nextData);
    const afterBytes = safeJsonSize(nextData);
    stats.trimmedConversations += queryTrimmedConversations;
    stats.removedTurns += queryRemovedTurns;
    stats.beforeKB += Math.round(beforeBytes / 1024);
    stats.afterKB += Math.round(afterBytes / 1024);
    stats.queries.push({{
      key: JSON.stringify(query.queryKey).slice(0, 180),
      beforeKB: Math.round(beforeBytes / 1024),
      afterKB: Math.round(afterBytes / 1024),
      trimmedConversations: queryTrimmedConversations,
      removedTurns: queryRemovedTurns,
    }});
  }});
  if (originals.length === 0) throw new Error("No conversations needed trimming");

  window[KEY] = {{
    installed: true,
    stats,
    status: () => ({{
      installed: true,
      stats,
    }}),
    revert: () => {{
      originals.forEach((original) => queryClient.setQueryData(original.queryKey, original.data));
      window[KEY] = null;
      return {{
        reverted: true,
        restoredQueries: originals.length,
        stats,
      }};
    }},
  }};
  return window[KEY].status();
}})()
"""


STATUS_CONVERSATION_CACHE_TRIM_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlConversationCacheTrimPatch?.status) {
    return { installed: false };
  }
  return window.__agentsRtlConversationCacheTrimPatch.status();
})()
"""


REVERT_CONVERSATION_CACHE_TRIM_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlConversationCacheTrimPatch?.revert) {
    return { reverted: false, installed: false };
  }
  return window.__agentsRtlConversationCacheTrimPatch.revert();
})()
"""


SET_CONVERSATION_DETAIL_PROSE_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlConversationDetailModePatch";
  if (window[KEY]?.revert) window[KEY].revert();

  const fiberKey = (element) => Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
  const findQueryClient = () => {
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
      for (const props of [fiber.memoizedProps, fiber.pendingProps].filter(Boolean)) {
        for (const candidate of [props.queryClient, props.client]) {
          if (candidate?.getQueryCache) return candidate;
        }
      }
      let hook = fiber.memoizedState;
      let hookDepth = 0;
      while (hook && hookDepth < 12) {
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
  const queryClient = findQueryClient();
  if (!queryClient?.getQueryData) throw new Error("React Query client was not found");
  if (typeof queryClient.setQueryData !== "function") throw new Error("React Query client does not expose setQueryData");

  const queryKey = ["vscode", "get-settings"];
  const originalData = queryClient.getQueryData(queryKey);
  if (!originalData?.values) throw new Error("VS Code settings query data was not found");
  const originalMode = originalData.values.conversationDetailMode;
  const nextData = {
    ...originalData,
    values: {
      ...originalData.values,
      conversationDetailMode: "STEPS_PROSE",
    },
  };
  queryClient.setQueryData(queryKey, nextData);
  const stats = {
    installedAt: new Date().toISOString(),
    originalMode,
    nextMode: "STEPS_PROSE",
  };
  window[KEY] = {
    installed: true,
    stats,
    status: () => ({
      installed: true,
      stats,
      currentMode: queryClient.getQueryData(queryKey)?.values?.conversationDetailMode,
    }),
    revert: () => {
      queryClient.setQueryData(queryKey, originalData);
      window[KEY] = null;
      return {
        reverted: true,
        restoredMode: originalMode,
        stats,
      };
    },
  };
  return window[KEY].status();
})()
"""


STATUS_CONVERSATION_DETAIL_PROSE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlConversationDetailModePatch?.status) {
    return { installed: false };
  }
  return window.__agentsRtlConversationDetailModePatch.status();
})()
"""


REVERT_CONVERSATION_DETAIL_PROSE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlConversationDetailModePatch?.revert) {
    return { reverted: false, installed: false };
  }
  return window.__agentsRtlConversationDetailModePatch.revert();
})()
"""


STATUS_AGENTS_RTL_RUNTIME_EXPRESSION = r"""
(() => {
  const runtime = window.__agentsRtl;
  return {
    found: Boolean(runtime),
    stopped: runtime?.stopped === true,
    version: runtime?.version || null,
    localStorageEnabled: localStorage.getItem("agentsRtl.enabled"),
    hasTabs: Boolean(document.getElementById("agents-rtl-codex-chat-tabs")),
    hasControls: Boolean(document.getElementById("agents-rtl-controls")),
    href: location.href,
    title: document.title,
  };
})()
"""


STOP_AGENTS_RTL_RUNTIME_EXPRESSION = r"""
(() => {
  const runtime = window.__agentsRtl;
  if (!runtime?.stop) throw new Error("Agents RTL runtime stop() was not found");
  runtime.stop();
  return {
    stopped: runtime.stopped === true,
    version: runtime.version || null,
    localStorageEnabled: localStorage.getItem("agentsRtl.enabled"),
    hasTabs: Boolean(document.getElementById("agents-rtl-codex-chat-tabs")),
    hasControls: Boolean(document.getElementById("agents-rtl-controls")),
    href: location.href,
    title: document.title,
  };
})()
"""


START_AGENTS_RTL_RUNTIME_EXPRESSION = r"""
(() => {
  const runtime = window.__agentsRtl;
  if (!runtime?.start) throw new Error("Agents RTL runtime start() was not found");
  runtime.start();
  return {
    stopped: runtime.stopped === true,
    version: runtime.version || null,
    localStorageEnabled: localStorage.getItem("agentsRtl.enabled"),
    hasTabs: Boolean(document.getElementById("agents-rtl-codex-chat-tabs")),
    hasControls: Boolean(document.getElementById("agents-rtl-controls")),
    href: location.href,
    title: document.title,
  };
})()
"""


INSTALL_AGENTS_RTL_HARD_PAUSE_EXPRESSION = r"""
(() => {
  const KEY = "__agentsRtlHardPause";
  const runtime = window.__agentsRtl;
  if (!runtime) throw new Error("Agents RTL runtime was not found");
  if (window[KEY]?.revert) window[KEY].revert();

  const functionNames = [
    "apply",
    "renderCodexChatTabs",
    "updateCodexConversations",
    "applyCodexConversationListRenameControls",
    "installControlButtons",
    "syncScrollButtons",
    "updateControlButtons",
    "ensureObserver",
  ];

  const originals = {};
  const replaced = [];
  for (const functionName of functionNames) {
    if (typeof runtime[functionName] !== "function") continue;
    originals[functionName] = runtime[functionName];
    runtime[functionName] = () => ({
      hardPaused: true,
      functionName,
    });
    replaced.push(functionName);
  }

  runtime.stopped = true;
  localStorage.setItem("agentsRtl.enabled", "0");

  window[KEY] = {
    installed: true,
    installedAt: new Date().toISOString(),
    replaced,
    status: () => ({
      installed: true,
      replaced,
      stopped: runtime.stopped === true,
      localStorageEnabled: localStorage.getItem("agentsRtl.enabled"),
      hasTabs: Boolean(document.getElementById("agents-rtl-codex-chat-tabs")),
      hasControls: Boolean(document.getElementById("agents-rtl-controls")),
    }),
    revert: () => {
      for (const [functionName, originalFunction] of Object.entries(originals)) {
        runtime[functionName] = originalFunction;
      }
      window[KEY] = null;
      return {
        reverted: true,
        restored: Object.keys(originals),
      };
    },
  };
  return window[KEY].status();
})()
"""


STATUS_AGENTS_RTL_HARD_PAUSE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlHardPause?.status) {
    return { installed: false };
  }
  return window.__agentsRtlHardPause.status();
})()
"""


REVERT_AGENTS_RTL_HARD_PAUSE_EXPRESSION = r"""
(() => {
  if (!window.__agentsRtlHardPause?.revert) {
    return { reverted: false, installed: false };
  }
  return window.__agentsRtlHardPause.revert();
})()
"""


STATUS_CODEX_SETTINGS_EXPRESSION = r"""
(() => {
  const fiberKey = (element) => Object.keys(element || {}).find((key) => key.startsWith("__reactFiber$"));
  const findQueryClient = () => {
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
      for (const props of [fiber.memoizedProps, fiber.pendingProps].filter(Boolean)) {
        for (const candidate of [props.queryClient, props.client]) {
          if (candidate?.getQueryCache && candidate?.getQueryData) return candidate;
        }
      }
      let hook = fiber.memoizedState;
      let hookDepth = 0;
      while (hook && hookDepth < 12) {
        for (const candidate of [hook.memoizedState, hook.memoizedState?.current?.queryClient]) {
          if (candidate?.getQueryCache && candidate?.getQueryData) return candidate;
        }
        hook = hook.next;
        hookDepth += 1;
      }
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }
    return null;
  };
  const queryClient = findQueryClient();
  if (!queryClient?.getQueryCache) throw new Error("React Query client was not found");

  const settings = queryClient.getQueryData(["vscode", "get-settings"]) || null;
  const queries = queryClient.getQueryCache().getAll().map((query) => {
    const data = query.state?.data;
    return {
      key: query.queryKey,
      dataType: Array.isArray(data) ? "array" : typeof data,
      arrayLength: Array.isArray(data) ? data.length : null,
      jsonKB: Math.round(JSON.stringify(data ?? null).length / 1024),
      updatedAt: query.state?.dataUpdatedAt || 0,
    };
  }).sort((left, right) => right.jsonKB - left.jsonKB).slice(0, 12);

  return {
    settingsKeys: settings?.values ? Object.keys(settings.values).sort() : [],
    settingsValues: settings?.values || null,
    largestQueries: queries,
  };
})()
"""


STATUS_RECENT_CONVERSATIONS_EXPRESSION = r"""
(() => {
  const client = window.__agentsRtl?.codexReactQueryClient;
  if (!client?.getQueryCache) throw new Error("Agents RTL React Query client was not found");
  const activeId =
    document.querySelector("#agents-rtl-codex-chat-tabs button[data-active='1']")?.dataset?.conversationId ||
    [...document.querySelectorAll("[aria-current='page'],[data-active='true'],[data-state='active']")]
      .map((element) => element.textContent?.trim())
      .find(Boolean) ||
    null;
  const queries = client.getQueryCache().getAll();
  const conversationQueries = queries
    .filter((query) =>
      Array.isArray(query.state?.data) &&
      query.state.data.some((item) => item?.turns && item?.title)
    )
    .map((query) => {
      const rows = query.state.data;
      return {
        key: query.queryKey,
        arrayLength: rows.length,
        jsonKB: Math.round(JSON.stringify(rows).length / 1024),
        totalTurns: rows.reduce((sum, row) => sum + (row.turns?.length || 0), 0),
        conversations: rows.map((row) => ({
          title: row.title,
          id: row.id,
          sessionId: row.sessionId,
          turnCount: row.turns?.length || 0,
          jsonKB: Math.round(JSON.stringify(row).length / 1024),
          updatedAt: row.updatedAt,
          recencyAt: row.recencyAt,
        })).sort((left, right) => right.jsonKB - left.jsonKB).slice(0, 20),
      };
    })
    .sort((left, right) => right.jsonKB - left.jsonKB);
  return {
    activeId,
    queryCount: conversationQueries.length,
    conversationQueries,
  };
})()
"""


def parse_args():
    parser = argparse.ArgumentParser(
        prog="codex-webview-lag-dry-patch",
        description="Temporarily inject or revert Codex webview lag dry patches and probes.",
    )
    parser.add_argument(
        "command",
        choices=[
            "status",
            "inject",
            "revert",
            "install-render-probe",
            "summary-render-probe",
            "stop-render-probe",
            "install-attribute-probe",
            "summary-attribute-probe",
            "stop-attribute-probe",
            "install-conversation-cache-trim",
            "status-conversation-cache-trim",
            "revert-conversation-cache-trim",
            "set-conversation-detail-prose",
            "status-conversation-detail-prose",
            "revert-conversation-detail-prose",
            "status-agents-rtl-runtime",
            "stop-agents-rtl-runtime",
            "start-agents-rtl-runtime",
            "install-agents-rtl-hard-pause",
            "status-agents-rtl-hard-pause",
            "revert-agents-rtl-hard-pause",
            "status-codex-settings",
            "status-recent-conversations",
        ],
    )
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--target-marker", default=DEFAULT_TARGET_MARKER)
    parser.add_argument("--delay-sec", type=float, default=0)
    parser.add_argument("--all-targets", action="store_true")
    parser.add_argument("--require-body", action="store_true")
    parser.add_argument("--keep-turns", type=int, default=1)
    parser.add_argument("--trim-active", action="store_true")
    return parser.parse_args()


def target_summary(target):
    return {
        "type": target.get("type"),
        "title": target.get("title"),
        "url": target.get("url"),
        "hasWebSocket": bool(target.get("webSocketDebuggerUrl")),
    }


def read_matching_targets(port, target_marker, all_targets):
    targets = read_json_url(f"http://127.0.0.1:{port}/json/list")
    matches = [
        target for target in targets
        if target.get("webSocketDebuggerUrl") and target_marker in target.get("url", "")
    ]
    if not matches:
        target_summaries = [target_summary(target) for target in targets]
        raise RuntimeError(f"No DevTools target matched {target_marker!r} on port {port}: {target_summaries}")
    if all_targets:
        return matches
    return [matches[0]]


def context_probe_expression():
    return """
(() => ({
  href: location.href,
  title: document.title,
  bodyTextLength: document.body?.innerText?.length || 0,
  hasAgentsRtl: Boolean(window.__agentsRtl),
  hasLagDryPatch: Boolean(window.__agentsRtlLagDryPatch?.installed),
  reactFiberElements: [...document.querySelectorAll("*")]
    .filter((element) => Object.keys(element).some((key) => key.startsWith("__reactFiber$")))
    .length
}))()
"""


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


def evaluate_on_target(target, expression, require_body):
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, context, selected_probe, probes = select_context(sock, next_id, events, require_body)
        next_id, value = evaluate_expression(sock, next_id, events, context["id"], expression)
        return {
            "target": target_summary(target),
            "selectedContext": selected_probe,
            "contextCandidates": [item["probe"] for item in probes],
            "value": value,
        }
    finally:
        sock.close()


def command_expression(args):
    command = args.command
    if command == "status":
        return STATUS_EXPRESSION
    if command == "inject":
        return INJECT_EXPRESSION
    if command == "revert":
        return REVERT_EXPRESSION
    if command == "install-render-probe":
        return INSTALL_RENDER_PROBE_EXPRESSION
    if command == "summary-render-probe":
        return SUMMARY_RENDER_PROBE_EXPRESSION
    if command == "stop-render-probe":
        return STOP_RENDER_PROBE_EXPRESSION
    if command == "install-attribute-probe":
        return INSTALL_ATTRIBUTE_PROBE_EXPRESSION
    if command == "summary-attribute-probe":
        return SUMMARY_ATTRIBUTE_PROBE_EXPRESSION
    if command == "stop-attribute-probe":
        return STOP_ATTRIBUTE_PROBE_EXPRESSION
    if command == "install-conversation-cache-trim":
        return install_conversation_cache_trim_expression(args.keep_turns, args.trim_active)
    if command == "status-conversation-cache-trim":
        return STATUS_CONVERSATION_CACHE_TRIM_EXPRESSION
    if command == "revert-conversation-cache-trim":
        return REVERT_CONVERSATION_CACHE_TRIM_EXPRESSION
    if command == "set-conversation-detail-prose":
        return SET_CONVERSATION_DETAIL_PROSE_EXPRESSION
    if command == "status-conversation-detail-prose":
        return STATUS_CONVERSATION_DETAIL_PROSE_EXPRESSION
    if command == "revert-conversation-detail-prose":
        return REVERT_CONVERSATION_DETAIL_PROSE_EXPRESSION
    if command == "status-agents-rtl-runtime":
        return STATUS_AGENTS_RTL_RUNTIME_EXPRESSION
    if command == "stop-agents-rtl-runtime":
        return STOP_AGENTS_RTL_RUNTIME_EXPRESSION
    if command == "start-agents-rtl-runtime":
        return START_AGENTS_RTL_RUNTIME_EXPRESSION
    if command == "install-agents-rtl-hard-pause":
        return INSTALL_AGENTS_RTL_HARD_PAUSE_EXPRESSION
    if command == "status-agents-rtl-hard-pause":
        return STATUS_AGENTS_RTL_HARD_PAUSE_EXPRESSION
    if command == "revert-agents-rtl-hard-pause":
        return REVERT_AGENTS_RTL_HARD_PAUSE_EXPRESSION
    if command == "status-codex-settings":
        return STATUS_CODEX_SETTINGS_EXPRESSION
    if command == "status-recent-conversations":
        return STATUS_RECENT_CONVERSATIONS_EXPRESSION
    raise RuntimeError(f"Unsupported command: {command}")


def print_json(label, value):
    print(label + " " + json.dumps(value, ensure_ascii=False, indent=2))


def run_command(args):
    if args.delay_sec < 0:
        raise RuntimeError("--delay-sec must be >= 0")
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)

    expression = command_expression(args)
    targets = read_matching_targets(args.port, args.target_marker, args.all_targets)
    results = [
        evaluate_on_target(target, expression, args.require_body)
        for target in targets
    ]
    print_json(args.command.upper(), results)


def main():
    try:
        run_command(parse_args())
    except Exception as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
