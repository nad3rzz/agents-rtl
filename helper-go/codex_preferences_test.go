package main

import (
	"encoding/json"
	"os"
	"path/filepath"
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
