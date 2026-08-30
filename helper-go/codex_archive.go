package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

func processCodexArchiveRequests(port int, targets []debuggerTarget, workspaceCWDs []string, codexCliPath string) error {
	if len(normalizedWorkspaceCWDs(workspaceCWDs)) == 0 {
		return nil
	}

	requestsByID := make(map[string]codexArchiveRequest)
	sourceTargets := []debuggerTarget{}
	for _, target := range targets {
		if !isOpenAIWebviewTarget(target) {
			continue
		}

		requests, err := readCodexArchiveRequestsFromTarget(port, target)
		if err != nil {
			log.Printf("target %s codex archive request read failed: %v", target.ID, err)
			continue
		}
		if len(requests) == 0 {
			continue
		}

		sourceTargets = append(sourceTargets, target)
		for _, request := range requests {
			if request.ID == "" {
				continue
			}
			requestsByID[request.ID] = request
		}
	}
	if len(requestsByID) == 0 {
		return nil
	}

	requests := make([]codexArchiveRequest, 0, len(requestsByID))
	for _, request := range requestsByID {
		requests = append(requests, request)
	}

	processedIDs, err := archiveCodexConversations(workspaceCWDs, requests, codexCliPath)
	if err != nil {
		return err
	}
	if len(processedIDs) == 0 {
		return nil
	}

	for _, target := range sourceTargets {
		if err := clearCodexArchiveRequestsFromTarget(port, target, processedIDs); err != nil {
			log.Printf("target %s codex archive request clear failed: %v", target.ID, err)
		}
	}

	return nil
}

func readCodexArchiveRequestsFromTarget(port int, target debuggerTarget) ([]codexArchiveRequest, error) {
	contextValues, err := evaluateInReadyTargetContexts(port, target, codexArchiveRequestsReadScript())
	if err != nil {
		return nil, err
	}

	requestsByID := make(map[string]codexArchiveRequest)
	for _, value := range contextValues {
		requests, err := decodeCodexArchiveRequests(value)
		if err != nil {
			return nil, err
		}
		for _, request := range requests {
			if request.ID == "" {
				continue
			}
			requestsByID[request.ID] = request
		}
	}

	requests := make([]codexArchiveRequest, 0, len(requestsByID))
	for _, request := range requestsByID {
		requests = append(requests, request)
	}
	return requests, nil
}

func clearCodexArchiveRequestsFromTarget(port int, target debuggerTarget, processedIDs []string) error {
	script, err := codexArchiveRequestsClearScript(processedIDs)
	if err != nil {
		return err
	}

	_, err = evaluateInReadyTargetContexts(port, target, script)
	return err
}

func codexArchiveRequestsReadScript() string {
	keyJSON, err := json.Marshal(codexArchiveRequestsKey)
	if err != nil {
		panic(err)
	}

	return fmt.Sprintf(`(() => {
  const key = %s;
  const rawValue = localStorage.getItem(key);
  if (rawValue === null) return [];
  const parsedValue = JSON.parse(rawValue);
  if (!Array.isArray(parsedValue)) throw new Error("Invalid Codex archive requests payload");
  return parsedValue
    .map((request) => ({
      id: String(request?.id || "").trim(),
      title: String(request?.title || "").trim(),
      requestedAt: Number(request?.requestedAt) || 0,
    }))
    .filter((request) => request.id);
})()`, string(keyJSON))
}

func codexArchiveRequestsClearScript(processedIDs []string) (string, error) {
	keyJSON, err := json.Marshal(codexArchiveRequestsKey)
	if err != nil {
		return "", err
	}
	processedKeyJSON, err := json.Marshal(codexProcessedArchivesKey)
	if err != nil {
		return "", err
	}
	processedIDsJSON, err := json.Marshal(processedIDs)
	if err != nil {
		return "", err
	}

	return fmt.Sprintf(`(() => {
  const key = %s;
  const processedKey = %s;
  const processedIds = new Set(%s.map((id) => String(id || "").trim()).filter(Boolean));
  const rawValue = localStorage.getItem(key);
  if (rawValue === null) return 0;
  const parsedValue = JSON.parse(rawValue);
  if (!Array.isArray(parsedValue)) throw new Error("Invalid Codex archive requests payload");
  const nextValue = parsedValue.filter((request) => !processedIds.has(String(request?.id || "").trim()));
  if (nextValue.length === 0) localStorage.removeItem(key);
  else localStorage.setItem(key, JSON.stringify(nextValue));
  const rawProcessedValue = localStorage.getItem(processedKey);
  const parsedProcessedValue = rawProcessedValue === null ? [] : JSON.parse(rawProcessedValue);
  if (!Array.isArray(parsedProcessedValue)) throw new Error("Invalid Codex processed archive ids payload");
  const mergedProcessedIds = [...new Set([...parsedProcessedValue.map((id) => String(id || "").trim()), ...processedIds].filter(Boolean))];
  if (mergedProcessedIds.length === 0) localStorage.removeItem(processedKey);
  else localStorage.setItem(processedKey, JSON.stringify(mergedProcessedIds));
  return parsedValue.length - nextValue.length;
})()`, string(keyJSON), string(processedKeyJSON), string(processedIDsJSON)), nil
}

func decodeCodexArchiveRequests(value any) ([]codexArchiveRequest, error) {
	encodedValue, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}

	requests := []codexArchiveRequest{}
	if err := json.Unmarshal(encodedValue, &requests); err != nil {
		return nil, err
	}

	for index, request := range requests {
		request.ID = strings.TrimSpace(request.ID)
		request.Title = compactDisplayText(request.Title)
		requests[index] = request
	}

	return requests, nil
}

func archiveCodexConversations(workspaceCWDs []string, requests []codexArchiveRequest, codexCliPath string) ([]string, error) {
	workspaceCWDValues := normalizedWorkspaceCWDs(workspaceCWDs)
	if len(workspaceCWDValues) == 0 || len(requests) == 0 {
		return nil, nil
	}

	codexHome, err := codexHomeDir()
	if err != nil {
		return nil, err
	}

	stateDatabasePath := filepath.Join(codexHome, "state_5.sqlite")
	if _, err := os.Stat(stateDatabasePath); err != nil {
		return nil, fmt.Errorf("cannot read Codex state database: %w", err)
	}

	database, err := sql.Open("sqlite", fmt.Sprintf("file:%s?mode=ro&_pragma=busy_timeout(1000)", filepath.ToSlash(stateDatabasePath)))
	if err != nil {
		return nil, err
	}
	defer database.Close()

	processedIDs := []string{}
	seenRequestIDs := make(map[string]bool)
	codexExecutablePath := ""
	for _, request := range requests {
		request.ID = strings.TrimSpace(request.ID)
		if request.ID == "" || seenRequestIDs[request.ID] {
			continue
		}
		seenRequestIDs[request.ID] = true

		archiveRow, err := readCodexArchiveRow(database, request.ID)
		if err != nil {
			return nil, err
		}

		if archiveRow.Archived == 0 {
			if codexExecutablePath == "" {
				codexExecutablePath, err = findCodexExecutablePath(codexHome, codexCliPath)
				if err != nil {
					return nil, err
				}
			}
			if err := runCodexArchiveCommand(codexExecutablePath, codexHome, request.ID); err != nil {
				return nil, err
			}
			verifiedArchiveRow, err := readCodexArchiveRow(database, request.ID)
			if err != nil {
				return nil, err
			}
			if verifiedArchiveRow.Archived == 0 {
				return nil, fmt.Errorf("Codex archive command did not archive thread id %q", request.ID)
			}
			archiveRow = verifiedArchiveRow
		}

		if err := broadcastCodexThreadArchived(request.ID, archiveRow.CWD); err != nil {
			return nil, err
		}

		processedIDs = append(processedIDs, request.ID)
	}

	return processedIDs, nil
}

func readCodexArchiveRow(database *sql.DB, conversationID string) (codexArchiveRow, error) {
	lookupQuery := `
select archived, cwd
from threads
where id = ? and source = 'vscode'
`
	var archiveRow codexArchiveRow
	if err := database.QueryRow(lookupQuery, conversationID).Scan(&archiveRow.Archived, &archiveRow.CWD); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return archiveRow, fmt.Errorf("archive request has no matching Codex thread id %q", conversationID)
		}
		return archiveRow, err
	}
	archiveRow.CWD = strings.TrimSpace(archiveRow.CWD)
	if archiveRow.CWD == "" {
		return archiveRow, fmt.Errorf("archive request has empty cwd for Codex thread id %q", conversationID)
	}
	return archiveRow, nil
}

func runCodexArchiveCommand(codexExecutablePath string, codexHome string, conversationID string) error {
	ctx, cancel := context.WithTimeout(context.Background(), codexArchiveCommandTimeout)
	defer cancel()

	command := exec.CommandContext(ctx, codexExecutablePath, "archive", conversationID)
	command.Env = append(os.Environ(), "CODEX_HOME="+codexHome)
	output, err := command.CombinedOutput()
	if ctx.Err() != nil {
		return fmt.Errorf("Codex archive command timed out for thread id %q: %w", conversationID, ctx.Err())
	}
	if err != nil {
		return fmt.Errorf("Codex archive command failed for thread id %q: %w: %s", conversationID, err, compactDisplayText(string(output)))
	}
	return nil
}

func findCodexExecutablePath(codexHome string, codexCliPath string) (string, error) {
	configuredPath := strings.TrimSpace(codexCliPath)
	if configuredPath == "" {
		configuredPath = strings.TrimSpace(os.Getenv("AGENTS_RTL_CODEX_CLI"))
	}
	if configuredPath == "" {
		return "", errors.New("Codex CLI path was not provided")
	}
	if !codexExecutableIsUsable(configuredPath) {
		return "", fmt.Errorf("configured Codex executable is not usable: %s", configuredPath)
	}
	if !codexExecutableSupportsArchive(configuredPath, codexHome) {
		return "", fmt.Errorf("configured Codex executable does not support archive: %s", configuredPath)
	}
	return configuredPath, nil
}

func codexExecutableIsUsable(pathValue string) bool {
	fileInfo, err := os.Stat(pathValue)
	if err != nil || fileInfo.IsDir() {
		return false
	}
	if runtime.GOOS == "windows" {
		return true
	}
	return fileInfo.Mode()&0111 != 0
}

func codexExecutableSupportsArchive(pathValue string, codexHome string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), codexArchiveHelpTimeout)
	defer cancel()

	command := exec.CommandContext(ctx, pathValue, "archive", "--help")
	command.Env = append(os.Environ(), "CODEX_HOME="+codexHome)
	output, err := command.CombinedOutput()
	if ctx.Err() != nil || err != nil {
		return false
	}
	return strings.Contains(string(output), "Usage: codex archive")
}
