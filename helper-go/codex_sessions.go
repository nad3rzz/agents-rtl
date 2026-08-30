package main

import (
	"bufio"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func readCodexConversations(workspaceCWDs []string) ([]codexConversation, error) {
	if len(workspaceCWDs) == 0 {
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

	titlesByID, err := readSessionIndexTitles(codexHome)
	if err != nil {
		return nil, err
	}

	database, err := sql.Open("sqlite", fmt.Sprintf("file:%s?mode=ro&_pragma=busy_timeout(1000)", filepath.ToSlash(stateDatabasePath)))
	if err != nil {
		return nil, err
	}
	defer database.Close()

	workspaceCWDValues := normalizedWorkspaceCWDs(workspaceCWDs)
	if len(workspaceCWDValues) == 0 {
		return nil, nil
	}

	placeholders := sqlitePlaceholders(len(workspaceCWDValues))
	queryArgs := stringSliceToAny(workspaceCWDValues)
	queryArgs = append(queryArgs, maxCodexChatTabs)
	query := fmt.Sprintf(`
select id, title, rollout_path
from threads
where archived = 0 and source = 'vscode' and cwd in (%s)
order by updated_at desc
limit ?
`, placeholders)

	rows, err := database.Query(query, queryArgs...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	conversations := []codexConversation{}
	for rows.Next() {
		var conversation codexConversation
		if err := rows.Scan(&conversation.ID, &conversation.Title, &conversation.Path); err != nil {
			return nil, err
		}

		if indexedTitle := titlesByID[conversation.ID]; indexedTitle != "" {
			conversation.Title = indexedTitle
		}
		conversation.Title = compactDisplayText(conversation.Title)
		if conversation.ID == "" || conversation.Title == "" {
			continue
		}
		conversations = append(conversations, conversation)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	return conversations, nil
}

func codexHomeDir() (string, error) {
	if codexHome := strings.TrimSpace(os.Getenv("CODEX_HOME")); codexHome != "" {
		return codexHome, nil
	}

	homeDir, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}

	return filepath.Join(homeDir, ".codex"), nil
}

func readSessionIndexTitles(codexHome string) (map[string]string, error) {
	titlesByID := make(map[string]string)
	sessionIndexPath := filepath.Join(codexHome, "session_index.jsonl")
	file, err := os.Open(sessionIndexPath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return titlesByID, nil
		}
		return nil, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		var row sessionIndexRow
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			return nil, err
		}
		if row.ID == "" || row.ThreadName == "" {
			continue
		}
		titlesByID[row.ID] = compactDisplayText(row.ThreadName)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return titlesByID, nil
}

func compactDisplayText(value string) string {
	return strings.Join(strings.Fields(value), " ")
}

func normalizedWorkspaceCWDs(workspaceCWDs []string) []string {
	normalizedValues := []string{}
	seenWorkspaceCWDs := make(map[string]bool)
	for _, workspaceCWD := range workspaceCWDs {
		trimmedWorkspaceCWD := strings.TrimSpace(workspaceCWD)
		if trimmedWorkspaceCWD == "" || seenWorkspaceCWDs[trimmedWorkspaceCWD] {
			continue
		}

		seenWorkspaceCWDs[trimmedWorkspaceCWD] = true
		normalizedValues = append(normalizedValues, trimmedWorkspaceCWD)
	}

	return normalizedValues
}

func sqlitePlaceholders(count int) string {
	placeholders := make([]string, 0, count)
	for index := 0; index < count; index += 1 {
		placeholders = append(placeholders, "?")
	}
	return strings.Join(placeholders, ",")
}

func stringSliceToAny(values []string) []any {
	convertedValues := make([]any, 0, len(values))
	for _, value := range values {
		convertedValues = append(convertedValues, value)
	}
	return convertedValues
}
