package main

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"testing"
)

const expectedRTLScriptPartCount = 81
const expectedRTLScriptByteLength = 221808
const expectedRTLScriptSHA256 = "21efc67e552aae3b9478cae544f284406726eaa85dfb249e8b96ac4fc3cafb2f"

var expectedRTLScriptPartNames = []string{
	"00_00_prelude_start.js",
	"00_10_dom_ids.js",
	"00_20_storage_and_tuning.js",
	"00_30_webview_selectors.js",
	"00_31_host_selectors.js",
	"00_32_agent_text_selectors.js",
	"00_40_environment_helpers.js",
	"00_50_gemini_history_trim.js",
	"00_60_install_controls_gate.js",
	"10_styles.js",
	"20_00_storage_booleans.js",
	"20_10_antigravity_select_all.js",
	"20_20_antigravity_enter_fallback.js",
	"20_30_text_helpers.js",
	"20_40_apply_text_direction.js",
	"20_50_restore_text_direction.js",
	"20_60_table_direction.js",
	"20_70_scrollable_element.js",
	"30_00_native_scroll_find.js",
	"30_10_antigravity_scroll_find.js",
	"30_20_native_wheel_scroll.js",
	"30_30_generic_scroll_find.js",
	"31_scroll_actions.js",
	"32_00_button_cluster_position.js",
	"32_10_button_cluster_drag.js",
	"32_20_button_cluster_dom.js",
	"33_visibility_and_text.js",
	"34_00_codex_webview_control_host.js",
	"34_10_gemini_control_host.js",
	"34_20_native_control_hosts.js",
	"35_00_scroll_button_positions.js",
	"35_10_control_button_state.js",
	"35_15_codex_resource_monitor.js",
	"35_20_control_bar_dom.js",
	"40_00_codex_record_fields.js",
	"40_10_codex_sanitize_merge.js",
	"40_20_codex_tab_order_recent.js",
	"40_30_codex_activity_keys.js",
	"40_40_codex_shared_preferences.js",
	"40_45_codex_native_rename.js",
	"49_codex_transient_source.js",
	"50_codex_confirmation.js",
	"51_00_codex_archive_storage.js",
	"51_10_codex_archive_local_cleanup.js",
	"51_20_codex_archive_flow.js",
	"52_00_codex_rename_save.js",
	"52_01_codex_rename_editor_dom.js",
	"52_10_codex_action_buttons.js",
	"53_codex_floating_actions.js",
	"54_00_codex_list_buttons.js",
	"54_10_codex_list_rename_events.js",
	"54_20_codex_transient_listeners.js",
	"60_00_codex_pending_storage.js",
	"60_10_codex_react_fiber.js",
	"60_20_codex_list_rows.js",
	"60_21_codex_list_row_actions.js",
	"60_22_codex_list_controls_apply.js",
	"60_30_codex_react_query.js",
	"60_40_codex_cache_shape.js",
	"60_41_codex_cache_prune_value.js",
	"60_42_codex_cache_remove_query.js",
	"61_00_codex_pending_sources.js",
	"61_10_codex_pending_refresh.js",
	"61_20_codex_status_badges.js",
	"61_30_codex_unread_activity.js",
	"62_00_codex_tab_order.js",
	"62_10_codex_overflow_menu.js",
	"62_11_codex_overflow_listeners.js",
	"62_20_codex_tab_header.js",
	"62_30_codex_tab_navigation.js",
	"62_40_codex_tab_render.js",
	"63_00_control_bar_install.js",
	"63_10_floating_scroll_buttons.js",
	"70_composer_direction.js",
	"71_apply_runtime.js",
	"72_00_same_version_refresh.js",
	"72_10_legacy_listener_cleanup.js",
	"72_20_legacy_dom_cleanup.js",
	"72_30_legacy_attribute_cleanup.js",
	"73_lifecycle_state.js",
	"74_public_api_bootstrap.js",
}

func TestRTLScriptAssemblyIsStable(t *testing.T) {
	entries, err := rtlScriptParts.ReadDir("rtl_script_parts")
	if err != nil {
		t.Fatalf("read RTL script parts: %v", err)
	}
	if len(entries) != expectedRTLScriptPartCount {
		t.Fatalf("expected %d RTL script parts, got %d", expectedRTLScriptPartCount, len(entries))
	}

	for index, expectedPartName := range expectedRTLScriptPartNames {
		if entries[index].Name() != expectedPartName {
			t.Fatalf("RTL script part %d = %q, expected %q", index, entries[index].Name(), expectedPartName)
		}
	}

	assembledScript := mustAssembleRTLScript()
	if len(assembledScript) != expectedRTLScriptByteLength {
		t.Fatalf("assembled RTL script length = %d, expected %d", len(assembledScript), expectedRTLScriptByteLength)
	}

	actualSHA256 := fmt.Sprintf("%x", sha256.Sum256([]byte(assembledScript)))
	if actualSHA256 != expectedRTLScriptSHA256 {
		t.Fatalf("assembled RTL script sha256 = %s, expected %s", actualSHA256, expectedRTLScriptSHA256)
	}
}

func TestRTLScriptIncludesCodexResponseAnnotationDirectionAndHighlight(t *testing.T) {
	assembledScript := mustAssembleRTLScript()
	requiredFragments := []string{
		"li[class*='response-annotation'] .break-words.whitespace-pre-wrap",
		"[role='tooltip']",
		"new Set([\"selected text:\", \"user comment:\"])",
		"applyCodexResponseAnnotationTextDirection();",
		"data-agents-rtl-codex-response-annotation-text",
		"data-agents-rtl-codex-response-annotation-kind",
		"data-browser-comment-editor-surface='true'",
		"data-composer-attachment-pill='true'",
		"='selected-text']",
		"='user-comment']",
	}
	for _, requiredFragment := range requiredFragments {
		if !strings.Contains(assembledScript, requiredFragment) {
			t.Fatalf("assembled RTL script is missing %q", requiredFragment)
		}
	}
}

func TestRTLScriptIncludesAutomaticPlainTextDirectionAndAddToChatHighlight(t *testing.T) {
	assembledScript := mustAssembleRTLScript()
	requiredFragments := []string{
		"new Set([\"txt\", \"text\", \"plaintext\", \"plain text\"])",
		"setAttributeIfChanged(element, \"dir\", \"auto\")",
		"[dir='auto']:dir(rtl)",
		"[dir='auto']:dir(ltr)",
		"applyPlainTextCodeBlockLineDirections(element);",
		`querySelectorAll(":scope > code > span > span")`,
		"data-agents-rtl-codex-add-to-chat-button",
		"const CODEX_ADD_TO_CHAT_BUTTON_LABEL = \"Add to chat\"",
		"applyCodexAddToChatButtonHighlight();",
	}
	for _, requiredFragment := range requiredFragments {
		if !strings.Contains(assembledScript, requiredFragment) {
			t.Fatalf("assembled RTL script is missing %q", requiredFragment)
		}
	}
}

func TestRTLScriptIncludesSharedCodexUnreadState(t *testing.T) {
	assembledScript := mustAssembleRTLScript()
	requiredFragments := []string{
		"codexConversationTurnsFromTurnHistory",
		"history.entitiesByKey",
		"history.islands",
		"nativeUnreadStateKnown",
		"nativeHasUnreadTurn",
		"codexConversationHasUnreadAgentReply",
		"codexLatestAgentReplyActivities",
		"latestAgentReplyActivityRequests",
		"codexLatestCompletedAgentReplyFromConversationRecord",
		"codexConversationNeedsApproval(conversation, pendingApprovalTitleSet)",
		"if (hasUnreadAgentReply)",
	}
	for _, requiredFragment := range requiredFragments {
		if !strings.Contains(assembledScript, requiredFragment) {
			t.Fatalf("assembled RTL script is missing %q", requiredFragment)
		}
	}
}

func TestRTLScriptIncludesCodexResourceMonitorToggleAndMetrics(t *testing.T) {
	assembledScript := mustAssembleRTLScript()
	requiredFragments := []string{
		"agentsRtl.codexResourceMonitorVisible",
		"agentsRtl.codexResourceMonitorResetRequestId",
		"agents-rtl-codex-resource-monitor-toggle",
		"toggleCodexResourceMonitorVisibility",
		"resetCodexResourceMonitorTotals",
		"title: \"Reset monitor totals?\"",
		"confirmLabel: \"Yes\"",
		"cancelLabel: \"No\"",
		"data-agents-rtl-codex-resource-metric-unit",
		"metric-unit='B'",
		"metric-unit='KiB'",
		"metric-unit='MiB'",
		"metric-unit='GiB'",
		"metric-unit='TiB'",
		"uploadBytesPerSecond",
		"uploadedBytesTotal",
		"residentMemoryBytes",
		"cpuPercent",
	}
	for _, requiredFragment := range requiredFragments {
		if !strings.Contains(assembledScript, requiredFragment) {
			t.Fatalf("assembled RTL script is missing %q", requiredFragment)
		}
	}
}
