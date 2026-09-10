package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"strings"
)

func processCodexPreferenceRequests(port int, targets []debuggerTarget) error {
	codexHome, err := codexHomeDir()
	if err != nil {
		return err
	}

	payloads := []codexPreferencePayload{}
	sourceTargets := []debuggerTarget{}
	hasPreferenceRequestQueues := false
	for _, target := range targets {
		if !isOpenAIWebviewTarget(target) {
			continue
		}

		targetPayloads, err := readCodexPreferencePayloadsFromTarget(port, target)
		if err != nil {
			log.Printf("target %s codex preference read failed: %v", target.ID, err)
			continue
		}
		if len(targetPayloads) == 0 {
			continue
		}

		sourceTargets = append(sourceTargets, target)
		for _, payload := range targetPayloads {
			if len(payload.TabOrderRequests) > 0 ||
				len(payload.ActivityKeyRequests) > 0 ||
				len(payload.LatestAgentReplyActivityRequests) > 0 {
				hasPreferenceRequestQueues = true
			}
			payloads = append(payloads, payload)
		}
	}
	if len(payloads) == 0 {
		return nil
	}

	if err := applyCodexPreferencePayloads(codexHome, payloads); err != nil {
		return err
	}
	if !hasPreferenceRequestQueues {
		return nil
	}

	for _, target := range sourceTargets {
		if err := clearCodexPreferenceRequestsFromTarget(port, target); err != nil {
			log.Printf("target %s codex preference request clear failed: %v", target.ID, err)
		}
	}
	return nil
}

func readCodexPreferencePayloadsFromTarget(port int, target debuggerTarget) ([]codexPreferencePayload, error) {
	contextValues, err := evaluateInReadyTargetContexts(port, target, codexPreferenceReadScript())
	if err != nil {
		return nil, err
	}

	payloads := []codexPreferencePayload{}
	for _, value := range contextValues {
		payload, err := decodeCodexPreferencePayload(value)
		if err != nil {
			return nil, err
		}
		if codexPreferencePayloadIsEmpty(payload) {
			continue
		}
		payloads = append(payloads, payload)
	}
	return payloads, nil
}

func clearCodexPreferenceRequestsFromTarget(port int, target debuggerTarget) error {
	_, err := evaluateInReadyTargetContexts(port, target, codexPreferenceRequestsClearScript())
	return err
}

func codexPreferenceReadScript() string {
	tabOrderRequestsKeyJSON := mustMarshalJSONString(codexTabOrderRequestsKey)
	activityRequestsKeyJSON := mustMarshalJSONString(codexActivityRequestsKey)
	latestAgentReplyActivityRequestsKeyJSON := mustMarshalJSONString(codexLatestAgentReplyActivityRequestsKey)
	return fmt.Sprintf(`(() => {
  const parseJson = (key, fallback) => {
    const rawValue = localStorage.getItem(key);
    if (rawValue === null) return fallback;
    return JSON.parse(rawValue);
  };
  return {
    tabOrderRequests: parseJson(%s, []),
    activityKeyRequests: parseJson(%s, []),
    latestAgentReplyActivityRequests: parseJson(%s, []),
  };
})()`, tabOrderRequestsKeyJSON, activityRequestsKeyJSON, latestAgentReplyActivityRequestsKeyJSON)
}

func codexPreferenceRequestsClearScript() string {
	tabOrderRequestsKeyJSON := mustMarshalJSONString(codexTabOrderRequestsKey)
	activityRequestsKeyJSON := mustMarshalJSONString(codexActivityRequestsKey)
	latestAgentReplyActivityRequestsKeyJSON := mustMarshalJSONString(codexLatestAgentReplyActivityRequestsKey)
	return fmt.Sprintf(`(() => {
  localStorage.removeItem(%s);
  localStorage.removeItem(%s);
  localStorage.removeItem(%s);
  return true;
})()`, tabOrderRequestsKeyJSON, activityRequestsKeyJSON, latestAgentReplyActivityRequestsKeyJSON)
}

func decodeCodexPreferencePayload(value any) (codexPreferencePayload, error) {
	encodedValue, err := json.Marshal(value)
	if err != nil {
		return codexPreferencePayload{}, err
	}

	payload := codexPreferencePayload{}
	if err := json.Unmarshal(encodedValue, &payload); err != nil {
		return codexPreferencePayload{}, err
	}

	for index, request := range payload.TabOrderRequests {
		request.IDs = sanitizeCodexConversationIDList(request.IDs)
		payload.TabOrderRequests[index] = request
	}
	filteredTabOrderRequests := []codexTabOrderRequest{}
	for _, request := range payload.TabOrderRequests {
		if len(request.IDs) == 0 {
			continue
		}
		filteredTabOrderRequests = append(filteredTabOrderRequests, request)
	}
	payload.TabOrderRequests = filteredTabOrderRequests
	for index, request := range payload.ActivityKeyRequests {
		request.ID = strings.TrimSpace(request.ID)
		request.ActivityKey = compactDisplayText(request.ActivityKey)
		payload.ActivityKeyRequests[index] = request
	}
	filteredActivityKeyRequests := []codexActivityKeyRequest{}
	for _, request := range payload.ActivityKeyRequests {
		if request.ID == "" || request.ActivityKey == "" {
			continue
		}
		filteredActivityKeyRequests = append(filteredActivityKeyRequests, request)
	}
	payload.ActivityKeyRequests = filteredActivityKeyRequests
	for index, request := range payload.LatestAgentReplyActivityRequests {
		request.ID = strings.TrimSpace(request.ID)
		request.ActivityKey = compactDisplayText(request.ActivityKey)
		if request.ID == "" {
			return codexPreferencePayload{}, fmt.Errorf("latest agent reply activity request %d is missing id", index)
		}
		if request.ActivityKey == "" {
			return codexPreferencePayload{}, fmt.Errorf("latest agent reply activity request %d is missing activityKey", index)
		}
		if request.OccurredAtMs <= 0 || math.IsNaN(request.OccurredAtMs) || math.IsInf(request.OccurredAtMs, 0) {
			return codexPreferencePayload{}, fmt.Errorf("latest agent reply activity request %d has invalid occurredAtMs", index)
		}
		payload.LatestAgentReplyActivityRequests[index] = request
	}
	return payload, nil
}

func codexPreferencePayloadIsEmpty(payload codexPreferencePayload) bool {
	return len(payload.TabOrderRequests) == 0 &&
		len(payload.ActivityKeyRequests) == 0 &&
		len(payload.LatestAgentReplyActivityRequests) == 0
}

func applyCodexPreferencePayloads(codexHome string, payloads []codexPreferencePayload) error {
	if err := os.MkdirAll(codexHome, 0700); err != nil {
		return err
	}
	lockFile, err := acquireCodexPreferencesFileLock(codexPreferencesFileLockPath(codexHome))
	if err != nil {
		return err
	}
	applyErr := applyCodexPreferencePayloadsWhileLocked(codexHome, payloads)
	releaseErr := releaseCodexPreferencesFileLock(lockFile)
	if applyErr != nil {
		if releaseErr != nil {
			return fmt.Errorf("apply Codex preferences: %w; release preferences lock: %v", applyErr, releaseErr)
		}
		return applyErr
	}
	return releaseErr
}

func applyCodexPreferencePayloadsWhileLocked(codexHome string, payloads []codexPreferencePayload) error {
	preferences, err := readCodexSharedPreferences(codexHome)
	if err != nil {
		return err
	}
	if preferences.CodexChatActivityKeys == nil {
		preferences.CodexChatActivityKeys = map[string]string{}
	}
	if preferences.CodexLatestAgentReplyActivities == nil {
		preferences.CodexLatestAgentReplyActivities = map[string]codexLatestAgentReplyActivity{}
	}

	changed := false
	for _, payload := range payloads {
		for _, request := range payload.TabOrderRequests {
			if strings.Join(preferences.CodexChatOrder, "|") == strings.Join(request.IDs, "|") {
				continue
			}
			preferences.CodexChatOrder = request.IDs
			changed = true
		}
		for _, request := range payload.LatestAgentReplyActivityRequests {
			requestChangedPreferences, err := applyCodexLatestAgentReplyActivityRequest(&preferences, request)
			if err != nil {
				return err
			}
			changed = requestChangedPreferences || changed
		}
		for _, request := range payload.ActivityKeyRequests {
			if preferences.CodexChatActivityKeys[request.ID] == request.ActivityKey {
				continue
			}
			preferences.CodexChatActivityKeys[request.ID] = request.ActivityKey
			changed = true
		}
	}

	if !changed {
		return nil
	}
	return writeCodexSharedPreferences(codexHome, preferences)
}

func codexPreferencesFileLockPath(codexHome string) string {
	return filepath.Join(codexHome, ".agents-rtl-preferences.lock")
}

func applyCodexLatestAgentReplyActivityRequest(
	preferences *codexSharedPreferences,
	request codexLatestAgentReplyActivityRequest,
) (bool, error) {
	currentActivity, currentActivityExists := preferences.CodexLatestAgentReplyActivities[request.ID]
	if currentActivityExists && request.OccurredAtMs < currentActivity.OccurredAtMs {
		return false, nil
	}
	if currentActivityExists && request.OccurredAtMs == currentActivity.OccurredAtMs {
		if request.ActivityKey != currentActivity.ActivityKey {
			return false, fmt.Errorf(
				"conflicting latest agent reply activities for conversation %s at %.0f",
				request.ID,
				request.OccurredAtMs,
			)
		}
		return false, nil
	}

	preferences.CodexLatestAgentReplyActivities[request.ID] = codexLatestAgentReplyActivity{
		ActivityKey:  request.ActivityKey,
		OccurredAtMs: request.OccurredAtMs,
	}
	changed := true
	if !currentActivityExists && request.NativeUnreadStateKnown && !request.NativeHasUnreadTurn &&
		preferences.CodexChatActivityKeys[request.ID] != request.ActivityKey {
		preferences.CodexChatActivityKeys[request.ID] = request.ActivityKey
		changed = true
	}
	return changed, nil
}

func codexSharedPreferencesPath(codexHome string) string {
	return filepath.Join(codexHome, codexPreferencesFileName)
}

func readCodexSharedPreferences(codexHome string) (codexSharedPreferences, error) {
	preferencesPath := codexSharedPreferencesPath(codexHome)
	fileContent, err := os.ReadFile(preferencesPath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return codexSharedPreferences{}, nil
		}
		return codexSharedPreferences{}, err
	}
	if len(bytes.TrimSpace(fileContent)) == 0 {
		return codexSharedPreferences{}, fmt.Errorf("Codex shared preferences file is empty: %s", preferencesPath)
	}

	preferences := codexSharedPreferences{}
	if err := json.Unmarshal(fileContent, &preferences); err != nil {
		return codexSharedPreferences{}, fmt.Errorf("invalid Codex shared preferences file %s: %w", preferencesPath, err)
	}
	preferences.CodexChatOrder = sanitizeCodexConversationIDList(preferences.CodexChatOrder)
	preferences.CodexChatActivityKeys = sanitizeCodexActivityKeyMap(preferences.CodexChatActivityKeys)
	preferences.CodexLatestAgentReplyActivities, err = sanitizeCodexLatestAgentReplyActivityMap(
		preferences.CodexLatestAgentReplyActivities,
	)
	if err != nil {
		return codexSharedPreferences{}, fmt.Errorf("invalid latest agent reply activities in %s: %w", preferencesPath, err)
	}
	return preferences, nil
}

func writeCodexSharedPreferences(codexHome string, preferences codexSharedPreferences) error {
	preferences.CodexChatOrder = sanitizeCodexConversationIDList(preferences.CodexChatOrder)
	preferences.CodexChatActivityKeys = sanitizeCodexActivityKeyMap(preferences.CodexChatActivityKeys)
	latestAgentReplyActivities, err := sanitizeCodexLatestAgentReplyActivityMap(
		preferences.CodexLatestAgentReplyActivities,
	)
	if err != nil {
		return err
	}
	preferences.CodexLatestAgentReplyActivities = latestAgentReplyActivities
	preferencesPath := codexSharedPreferencesPath(codexHome)
	if err := os.MkdirAll(filepath.Dir(preferencesPath), 0700); err != nil {
		return err
	}

	fileContent, err := json.MarshalIndent(preferences, "", "  ")
	if err != nil {
		return err
	}
	fileContent = append(fileContent, '\n')
	temporaryFile, err := os.CreateTemp(filepath.Dir(preferencesPath), "."+filepath.Base(preferencesPath)+".*.tmp")
	if err != nil {
		return err
	}
	temporaryPath := temporaryFile.Name()
	defer os.Remove(temporaryPath)
	defer temporaryFile.Close()
	if err := temporaryFile.Chmod(0600); err != nil {
		return err
	}
	if _, err := temporaryFile.Write(fileContent); err != nil {
		return err
	}
	if err := temporaryFile.Sync(); err != nil {
		return err
	}
	if err := temporaryFile.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryPath, preferencesPath)
}

func sanitizeCodexActivityKeyMap(activityKeyMap map[string]string) map[string]string {
	if len(activityKeyMap) == 0 {
		return map[string]string{}
	}

	sanitizedValues := map[string]string{}
	for conversationID, activityKey := range activityKeyMap {
		conversationID = strings.TrimSpace(conversationID)
		activityKey = compactDisplayText(activityKey)
		if conversationID == "" || activityKey == "" {
			continue
		}
		sanitizedValues[conversationID] = activityKey
	}
	return sanitizedValues
}

func sanitizeCodexLatestAgentReplyActivityMap(
	activityMap map[string]codexLatestAgentReplyActivity,
) (map[string]codexLatestAgentReplyActivity, error) {
	if len(activityMap) == 0 {
		return map[string]codexLatestAgentReplyActivity{}, nil
	}

	sanitizedValues := map[string]codexLatestAgentReplyActivity{}
	for conversationID, activity := range activityMap {
		conversationID = strings.TrimSpace(conversationID)
		activity.ActivityKey = compactDisplayText(activity.ActivityKey)
		if conversationID == "" {
			return nil, errors.New("latest agent reply activity contains an empty conversation id")
		}
		if activity.ActivityKey == "" {
			return nil, fmt.Errorf("latest agent reply activity %s has an empty activity key", conversationID)
		}
		if activity.OccurredAtMs <= 0 || math.IsNaN(activity.OccurredAtMs) || math.IsInf(activity.OccurredAtMs, 0) {
			return nil, fmt.Errorf("latest agent reply activity %s has invalid occurredAtMs", conversationID)
		}
		sanitizedValues[conversationID] = activity
	}
	return sanitizedValues, nil
}

func sanitizeCodexConversationIDList(conversationIDs []string) []string {
	sanitizedValues := []string{}
	seenConversationIDs := map[string]bool{}
	for _, conversationID := range conversationIDs {
		conversationID = strings.TrimSpace(conversationID)
		if conversationID == "" || seenConversationIDs[conversationID] {
			continue
		}
		seenConversationIDs[conversationID] = true
		sanitizedValues = append(sanitizedValues, conversationID)
	}
	return sanitizedValues
}

func mustMarshalJSONString(value string) string {
	encodedValue, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return string(encodedValue)
}
