package main

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAppendAccountSwitcherAuditEventWritesPrivateJSONLine(t *testing.T) {
	stateDirectory := filepath.Join(t.TempDir(), "state")
	event := accountSwitcherAuditEvent{
		Timestamp:          time.Now().UTC().Format(time.RFC3339Nano),
		Action:             "switch",
		Result:             auditResultSuccess,
		Client:             "Visual Studio Code",
		AccountLabel:       "Account 2",
		AccountIDHashShort: "123456789abc",
		StateDirectory:     stateDirectory,
	}

	if err := appendAccountSwitcherAuditEvent(event); err != nil {
		t.Fatalf("appendAccountSwitcherAuditEvent failed: %v", err)
	}

	auditLogPath := filepath.Join(stateDirectory, auditLogFileName)
	auditLogInfo, err := os.Lstat(auditLogPath)
	if err != nil {
		t.Fatalf("cannot stat audit log: %v", err)
	}
	if auditLogInfo.Mode().Perm() != privateFileMode {
		t.Fatalf("audit log mode = %04o, want %04o", auditLogInfo.Mode().Perm(), privateFileMode)
	}

	auditLogFile, err := os.Open(auditLogPath)
	if err != nil {
		t.Fatalf("cannot open audit log: %v", err)
	}
	defer auditLogFile.Close()
	scanner := bufio.NewScanner(auditLogFile)
	if !scanner.Scan() {
		t.Fatalf("audit log has no event: %v", scanner.Err())
	}
	var decodedEvent map[string]any
	if err := json.Unmarshal(scanner.Bytes(), &decodedEvent); err != nil {
		t.Fatalf("audit event is invalid JSON: %v", err)
	}
	if scanner.Scan() {
		t.Fatal("audit log unexpectedly contains more than one event")
	}
	if _, exists := decodedEvent["state_directory"]; exists {
		t.Fatal("audit event exposed its internal state directory")
	}
	if decodedEvent["account_id_sha256_short"] != "123456789abc" {
		t.Fatalf("unexpected audit identity: %v", decodedEvent["account_id_sha256_short"])
	}
}

func TestAppendAccountSwitcherAuditEventRotatesAtSizeLimit(t *testing.T) {
	stateDirectory := filepath.Join(t.TempDir(), "state")
	if err := ensurePrivateDirectory(stateDirectory); err != nil {
		t.Fatalf("cannot prepare state directory: %v", err)
	}
	auditLogPath := filepath.Join(stateDirectory, auditLogFileName)
	existingBytes := []byte(strings.Repeat("x", int(maximumAuditLogBytes-16)))
	if err := os.WriteFile(auditLogPath, existingBytes, privateFileMode); err != nil {
		t.Fatalf("cannot prepare full audit log: %v", err)
	}

	event := accountSwitcherAuditEvent{
		Timestamp:      time.Now().UTC().Format(time.RFC3339Nano),
		Action:         "login",
		Result:         auditResultStarted,
		Client:         "Antigravity",
		AccountLabel:   "Account 3",
		StateDirectory: stateDirectory,
	}
	if err := appendAccountSwitcherAuditEvent(event); err != nil {
		t.Fatalf("appendAccountSwitcherAuditEvent failed: %v", err)
	}

	rotatedBytes, err := os.ReadFile(filepath.Join(stateDirectory, auditLogRotatedFileName))
	if err != nil {
		t.Fatalf("cannot read rotated audit log: %v", err)
	}
	if string(rotatedBytes) != string(existingBytes) {
		t.Fatal("rotated audit log content changed")
	}
	currentAuditLogInfo, err := os.Lstat(auditLogPath)
	if err != nil {
		t.Fatalf("cannot stat current audit log: %v", err)
	}
	if currentAuditLogInfo.Size() <= 0 || currentAuditLogInfo.Size() >= maximumAuditLogBytes {
		t.Fatalf("current audit log has unexpected size: %d", currentAuditLogInfo.Size())
	}
}

func TestRecordAuditEventRejectsUnsupportedFields(t *testing.T) {
	stateDirectory := filepath.Join(t.TempDir(), "state")
	err := runRecordAuditEventCommand([]string{
		"--action", "token-export",
		"--result", auditResultSuccess,
		"--label", "Account 1",
		"--state-dir", stateDirectory,
	})
	if err == nil {
		t.Fatal("record-event accepted an unsupported action")
	}
}
