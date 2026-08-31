package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"

	"golang.org/x/sys/unix"
)

const (
	auditLogFileName                 = "events.jsonl"
	auditLogRotatedFileName          = "events.jsonl.1"
	auditLogLockFileName             = "events.lock"
	maximumAuditLogBytes       int64 = 1024 * 1024
	maximumAuditClientRunes          = 80
	auditClientEnvironmentName       = "AGENTS_RTL_ACCOUNT_SWITCHER_CLIENT"
	auditResultStarted               = "started"
	auditResultSuccess               = "success"
	auditResultFailure               = "failure"
)

type accountSwitcherAuditEvent struct {
	Timestamp            string `json:"timestamp"`
	Action               string `json:"action"`
	Result               string `json:"result"`
	Client               string `json:"client"`
	AccountLabel         string `json:"account_label,omitempty"`
	PreviousAccountLabel string `json:"previous_account_label,omitempty"`
	AccountIDHashShort   string `json:"account_id_sha256_short,omitempty"`
	StateDirectory       string `json:"-"`
}

func buildCommandAuditRequest(arguments []string) (accountSwitcherAuditEvent, bool, error) {
	if len(arguments) == 0 {
		return accountSwitcherAuditEvent{}, false, nil
	}

	action, commandIsAudited := auditedCommandAction(arguments[0])
	if !commandIsAudited {
		return accountSwitcherAuditEvent{}, false, nil
	}

	stateDirectory, err := auditStateDirectoryFromArguments(arguments[1:])
	if err != nil {
		return accountSwitcherAuditEvent{}, false, err
	}
	client, err := auditClientFromEnvironment()
	if err != nil {
		return accountSwitcherAuditEvent{}, false, err
	}
	accountLabel, previousAccountLabel, err := auditLabelsFromArguments(arguments)
	if err != nil {
		return accountSwitcherAuditEvent{}, false, err
	}

	return accountSwitcherAuditEvent{
		Timestamp:            time.Now().UTC().Format(time.RFC3339Nano),
		Action:               action,
		Client:               client,
		AccountLabel:         accountLabel,
		PreviousAccountLabel: previousAccountLabel,
		StateDirectory:       stateDirectory,
	}, true, nil
}

func auditedCommandAction(command string) (string, bool) {
	switch command {
	case "register", "add", "switch", "rename", "remove", "delete", "replace-auth", "adopt-current-login":
		if command == "delete" {
			return "remove", true
		}
		return command, true
	default:
		return "", false
	}
}

func auditStateDirectoryFromArguments(arguments []string) (string, error) {
	configuredStateDirectory, stateDirectoryExists, err := commandFlagValue(arguments, "--state-dir")
	if err != nil {
		return "", err
	}
	if stateDirectoryExists {
		return absolutePath(configuredStateDirectory, "state-dir")
	}
	return defaultStateDirectory()
}

func auditLabelsFromArguments(arguments []string) (string, string, error) {
	command := arguments[0]
	commandArguments := arguments[1:]
	if command == "rename" {
		previousLabel, _, err := commandFlagValue(commandArguments, "--from")
		if err != nil {
			return "", "", err
		}
		newLabel, _, err := commandFlagValue(commandArguments, "--to")
		return newLabel, previousLabel, err
	}

	flagName := "--label"
	switch command {
	case "switch":
		flagName = "--to"
	case "register":
		flagName = "--current-label"
	}
	label, _, err := commandFlagValue(commandArguments, flagName)
	return label, "", err
}

func commandFlagValue(arguments []string, flagName string) (string, bool, error) {
	for argumentIndex := 0; argumentIndex < len(arguments); argumentIndex++ {
		argument := arguments[argumentIndex]
		if argument == flagName {
			if argumentIndex+1 >= len(arguments) {
				return "", false, fmt.Errorf("%s requires a value", flagName)
			}
			return arguments[argumentIndex+1], true, nil
		}
		flagPrefix := flagName + "="
		if strings.HasPrefix(argument, flagPrefix) {
			return strings.TrimPrefix(argument, flagPrefix), true, nil
		}
	}
	return "", false, nil
}

func auditClientFromEnvironment() (string, error) {
	client := strings.TrimSpace(os.Getenv(auditClientEnvironmentName))
	if client == "" {
		client = "cli"
	}
	if err := validateAuditClient(client); err != nil {
		return "", err
	}
	return client, nil
}

func validateAuditClient(client string) error {
	if client == "" {
		return errors.New("audit client is required")
	}
	if len([]rune(client)) > maximumAuditClientRunes {
		return fmt.Errorf("audit client exceeds %d characters", maximumAuditClientRunes)
	}
	for _, character := range client {
		if unicode.IsControl(character) {
			return errors.New("audit client contains control characters")
		}
	}
	return nil
}

func populateSuccessfulAuditAccountHash(event *accountSwitcherAuditEvent) error {
	if event.AccountLabel == "" || event.Action == "remove" {
		return nil
	}
	statePath := filepath.Join(event.StateDirectory, stateFileName)
	state, err := readState(statePath)
	if err != nil {
		return fmt.Errorf("cannot read state for audit identity: %w", err)
	}
	accountIndex, accountExists := findAccountByLabel(state, event.AccountLabel)
	if event.Action == "adopt-current-login" {
		accountIndex, err = activeAccountIndex(state)
		if err != nil {
			return fmt.Errorf("cannot resolve active account for audit identity: %w", err)
		}
		accountExists = true
		event.AccountLabel = state.Accounts[accountIndex].Label
	}
	if !accountExists {
		return fmt.Errorf("audit account label is absent from state after %s: %q", event.Action, event.AccountLabel)
	}
	accountHash := state.Accounts[accountIndex].AccountIDHash
	if len(accountHash) < accountHashPrefixLength {
		return fmt.Errorf("audit account hash is shorter than %d characters for %q", accountHashPrefixLength, event.AccountLabel)
	}
	event.AccountIDHashShort = accountHash[:accountHashPrefixLength]
	return nil
}

func runRecordAuditEventCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("record-event", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	action := flags.String("action", "", "audit action")
	result := flags.String("result", "", "audit result")
	label := flags.String("label", "", "related account label")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected record-event arguments: %s", strings.Join(flags.Args(), " "))
	}
	if *action != "login" {
		return fmt.Errorf("unsupported recorded action %q: expected login", *action)
	}
	if *result != auditResultStarted && *result != auditResultSuccess && *result != auditResultFailure {
		return fmt.Errorf("unsupported recorded result %q: expected started, success, or failure", *result)
	}
	validatedStateDirectory, err := absolutePath(*stateDirectory, "state-dir")
	if err != nil {
		return err
	}
	validatedLabel, err := validateAccountLabel(*label)
	if err != nil {
		return fmt.Errorf("invalid audit account label: %w", err)
	}
	client, err := auditClientFromEnvironment()
	if err != nil {
		return err
	}
	return appendAccountSwitcherAuditEvent(accountSwitcherAuditEvent{
		Timestamp:      time.Now().UTC().Format(time.RFC3339Nano),
		Action:         *action,
		Result:         *result,
		Client:         client,
		AccountLabel:   validatedLabel,
		StateDirectory: validatedStateDirectory,
	})
}

func appendAccountSwitcherAuditEvent(event accountSwitcherAuditEvent) error {
	if err := validateAccountSwitcherAuditEvent(event); err != nil {
		return err
	}
	if err := ensurePrivateDirectory(event.StateDirectory); err != nil {
		return fmt.Errorf("cannot prepare audit state directory: %w", err)
	}

	encodedEvent, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("cannot encode account audit event: %w", err)
	}
	encodedEvent = append(encodedEvent, '\n')
	if int64(len(encodedEvent)) > maximumAuditLogBytes {
		return errors.New("one account audit event exceeds the complete audit log size limit")
	}

	lockFile, err := acquireAuditLogLock(event.StateDirectory)
	if err != nil {
		return err
	}
	appendErr := appendAuditEventWhileLocked(event.StateDirectory, encodedEvent)
	releaseErr := releaseAuditLogLock(lockFile)
	if appendErr != nil && releaseErr != nil {
		return fmt.Errorf("%w; additionally failed to release audit lock: %v", appendErr, releaseErr)
	}
	if appendErr != nil {
		return appendErr
	}
	if releaseErr != nil {
		return releaseErr
	}
	return nil
}

func validateAccountSwitcherAuditEvent(event accountSwitcherAuditEvent) error {
	if _, err := time.Parse(time.RFC3339Nano, event.Timestamp); err != nil {
		return fmt.Errorf("invalid audit timestamp: %w", err)
	}
	if event.Action == "" || event.Result == "" || event.Client == "" {
		return errors.New("audit action, result, and client are required")
	}
	if err := validateAuditClient(event.Client); err != nil {
		return err
	}
	if !supportedAuditAction(event.Action) {
		return fmt.Errorf("unsupported audit action %q", event.Action)
	}
	if event.Result != auditResultStarted && event.Result != auditResultSuccess && event.Result != auditResultFailure {
		return fmt.Errorf("unsupported audit result %q", event.Result)
	}
	if !filepath.IsAbs(event.StateDirectory) {
		return fmt.Errorf("audit state directory must be absolute: %s", event.StateDirectory)
	}
	return nil
}

func supportedAuditAction(action string) bool {
	switch action {
	case "register", "add", "switch", "rename", "remove", "replace-auth", "adopt-current-login", "login":
		return true
	default:
		return false
	}
}

func acquireAuditLogLock(stateDirectory string) (*os.File, error) {
	lockPath := filepath.Join(stateDirectory, auditLogLockFileName)
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, privateFileMode)
	if err != nil {
		return nil, fmt.Errorf("cannot open audit lock: %w", err)
	}
	lockFileInfo, err := lockFile.Stat()
	if err != nil {
		lockFile.Close()
		return nil, fmt.Errorf("cannot stat audit lock: %w", err)
	}
	if !lockFileInfo.Mode().IsRegular() || lockFileInfo.Mode().Perm() != privateFileMode {
		lockFile.Close()
		return nil, fmt.Errorf("audit lock must be a regular file with permissions 0600: %s", lockPath)
	}
	if err := unix.Flock(int(lockFile.Fd()), unix.LOCK_EX); err != nil {
		lockFile.Close()
		return nil, fmt.Errorf("cannot acquire audit lock: %w", err)
	}
	return lockFile, nil
}

func releaseAuditLogLock(lockFile *os.File) error {
	unlockErr := unix.Flock(int(lockFile.Fd()), unix.LOCK_UN)
	closeErr := lockFile.Close()
	if unlockErr != nil && closeErr != nil {
		return fmt.Errorf("cannot unlock audit log: %v; cannot close audit lock: %w", unlockErr, closeErr)
	}
	if unlockErr != nil {
		return fmt.Errorf("cannot unlock audit log: %w", unlockErr)
	}
	if closeErr != nil {
		return fmt.Errorf("cannot close audit lock: %w", closeErr)
	}
	return nil
}

func appendAuditEventWhileLocked(stateDirectory string, encodedEvent []byte) error {
	auditLogPath := filepath.Join(stateDirectory, auditLogFileName)
	if err := rotateAuditLogWhenRequired(stateDirectory, auditLogPath, int64(len(encodedEvent))); err != nil {
		return err
	}

	auditLogFile, err := os.OpenFile(auditLogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, privateFileMode)
	if err != nil {
		return fmt.Errorf("cannot open account audit log: %w", err)
	}
	if err := verifyPrivateRegularFile(auditLogFile, auditLogPath); err != nil {
		auditLogFile.Close()
		return err
	}
	if _, err := auditLogFile.Write(encodedEvent); err != nil {
		auditLogFile.Close()
		return fmt.Errorf("cannot append account audit event: %w", err)
	}
	if err := auditLogFile.Sync(); err != nil {
		auditLogFile.Close()
		return fmt.Errorf("cannot sync account audit log: %w", err)
	}
	if err := auditLogFile.Close(); err != nil {
		return fmt.Errorf("cannot close account audit log: %w", err)
	}
	return syncDirectory(stateDirectory)
}

func rotateAuditLogWhenRequired(stateDirectory string, auditLogPath string, incomingEventBytes int64) error {
	auditLogInfo, err := os.Lstat(auditLogPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot stat account audit log: %w", err)
	}
	if !auditLogInfo.Mode().IsRegular() || auditLogInfo.Mode().Perm() != privateFileMode {
		return fmt.Errorf("account audit log must be a regular file with permissions 0600: %s", auditLogPath)
	}
	if auditLogInfo.Size()+incomingEventBytes <= maximumAuditLogBytes {
		return nil
	}

	rotatedAuditLogPath := filepath.Join(stateDirectory, auditLogRotatedFileName)
	if err := removeExistingRotatedAuditLog(rotatedAuditLogPath); err != nil {
		return err
	}
	if err := os.Rename(auditLogPath, rotatedAuditLogPath); err != nil {
		return fmt.Errorf("cannot rotate account audit log: %w", err)
	}
	return syncDirectory(stateDirectory)
}

func removeExistingRotatedAuditLog(rotatedAuditLogPath string) error {
	rotatedLogInfo, err := os.Lstat(rotatedAuditLogPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot stat rotated account audit log: %w", err)
	}
	if !rotatedLogInfo.Mode().IsRegular() || rotatedLogInfo.Mode().Perm() != privateFileMode {
		return fmt.Errorf("rotated account audit log must be a regular file with permissions 0600: %s", rotatedAuditLogPath)
	}
	if err := os.Remove(rotatedAuditLogPath); err != nil {
		return fmt.Errorf("cannot remove previous rotated account audit log: %w", err)
	}
	return nil
}

func verifyPrivateRegularFile(file *os.File, filePath string) error {
	fileInfo, err := file.Stat()
	if err != nil {
		return fmt.Errorf("cannot stat private file %s: %w", filePath, err)
	}
	if !fileInfo.Mode().IsRegular() || fileInfo.Mode().Perm() != privateFileMode {
		return fmt.Errorf("private file must be regular with permissions 0600: %s", filePath)
	}
	return nil
}
