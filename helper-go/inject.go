package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"path/filepath"
	"strings"
	"time"
)

type targetInjectionState struct {
	ResourceMonitorResetRequestObserved bool
	ResourceMonitorResetRequestID       string
}

func injectAll(
	port int,
	workspaceCWDs []string,
	codexCliPath string,
	resourceMonitor *codexResourceMonitor,
) error {
	targets, err := fetchTargets(port)
	if err != nil {
		return err
	}
	targets, err = targetsScopedToWorkspace(targets, workspaceCWDs)
	if err != nil {
		return err
	}

	if err := processCodexArchiveRequests(port, targets, workspaceCWDs, codexCliPath); err != nil {
		log.Printf("codex archive requests unavailable: %v", err)
	}

	if err := processCodexPreferenceRequests(port, targets); err != nil {
		log.Printf("codex shared preferences unavailable: %v", err)
	}

	codexHome, err := codexHomeDir()
	if err != nil {
		return err
	}
	preferences, err := readCodexSharedPreferences(codexHome)
	if err != nil {
		return err
	}

	conversations, err := readCodexConversations(workspaceCWDs)
	if err != nil {
		log.Printf("codex chat tabs unavailable: %v", err)
		conversations = nil
	}

	hasOpenAIWebviewTarget := false
	for _, target := range targets {
		if isOpenAIWebviewTarget(target) {
			hasOpenAIWebviewTarget = true
			break
		}
	}

	resourceMetrics := unavailableCodexResourceMetrics()
	if resourceMonitor != nil {
		if err := resourceMonitor.setSamplingEnabled(hasOpenAIWebviewTarget); err != nil {
			log.Printf("codex resource monitor state unavailable: %v", err)
		}
		resourceMetrics, err = resourceMonitor.collectMetrics()
		if err != nil {
			log.Printf("codex resource metrics unavailable: %v", err)
		}
	}
	resourceMonitorResetRequestWasObserved := false
	resourceMonitorResetRequestID := ""

	for _, target := range targets {
		if !isAgentTarget(target) {
			continue
		}

		targetResourceMetrics := unavailableCodexResourceMetrics()
		if isOpenAIWebviewTarget(target) {
			targetResourceMetrics = resourceMetrics
		}

		targetState, err := injectTarget(port, target, conversations, preferences, targetResourceMetrics)
		if err != nil {
			log.Printf("target %s failed: %v", target.ID, err)
			continue
		}
		if targetState.ResourceMonitorResetRequestObserved {
			if resourceMonitorResetRequestWasObserved &&
				resourceMonitorResetRequestID != targetState.ResourceMonitorResetRequestID {
				return fmt.Errorf("conflicting Codex resource monitor reset requests across target contexts")
			}
			resourceMonitorResetRequestWasObserved = true
			resourceMonitorResetRequestID = targetState.ResourceMonitorResetRequestID
		}
	}

	if resourceMonitor != nil && resourceMonitorResetRequestWasObserved {
		if err := resourceMonitor.observeResetRequestID(resourceMonitorResetRequestID); err != nil {
			log.Printf("codex resource monitor reset unavailable: %v", err)
		}
	}

	return nil
}

func fetchTargets(port int) ([]debuggerTarget, error) {
	client := &http.Client{Timeout: 3 * time.Second}
	response, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/json", port))
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected debugger status: %s", response.Status)
	}

	var targets []debuggerTarget
	if err := json.NewDecoder(response.Body).Decode(&targets); err != nil {
		return nil, err
	}

	return targets, nil
}

func targetsScopedToWorkspace(targets []debuggerTarget, workspaceCWDs []string) ([]debuggerTarget, error) {
	workbenchTargets := []debuggerTarget{}
	for _, target := range targets {
		if isWorkbenchTarget(target) {
			workbenchTargets = append(workbenchTargets, target)
		}
	}
	if len(workbenchTargets) <= 1 {
		return targets, nil
	}

	workspaceNames := workspaceNamesFromCWDs(workspaceCWDs)
	if len(workspaceNames) == 0 {
		return targetsScopedToNoWorkspaceWorkbench(targets, workbenchTargets)
	}

	matchedWorkbenchIDs := map[string]bool{}
	for _, target := range workbenchTargets {
		if workbenchTargetMatchesWorkspaceNames(target, workspaceNames) {
			matchedWorkbenchIDs[target.ID] = true
		}
	}
	if len(matchedWorkbenchIDs) == 0 {
		return nil, fmt.Errorf(
			"cannot scope DevTools targets to workspace names %q; available workbench titles: %q",
			strings.Join(workspaceNames, ", "),
			strings.Join(workbenchTargetTitles(workbenchTargets), " | "),
		)
	}

	return targetsScopedToWorkbenchIDs(targets, matchedWorkbenchIDs), nil
}

func targetsScopedToNoWorkspaceWorkbench(targets []debuggerTarget, workbenchTargets []debuggerTarget) ([]debuggerTarget, error) {
	matchedWorkbenchIDs := map[string]bool{}
	for _, target := range workbenchTargets {
		if workbenchTargetHasNoWorkspaceTitle(target) {
			matchedWorkbenchIDs[target.ID] = true
		}
	}
	if len(matchedWorkbenchIDs) == 0 {
		return nil, fmt.Errorf(
			"cannot scope DevTools targets to no-workspace window; available workbench titles: %q",
			strings.Join(workbenchTargetTitles(workbenchTargets), " | "),
		)
	}

	return targetsScopedToWorkbenchIDs(targets, matchedWorkbenchIDs), nil
}

func targetsScopedToWorkbenchIDs(targets []debuggerTarget, matchedWorkbenchIDs map[string]bool) []debuggerTarget {
	scopedTargets := []debuggerTarget{}
	for _, target := range targets {
		if isWorkbenchTarget(target) {
			if matchedWorkbenchIDs[target.ID] {
				scopedTargets = append(scopedTargets, target)
			}
			continue
		}
		if target.ParentID != "" {
			if matchedWorkbenchIDs[target.ParentID] {
				scopedTargets = append(scopedTargets, target)
			}
			continue
		}
		if len(matchedWorkbenchIDs) == 1 {
			scopedTargets = append(scopedTargets, target)
		}
	}
	return scopedTargets
}

func workspaceNamesFromCWDs(workspaceCWDs []string) []string {
	normalizedCWDs := normalizedWorkspaceCWDs(workspaceCWDs)
	workspaceNames := []string{}
	seenWorkspaceNames := map[string]bool{}
	for _, cwd := range normalizedCWDs {
		workspaceName := strings.TrimSpace(filepath.Base(cwd))
		if workspaceName == "" || workspaceName == "." || seenWorkspaceNames[workspaceName] {
			continue
		}
		seenWorkspaceNames[workspaceName] = true
		workspaceNames = append(workspaceNames, workspaceName)
	}
	return workspaceNames
}

func workbenchTargetMatchesWorkspaceNames(target debuggerTarget, workspaceNames []string) bool {
	for _, workspaceName := range workspaceNames {
		if workbenchTitleMatchesWorkspaceName(target.Title, workspaceName) {
			return true
		}
	}
	return false
}

func workbenchTitleMatchesWorkspaceName(title string, workspaceName string) bool {
	normalizedTitle := strings.ToLower(strings.TrimSpace(title))
	normalizedWorkspaceName := strings.ToLower(strings.TrimSpace(workspaceName))
	if normalizedTitle == "" || normalizedWorkspaceName == "" {
		return false
	}
	return normalizedTitle == normalizedWorkspaceName ||
		strings.HasPrefix(normalizedTitle, normalizedWorkspaceName+" - ") ||
		strings.Contains(normalizedTitle, " - "+normalizedWorkspaceName+" - ")
}

func workbenchTargetHasNoWorkspaceTitle(target debuggerTarget) bool {
	normalizedTitle := strings.ToLower(strings.TrimSpace(target.Title))
	return normalizedTitle == "antigravity" ||
		normalizedTitle == "visual studio code" ||
		normalizedTitle == "code" ||
		normalizedTitle == "vscodium" ||
		normalizedTitle == "cursor" ||
		normalizedTitle == "windsurf"
}

func workbenchTargetTitles(targets []debuggerTarget) []string {
	titles := []string{}
	for _, target := range targets {
		title := strings.TrimSpace(target.Title)
		if title == "" {
			title = target.ID
		}
		titles = append(titles, title)
	}
	return titles
}

func isAgentTarget(target debuggerTarget) bool {
	return target.WebSocketDebuggerURL != "" &&
		(isOpenAIWebviewTarget(target) || isGeminiWebviewTarget(target) || isWorkbenchTarget(target))
}

func isOpenAIWebviewTarget(target debuggerTarget) bool {
	return (target.Type == "iframe" || target.Type == "page") &&
		strings.HasPrefix(target.URL, "vscode-webview://") &&
		strings.Contains(target.URL, chatgptWebviewURLMarker)
}

func isGeminiWebviewTarget(target debuggerTarget) bool {
	return (target.Type == "iframe" || target.Type == "page") &&
		strings.HasPrefix(target.URL, "vscode-webview://") &&
		strings.Contains(target.URL, geminiWebviewURLMarker)
}

func isWorkbenchTarget(target debuggerTarget) bool {
	return target.Type == "page" &&
		strings.HasPrefix(target.URL, "vscode-file://") &&
		strings.Contains(target.URL, workbenchURLMarker)
}

func injectTarget(
	port int,
	target debuggerTarget,
	conversations []codexConversation,
	preferences codexSharedPreferences,
	resourceMetrics codexResourceMetrics,
) (targetInjectionState, error) {
	parsedURL, err := url.Parse(target.WebSocketDebuggerURL)
	if err != nil {
		return targetInjectionState{}, err
	}

	client, err := connectDevtools(port, parsedURL.RequestURI())
	if err != nil {
		return targetInjectionState{}, err
	}
	defer client.close()

	if _, err := client.command("Runtime.enable", map[string]any{}); err != nil {
		return targetInjectionState{}, err
	}

	time.Sleep(250 * time.Millisecond)

	contextIDs, err := client.readyContextIDs()
	if err != nil {
		return targetInjectionState{}, err
	}

	script, err := injectionScript(conversations, preferences, resourceMetrics)
	if err != nil {
		return targetInjectionState{}, err
	}

	targetState := targetInjectionState{}
	for _, contextID := range contextIDs {
		value, err := client.evaluate(contextID, script)
		if err != nil {
			return targetInjectionState{}, fmt.Errorf("context %d injection failed: %w", contextID, err)
		}
		if !isOpenAIWebviewTarget(target) {
			continue
		}
		resourceMonitorResetRequestID, err := resourceMonitorResetRequestIDFromInjectionValue(value)
		if err != nil {
			return targetInjectionState{}, fmt.Errorf("context %d resource monitor state failed: %w", contextID, err)
		}
		if targetState.ResourceMonitorResetRequestObserved &&
			targetState.ResourceMonitorResetRequestID != resourceMonitorResetRequestID {
			return targetInjectionState{}, fmt.Errorf("context %d returned a conflicting resource monitor reset request", contextID)
		}
		targetState.ResourceMonitorResetRequestObserved = true
		targetState.ResourceMonitorResetRequestID = resourceMonitorResetRequestID
	}

	return targetState, nil
}

func resourceMonitorResetRequestIDFromInjectionValue(value any) (string, error) {
	payload, ok := value.(map[string]any)
	if !ok {
		return "", fmt.Errorf("injection result must be an object, got %T", value)
	}
	resourceMonitorResetRequestID, ok := payload["resourceMonitorResetRequestId"].(string)
	if !ok {
		return "", fmt.Errorf("injection result is missing string resourceMonitorResetRequestId")
	}
	return resourceMonitorResetRequestID, nil
}

func injectionScript(
	conversations []codexConversation,
	preferences codexSharedPreferences,
	resourceMetrics codexResourceMetrics,
) (string, error) {
	conversationsJSON, err := json.Marshal(conversations)
	if err != nil {
		return "", err
	}
	preferencesJSON, err := json.Marshal(preferences)
	if err != nil {
		return "", err
	}
	resourceMetricsJSON, err := json.Marshal(resourceMetrics)
	if err != nil {
		return "", err
	}

	return "window.__agentsRtlCodexConversations = " + string(conversationsJSON) + ";\n" +
		"window.__agentsRtlCodexPreferences = " + string(preferencesJSON) + ";\n" +
		"window.__agentsRtlCodexResourceMetrics = " + string(resourceMetricsJSON) + ";\n" +
		rtlScript + "\n({ resourceMonitorResetRequestId: String(window.__agentsRtl?.codexResourceMonitorResetRequestId || '') });", nil
}
