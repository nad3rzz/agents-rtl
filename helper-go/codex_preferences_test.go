package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWriteCodexSharedPreferencesDropsLegacyRenameAliases(t *testing.T) {
	codexHome := t.TempDir()
	preferencesPath := codexSharedPreferencesPath(codexHome)
	legacyPreferences := []byte(`{
  "codexChatRenames": {"conversation-1": "Legacy alias"},
  "codexChatOrder": ["conversation-1"],
  "codexChatActivityKeys": {"conversation-1": "activity-1"}
}`)
	if err := os.WriteFile(preferencesPath, legacyPreferences, 0600); err != nil {
		t.Fatalf("write legacy preferences: %v", err)
	}

	preferences, err := readCodexSharedPreferences(codexHome)
	if err != nil {
		t.Fatalf("read legacy preferences: %v", err)
	}
	if err := writeCodexSharedPreferences(codexHome, preferences); err != nil {
		t.Fatalf("rewrite preferences: %v", err)
	}

	rewrittenContent, err := os.ReadFile(preferencesPath)
	if err != nil {
		t.Fatalf("read rewritten preferences: %v", err)
	}
	rewrittenObject := map[string]json.RawMessage{}
	if err := json.Unmarshal(rewrittenContent, &rewrittenObject); err != nil {
		t.Fatalf("decode rewritten preferences: %v", err)
	}
	if _, exists := rewrittenObject["codexChatRenames"]; exists {
		t.Fatal("rewritten preferences retained codexChatRenames")
	}
	if len(preferences.CodexChatOrder) != 1 || preferences.CodexChatOrder[0] != "conversation-1" {
		t.Fatalf("unexpected preserved order: %v", preferences.CodexChatOrder)
	}
	if preferences.CodexChatActivityKeys["conversation-1"] != "activity-1" {
		t.Fatalf("unexpected preserved activity keys: %v", preferences.CodexChatActivityKeys)
	}

	temporaryFiles, err := filepath.Glob(filepath.Join(codexHome, ".agents-rtl-preferences.json.*.tmp"))
	if err != nil {
		t.Fatalf("list temporary preference files: %v", err)
	}
	if len(temporaryFiles) != 0 {
		t.Fatalf("temporary preference files were not cleaned: %v", temporaryFiles)
	}
}

func TestLatestAgentReplyActivityKeepsNewestObservation(t *testing.T) {
	preferences := codexSharedPreferences{
		CodexChatActivityKeys: map[string]string{},
		CodexLatestAgentReplyActivities: map[string]codexLatestAgentReplyActivity{
			"conversation-1": {ActivityKey: "newer", OccurredAtMs: 2000},
		},
	}
	changed, err := applyCodexLatestAgentReplyActivityRequest(
		&preferences,
		codexLatestAgentReplyActivityRequest{
			ID: "conversation-1", ActivityKey: "older", OccurredAtMs: 1000,
		},
	)
	if err != nil {
		t.Fatalf("apply older latest-agent-reply activity: %v", err)
	}
	if changed {
		t.Fatal("older latest-agent-reply activity changed preferences")
	}
	if preferences.CodexLatestAgentReplyActivities["conversation-1"].ActivityKey != "newer" {
		t.Fatalf("newer activity was replaced: %+v", preferences.CodexLatestAgentReplyActivities)
	}
}

func TestLatestAgentReplyActivityBaselinesKnownReadConversation(t *testing.T) {
	preferences := codexSharedPreferences{
		CodexChatActivityKeys:           map[string]string{"conversation-1": "legacy-key"},
		CodexLatestAgentReplyActivities: map[string]codexLatestAgentReplyActivity{},
	}
	request := codexLatestAgentReplyActivityRequest{
		ID:                     "conversation-1",
		ActivityKey:            "current-reply",
		OccurredAtMs:           2000,
		NativeUnreadStateKnown: true,
		NativeHasUnreadTurn:    false,
	}
	changed, err := applyCodexLatestAgentReplyActivityRequest(&preferences, request)
	if err != nil {
		t.Fatalf("apply known-read latest-agent-reply activity: %v", err)
	}
	if !changed {
		t.Fatal("known-read latest-agent-reply activity did not change preferences")
	}
	if preferences.CodexChatActivityKeys["conversation-1"] != "current-reply" {
		t.Fatalf("known-read conversation was not baselined: %+v", preferences.CodexChatActivityKeys)
	}
}

func TestLatestAgentReplyActivityDoesNotBaselineUnreadConversation(t *testing.T) {
	preferences := codexSharedPreferences{
		CodexChatActivityKeys:           map[string]string{"conversation-1": "previous-reply"},
		CodexLatestAgentReplyActivities: map[string]codexLatestAgentReplyActivity{},
	}
	request := codexLatestAgentReplyActivityRequest{
		ID:                     "conversation-1",
		ActivityKey:            "unread-reply",
		OccurredAtMs:           2000,
		NativeUnreadStateKnown: true,
		NativeHasUnreadTurn:    true,
	}
	changed, err := applyCodexLatestAgentReplyActivityRequest(&preferences, request)
	if err != nil {
		t.Fatalf("apply unread latest-agent-reply activity: %v", err)
	}
	if !changed {
		t.Fatal("unread latest-agent-reply activity did not change preferences")
	}
	if preferences.CodexChatActivityKeys["conversation-1"] != "previous-reply" {
		t.Fatalf("unread conversation was marked seen: %+v", preferences.CodexChatActivityKeys)
	}
}

func TestLatestAgentReplyActivityRejectsConflictingEqualTimestamp(t *testing.T) {
	preferences := codexSharedPreferences{
		CodexChatActivityKeys: map[string]string{},
		CodexLatestAgentReplyActivities: map[string]codexLatestAgentReplyActivity{
			"conversation-1": {ActivityKey: "reply-a", OccurredAtMs: 2000},
		},
	}
	_, err := applyCodexLatestAgentReplyActivityRequest(
		&preferences,
		codexLatestAgentReplyActivityRequest{
			ID: "conversation-1", ActivityKey: "reply-b", OccurredAtMs: 2000,
		},
	)
	if err == nil || !strings.Contains(err.Error(), "conflicting latest agent reply activities") {
		t.Fatalf("expected equal-timestamp conflict, got %v", err)
	}
}

func TestCodexPreferenceRequestScriptsIncludeLatestAgentReplyQueue(t *testing.T) {
	readScript := codexPreferenceReadScript()
	clearScript := codexPreferenceRequestsClearScript()
	if !strings.Contains(readScript, codexLatestAgentReplyActivityRequestsKey) {
		t.Fatal("preference read script is missing latest-agent-reply request queue")
	}
	if !strings.Contains(clearScript, codexLatestAgentReplyActivityRequestsKey) {
		t.Fatal("preference clear script is missing latest-agent-reply request queue")
	}
}

func TestApplyCodexPreferencePayloadsSerializesConcurrentWriters(t *testing.T) {
	codexHome := t.TempDir()
	results := make(chan error, 2)
	firstPayload := codexPreferencePayload{
		LatestAgentReplyActivityRequests: []codexLatestAgentReplyActivityRequest{
			{ID: "conversation-1", ActivityKey: "reply-1", OccurredAtMs: 1000},
		},
	}
	secondPayload := codexPreferencePayload{
		LatestAgentReplyActivityRequests: []codexLatestAgentReplyActivityRequest{
			{ID: "conversation-2", ActivityKey: "reply-2", OccurredAtMs: 2000},
		},
	}

	go applyCodexPreferencePayloadForTest(codexHome, firstPayload, results)
	go applyCodexPreferencePayloadForTest(codexHome, secondPayload, results)
	for resultIndex := 0; resultIndex < 2; resultIndex += 1 {
		if err := <-results; err != nil {
			t.Fatalf("concurrent preference write failed: %v", err)
		}
	}

	preferences, err := readCodexSharedPreferences(codexHome)
	if err != nil {
		t.Fatalf("read concurrent preferences: %v", err)
	}
	if len(preferences.CodexLatestAgentReplyActivities) != 2 {
		t.Fatalf("concurrent writes lost an activity: %+v", preferences.CodexLatestAgentReplyActivities)
	}
}

func applyCodexPreferencePayloadForTest(
	codexHome string,
	payload codexPreferencePayload,
	results chan<- error,
) {
	results <- applyCodexPreferencePayloads(codexHome, []codexPreferencePayload{payload})
}
