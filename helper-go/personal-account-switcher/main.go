package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"golang.org/x/sys/unix"
)

const (
	accountStateSchemaVersion       = 2
	legacyAccountStateSchemaVersion = 1
	maximumAuthFileBytes            = 128 * 1024
	maximumAccountLabelRunes        = 80
	accountHashPrefixLength         = 12
	privateDirectoryMode            = 0o700
	privateFileMode                 = 0o600
	stateFileName                   = "state.json"
	accountsDirectoryName           = "accounts"
	removedAccountsDirectoryName    = "removed-accounts"
	pendingLoginAccountsFileName    = "pending-login-accounts.json"
	replacedAuthDirectoryName       = "replaced-auth"
	authFileName                    = "auth.json"
	switchLockFileName              = "switch.lock"
)

var errPreviousActiveAuthNotFound = errors.New("previous active auth not found")

type appServerProcessPolicy int

const (
	skipAppServerProcessCheck appServerProcessPolicy = iota
	requireStoppedAppServers
)

type authTokens struct {
	AccessToken  string `json:"access_token"`
	AccountID    string `json:"account_id"`
	IDToken      string `json:"id_token"`
	RefreshToken string `json:"refresh_token"`
}

type authFilePayload struct {
	AuthMode string     `json:"auth_mode"`
	Tokens   authTokens `json:"tokens"`
}

type accountIdentity struct {
	Label         string `json:"label"`
	AccountIDHash string `json:"account_id_sha256"`
	Email         string `json:"email,omitempty"`
	Name          string `json:"name,omitempty"`
}

type pendingLoginAccount struct {
	Label            string `json:"label"`
	AccountIDHash    string `json:"account_id_sha256"`
	Email            string `json:"email,omitempty"`
	Name             string `json:"name,omitempty"`
	LastActiveAt     string `json:"last_active_at,omitempty"`
	PendingReason    string `json:"pending_reason"`
	MovedToPendingAt string `json:"moved_to_pending_at"`
}

type registeredAccount struct {
	Label         string `json:"label"`
	AccountIDHash string `json:"account_id_sha256"`
	Email         string `json:"email,omitempty"`
	Name          string `json:"name,omitempty"`
	AuthPath      string `json:"auth_path"`
	Active        bool   `json:"active"`
	LastActiveAt  string `json:"last_active_at,omitempty"`
}

type accountSwitcherState struct {
	SchemaVersion  int                 `json:"schema_version"`
	SharedAuthPath string              `json:"shared_auth_path"`
	Accounts       []registeredAccount `json:"accounts"`
}

type legacyAccountSwitcherState struct {
	SchemaVersion    int             `json:"schema_version"`
	AuthPath         string          `json:"auth_path"`
	InactiveAuthPath string          `json:"inactive_auth_path"`
	ActiveAccount    accountIdentity `json:"active_account"`
	InactiveAccount  accountIdentity `json:"inactive_account"`
}

type accountStatusOutput struct {
	Label              string `json:"label"`
	Active             bool   `json:"active"`
	AccountIDHash      string `json:"account_id_sha256"`
	AccountIDHashShort string `json:"account_id_sha256_short"`
	DisplayName        string `json:"display_name"`
	Email              string `json:"email,omitempty"`
	Name               string `json:"name,omitempty"`
	AuthPath           string `json:"auth_path"`
	LastActiveAt       string `json:"last_active_at,omitempty"`
	AuthModifiedAt     string `json:"auth_modified_at"`
}

type pendingLoginAccountStatusOutput struct {
	Label              string `json:"label"`
	AccountIDHash      string `json:"account_id_sha256"`
	AccountIDHashShort string `json:"account_id_sha256_short"`
	DisplayName        string `json:"display_name"`
	Email              string `json:"email,omitempty"`
	Name               string `json:"name,omitempty"`
	LastActiveAt       string `json:"last_active_at,omitempty"`
	PendingReason      string `json:"pending_reason"`
	MovedToPendingAt   string `json:"moved_to_pending_at"`
}

type stateOutput struct {
	Action                    string                            `json:"action"`
	AccountsCount             int                               `json:"accounts_count"`
	PendingLoginAccountsCount int                               `json:"pending_login_accounts_count"`
	TotalAccountsCount        int                               `json:"total_accounts_count"`
	ActiveAccount             string                            `json:"active_account"`
	ActiveAccountDisplayName  string                            `json:"active_account_display_name"`
	SharedCodexHome           string                            `json:"shared_codex_home"`
	SharedAuthPath            string                            `json:"shared_auth_path"`
	Accounts                  []accountStatusOutput             `json:"accounts"`
	PendingLoginAccounts      []pendingLoginAccountStatusOutput `json:"pending_login_accounts,omitempty"`
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "codex-account-switcher: %v\n", err)
		os.Exit(1)
	}
}

func run(arguments []string) error {
	auditRequest, auditRequestExists, auditRequestErr := buildCommandAuditRequest(arguments)
	if auditRequestErr != nil {
		return auditRequestErr
	}

	commandErr := runCommand(arguments)
	if !auditRequestExists {
		return commandErr
	}

	auditRequest.Result = auditResultSuccess
	if commandErr != nil {
		auditRequest.Result = auditResultFailure
	} else if err := populateSuccessfulAuditAccountHash(&auditRequest); err != nil {
		return fmt.Errorf("account operation completed but its audit identity could not be resolved: %w", err)
	}
	auditErr := appendAccountSwitcherAuditEvent(auditRequest)
	if commandErr != nil && auditErr != nil {
		return fmt.Errorf("%w; additionally failed to append audit event: %v", commandErr, auditErr)
	}
	if commandErr != nil {
		return commandErr
	}
	if auditErr != nil {
		return fmt.Errorf("account operation completed but its audit event could not be recorded: %w", auditErr)
	}
	return nil
}

func runCommand(arguments []string) error {
	if len(arguments) == 0 {
		return errors.New("command is required: register, add, status, switch, rename, remove, replace-auth, adopt-current-login, or record-event")
	}

	switch arguments[0] {
	case "register":
		return runRegisterCommand(arguments[1:])
	case "add":
		return runAddCommand(arguments[1:])
	case "status":
		return runStatusCommand(arguments[1:])
	case "switch":
		return runSwitchCommand(arguments[1:])
	case "rename":
		return runRenameCommand(arguments[1:])
	case "remove", "delete":
		return runRemoveCommand(arguments[1:])
	case "replace-auth":
		return runReplaceAuthCommand(arguments[1:])
	case "adopt-current-login":
		return runAdoptCurrentLoginCommand(arguments[1:])
	case "record-event":
		return runRecordAuditEventCommand(arguments[1:])
	default:
		return fmt.Errorf("unsupported command %q: expected register, add, status, switch, rename, remove, replace-auth, adopt-current-login, or record-event", arguments[0])
	}
}

func runRegisterCommand(arguments []string) error {
	defaultCodexHomePath, err := defaultCodexHome()
	if err != nil {
		return err
	}
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("register", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	currentLabel := flags.String("current-label", "", "label for the account currently active in CODEX_HOME")
	inactiveLabel := flags.String("inactive-label", "", "label for the second account")
	inactiveAuthPath := flags.String("inactive-auth", "", "auth.json created by the second account login")
	codexHome := flags.String("codex-home", defaultCodexHomePath, "shared Codex home containing conversations")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected register arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := registerAccounts(*currentLabel, *inactiveLabel, *inactiveAuthPath, *codexHome, *stateDirectory)
	if err != nil {
		return err
	}
	return printState("registered", state, *stateDirectory, *printJSON)
}

func runAddCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("add", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	label := flags.String("label", "", "label for the new account")
	authPath := flags.String("auth", "", "auth.json created by the new account login")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected add arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := addAccount(*label, *authPath, *stateDirectory)
	if err != nil {
		return err
	}
	return printState("added", state, *stateDirectory, *printJSON)
}

func runStatusCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected status arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := loadAndVerifyState(*stateDirectory)
	if err != nil {
		return err
	}
	return printState("ready", state, *stateDirectory, *printJSON)
}

func runSwitchCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("switch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	targetLabel := flags.String("to", "", "registered account label to activate")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	liveSwitch := flags.Bool("live", false, "switch while Codex app-server is running; requires restarting the extension host")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected switch arguments: %s", strings.Join(flags.Args(), " "))
	}

	processPolicy := requireStoppedAppServers
	if *liveSwitch {
		processPolicy = skipAppServerProcessCheck
	}
	state, err := switchAccounts(*targetLabel, *stateDirectory, processPolicy)
	if err != nil {
		return err
	}
	if err := printState("switched", state, *stateDirectory, *printJSON); err != nil {
		return err
	}
	if *liveSwitch && !*printJSON {
		fmt.Println("restart_required: Developer: Restart Extension Host")
	}
	return nil
}

func runRenameCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("rename", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	fromLabel := flags.String("from", "", "registered account label to rename")
	toLabel := flags.String("to", "", "new account label")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected rename arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := renameAccount(*fromLabel, *toLabel, *stateDirectory)
	if err != nil {
		return err
	}
	return printState("renamed", state, *stateDirectory, *printJSON)
}

func runRemoveCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("remove", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	label := flags.String("label", "", "inactive registered account label to remove")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected remove arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := removeAccount(*label, *stateDirectory)
	if err != nil {
		return err
	}
	return printState("removed", state, *stateDirectory, *printJSON)
}

func runReplaceAuthCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("replace-auth", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	label := flags.String("label", "", "registered account label whose auth should be replaced")
	authPath := flags.String("auth", "", "fresh auth.json for the same ChatGPT account")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	liveReplace := flags.Bool("live", false, "replace active auth while Codex app-server is running; requires restarting the extension host")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected replace-auth arguments: %s", strings.Join(flags.Args(), " "))
	}

	processPolicy := requireStoppedAppServers
	if *liveReplace {
		processPolicy = skipAppServerProcessCheck
	}
	state, err := replaceAccountAuth(*label, *authPath, *stateDirectory, processPolicy)
	if err != nil {
		return err
	}
	if err := printState("auth-replaced", state, *stateDirectory, *printJSON); err != nil {
		return err
	}
	if *liveReplace && !*printJSON {
		fmt.Println("restart_required: Developer: Restart Extension Host")
	}
	return nil
}

func runAdoptCurrentLoginCommand(arguments []string) error {
	defaultStateDirectoryPath, err := defaultStateDirectory()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("adopt-current-login", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	label := flags.String("label", "", "new label for the manually logged-in shared auth.json")
	stateDirectory := flags.String("state-dir", defaultStateDirectoryPath, "private account-switcher state directory")
	printJSON := flags.Bool("json", false, "print machine-readable JSON")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected adopt-current-login arguments: %s", strings.Join(flags.Args(), " "))
	}

	state, err := adoptCurrentLogin(*label, *stateDirectory)
	if err != nil {
		return err
	}
	return printState("current-login-adopted", state, *stateDirectory, *printJSON)
}

func defaultCodexHome() (string, error) {
	if configuredCodexHome := strings.TrimSpace(os.Getenv("CODEX_HOME")); configuredCodexHome != "" {
		return configuredCodexHome, nil
	}

	homeDirectory, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("cannot resolve user home for CODEX_HOME: %w", err)
	}
	return filepath.Join(homeDirectory, ".codex"), nil
}

func defaultStateDirectory() (string, error) {
	homeDirectory, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("cannot resolve user home for account switcher state: %w", err)
	}
	return filepath.Join(homeDirectory, ".local", "share", "agents-rtl-personal", "codex-account-switcher"), nil
}

func registerAccounts(currentLabel string, inactiveLabel string, inactiveAuthPath string, codexHome string, stateDirectory string) (accountSwitcherState, error) {
	validatedCurrentLabel, err := validateAccountLabel(currentLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid current account label: %w", err)
	}
	validatedInactiveLabel, err := validateAccountLabel(inactiveLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid inactive account label: %w", err)
	}
	if validatedCurrentLabel == validatedInactiveLabel {
		return accountSwitcherState{}, errors.New("account labels must be different")
	}

	validatedCodexHome, err := absolutePath(codexHome, "codex-home")
	if err != nil {
		return accountSwitcherState{}, err
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}
	validatedInactiveAuthPath, err := absolutePath(inactiveAuthPath, "inactive-auth")
	if err != nil {
		return accountSwitcherState{}, err
	}

	sharedAuthPath := filepath.Join(validatedCodexHome, authFileName)
	if sharedAuthPath == validatedInactiveAuthPath {
		return accountSwitcherState{}, errors.New("active and imported auth paths must be distinct")
	}

	activeIdentity, err := loadAuthIdentity(sharedAuthPath, validatedCurrentLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("active account auth is invalid: %w", err)
	}
	inactiveIdentity, err := loadAuthIdentity(validatedInactiveAuthPath, validatedInactiveLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("inactive account auth is invalid: %w", err)
	}
	if activeIdentity.AccountIDHash == inactiveIdentity.AccountIDHash {
		return accountSwitcherState{}, errors.New("the two auth files belong to the same ChatGPT account")
	}

	if err := ensurePrivateDirectory(validatedStateDirectory); err != nil {
		return accountSwitcherState{}, err
	}
	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	statePath := filepath.Join(validatedStateDirectory, stateFileName)
	if err := requirePathDoesNotExist(statePath, "account switcher state"); err != nil {
		return accountSwitcherState{}, err
	}

	inactiveAuthDestination, err := prepareStoredAuthDestination(validatedStateDirectory, inactiveIdentity)
	if err != nil {
		return accountSwitcherState{}, err
	}
	if sharedAuthPath == inactiveAuthDestination || validatedInactiveAuthPath == inactiveAuthDestination {
		return accountSwitcherState{}, errors.New("active, imported, and stored auth paths must be distinct")
	}

	state := accountSwitcherState{
		SchemaVersion:  accountStateSchemaVersion,
		SharedAuthPath: sharedAuthPath,
		Accounts: []registeredAccount{
			accountRecordFromIdentity(activeIdentity, sharedAuthPath, true),
			accountRecordFromIdentity(inactiveIdentity, inactiveAuthDestination, false),
		},
	}

	if err := moveImportedAuth(validatedInactiveAuthPath, inactiveAuthDestination); err != nil {
		return accountSwitcherState{}, err
	}
	if err := writeStateAtomically(validatedStateDirectory, state); err != nil {
		return accountSwitcherState{}, rollbackImportedAuth(validatedInactiveAuthPath, inactiveAuthDestination, err)
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	return verifiedState, nil
}

func addAccount(label string, authPath string, stateDirectory string) (accountSwitcherState, error) {
	validatedLabel, err := validateAccountLabel(label)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid account label: %w", err)
	}
	validatedAuthPath, err := absolutePath(authPath, "auth")
	if err != nil {
		return accountSwitcherState{}, err
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}

	if err := ensurePrivateDirectory(validatedStateDirectory); err != nil {
		return accountSwitcherState{}, err
	}
	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	pendingLoginAccounts, err := readPendingLoginAccounts(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	if validatedAuthPath == state.SharedAuthPath {
		return accountSwitcherState{}, errors.New("imported auth path must not be the active shared auth path")
	}

	newIdentity, err := loadAuthIdentity(validatedAuthPath, validatedLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("new account auth is invalid: %w", err)
	}
	if _, exists := findAccountByLabel(state, validatedLabel); exists {
		return accountSwitcherState{}, fmt.Errorf("account label %q is already registered", validatedLabel)
	}
	if _, exists := findAccountByHash(state, newIdentity.AccountIDHash); exists {
		return accountSwitcherState{}, errors.New("the imported auth belongs to an already registered account")
	}
	pendingAccountIndex, pendingAccount, err := pendingLoginAccountForImport(
		pendingLoginAccounts,
		validatedLabel,
		newIdentity.AccountIDHash,
	)
	if err != nil {
		return accountSwitcherState{}, err
	}

	storedAuthDestination, err := prepareUniqueStoredAuthDestination(validatedStateDirectory, newIdentity)
	if err != nil {
		return accountSwitcherState{}, err
	}
	for _, account := range state.Accounts {
		if account.AuthPath == storedAuthDestination {
			return accountSwitcherState{}, fmt.Errorf("stored auth path is already registered: %s", storedAuthDestination)
		}
	}

	authAlreadyStored := false
	if _, err := os.Lstat(storedAuthDestination); err == nil {
		authAlreadyStored = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return accountSwitcherState{}, fmt.Errorf("cannot stat stored auth destination: %w", err)
	}
	if !authAlreadyStored {
		if err := moveImportedAuth(validatedAuthPath, storedAuthDestination); err != nil {
			return accountSwitcherState{}, err
		}
	}

	previousState := state
	previousState.Accounts = append([]registeredAccount{}, state.Accounts...)
	accountRecord := accountRecordFromIdentity(newIdentity, storedAuthDestination, false)
	if pendingAccountIndex >= 0 {
		accountRecord.LastActiveAt = pendingAccount.LastActiveAt
	}
	state.Accounts = append(state.Accounts, accountRecord)
	sortAccountsForStableOutput(state.Accounts)
	if err := writeStateAtomically(validatedStateDirectory, state); err != nil {
		if authAlreadyStored {
			return accountSwitcherState{}, err
		}
		return accountSwitcherState{}, rollbackImportedAuth(validatedAuthPath, storedAuthDestination, err)
	}
	if pendingAccountIndex >= 0 {
		remainingPendingLoginAccounts := append(
			append([]pendingLoginAccount{}, pendingLoginAccounts[:pendingAccountIndex]...),
			pendingLoginAccounts[pendingAccountIndex+1:]...,
		)
		if err := writePendingLoginAccountsAtomically(validatedStateDirectory, remainingPendingLoginAccounts); err != nil {
			return accountSwitcherState{}, rollbackAccountImport(
				validatedStateDirectory,
				previousState,
				pendingLoginAccounts,
				validatedAuthPath,
				storedAuthDestination,
				!authAlreadyStored,
				err,
			)
		}
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, rollbackAccountImport(
			validatedStateDirectory,
			previousState,
			pendingLoginAccounts,
			validatedAuthPath,
			storedAuthDestination,
			!authAlreadyStored,
			err,
		)
	}
	if _, err := buildStateOutput("verify-account-import", verifiedState, validatedStateDirectory); err != nil {
		return accountSwitcherState{}, rollbackAccountImport(
			validatedStateDirectory,
			previousState,
			pendingLoginAccounts,
			validatedAuthPath,
			storedAuthDestination,
			!authAlreadyStored,
			err,
		)
	}
	return verifiedState, nil
}

func switchAccounts(targetLabel string, stateDirectory string, processPolicy appServerProcessPolicy) (accountSwitcherState, error) {
	validatedTargetLabel, err := validateAccountLabel(targetLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid target account label: %w", err)
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}
	if processPolicy == requireStoppedAppServers {
		if err := ensureCodexAppServersAreStopped(); err != nil {
			return accountSwitcherState{}, err
		}
	}

	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	activeIndex, err := activeAccountIndex(state)
	if err != nil {
		return accountSwitcherState{}, err
	}
	targetIndex, exists := findAccountByLabel(state, validatedTargetLabel)
	if !exists {
		return accountSwitcherState{}, fmt.Errorf("account %q is not registered", validatedTargetLabel)
	}
	if activeIndex == targetIndex {
		return accountSwitcherState{}, fmt.Errorf("account %q is already active", validatedTargetLabel)
	}

	targetStoredAuthPath := state.Accounts[targetIndex].AuthPath
	if err := exchangeAuthFiles(state.SharedAuthPath, targetStoredAuthPath); err != nil {
		return accountSwitcherState{}, err
	}
	if err := verifyExchangedAuthFiles(state, targetIndex); err != nil {
		return accountSwitcherState{}, rollbackAuthExchange(state, targetIndex, err)
	}
	if err := syncDirectory(filepath.Dir(state.SharedAuthPath)); err != nil {
		return accountSwitcherState{}, rollbackAuthExchange(state, targetIndex, err)
	}
	if filepath.Dir(state.SharedAuthPath) != filepath.Dir(targetStoredAuthPath) {
		if err := syncDirectory(filepath.Dir(targetStoredAuthPath)); err != nil {
			return accountSwitcherState{}, rollbackAuthExchange(state, targetIndex, err)
		}
	}

	nextState := state
	nextState.Accounts[activeIndex].Active = false
	nextState.Accounts[activeIndex].AuthPath = targetStoredAuthPath
	nextState.Accounts[targetIndex].Active = true
	nextState.Accounts[targetIndex].AuthPath = state.SharedAuthPath
	nextState.Accounts[targetIndex].LastActiveAt = currentTimestamp()
	sortAccountsForStableOutput(nextState.Accounts)
	if err := writeStateAtomically(validatedStateDirectory, nextState); err != nil {
		return accountSwitcherState{}, rollbackAuthExchange(state, targetIndex, err)
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	return verifiedState, nil
}

func renameAccount(fromLabel string, toLabel string, stateDirectory string) (accountSwitcherState, error) {
	validatedFromLabel, err := validateAccountLabel(fromLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid source account label: %w", err)
	}
	validatedToLabel, err := validateAccountLabel(toLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid target account label: %w", err)
	}
	if validatedFromLabel == validatedToLabel {
		return accountSwitcherState{}, errors.New("source and target account labels are identical")
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}

	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	accountIndex, exists := findAccountByLabel(state, validatedFromLabel)
	if !exists {
		return accountSwitcherState{}, fmt.Errorf("account %q is not registered", validatedFromLabel)
	}
	if _, exists := findAccountByLabel(state, validatedToLabel); exists {
		return accountSwitcherState{}, fmt.Errorf("account label %q is already registered", validatedToLabel)
	}

	state.Accounts[accountIndex].Label = validatedToLabel
	sortAccountsForStableOutput(state.Accounts)
	if err := writeStateAtomically(validatedStateDirectory, state); err != nil {
		return accountSwitcherState{}, err
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	return verifiedState, nil
}

func removeAccount(label string, stateDirectory string) (accountSwitcherState, error) {
	validatedLabel, err := validateAccountLabel(label)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid account label: %w", err)
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}

	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	accountIndex, exists := findAccountByLabel(state, validatedLabel)
	if !exists {
		return accountSwitcherState{}, fmt.Errorf("account %q is not registered", validatedLabel)
	}
	if state.Accounts[accountIndex].Active {
		return accountSwitcherState{}, errors.New("cannot remove the active account; switch to another account first")
	}
	if len(state.Accounts) <= 2 {
		return accountSwitcherState{}, errors.New("cannot remove account because at least two accounts must remain registered")
	}

	removedAccount := state.Accounts[accountIndex]
	archivedAuthPath, err := archiveAuthFile(validatedStateDirectory, removedAccountsDirectoryName, removedAccount)
	if err != nil {
		return accountSwitcherState{}, err
	}

	state.Accounts = append(state.Accounts[:accountIndex], state.Accounts[accountIndex+1:]...)
	sortAccountsForStableOutput(state.Accounts)
	if err := writeStateAtomically(validatedStateDirectory, state); err != nil {
		return accountSwitcherState{}, rollbackArchivedAuth(archivedAuthPath, removedAccount.AuthPath, err)
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	return verifiedState, nil
}

func replaceAccountAuth(label string, authPath string, stateDirectory string, processPolicy appServerProcessPolicy) (accountSwitcherState, error) {
	validatedLabel, err := validateAccountLabel(label)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid account label: %w", err)
	}
	validatedAuthPath, err := absolutePath(authPath, "auth")
	if err != nil {
		return accountSwitcherState{}, err
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}

	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	accountIndex, exists := findAccountByLabel(state, validatedLabel)
	if !exists {
		return accountSwitcherState{}, fmt.Errorf("account %q is not registered", validatedLabel)
	}
	targetAccount := state.Accounts[accountIndex]
	if targetAccount.Active && processPolicy == requireStoppedAppServers {
		if err := ensureCodexAppServersAreStopped(); err != nil {
			return accountSwitcherState{}, err
		}
	}
	if validatedAuthPath == targetAccount.AuthPath {
		return accountSwitcherState{}, errors.New("replacement auth path must be different from the registered auth path")
	}

	replacementIdentity, err := loadAuthIdentity(validatedAuthPath, targetAccount.Label)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("replacement account auth is invalid: %w", err)
	}
	if replacementIdentity.AccountIDHash != targetAccount.AccountIDHash {
		return accountSwitcherState{}, fmt.Errorf("replacement auth belongs to a different account: expected %s, got %s", targetAccount.AccountIDHash, replacementIdentity.AccountIDHash)
	}

	backupAuthPath, err := replaceAuthFile(validatedAuthPath, targetAccount.AuthPath, validatedStateDirectory, targetAccount)
	if err != nil {
		return accountSwitcherState{}, err
	}
	state.Accounts[accountIndex].Email = replacementIdentity.Email
	state.Accounts[accountIndex].Name = replacementIdentity.Name
	if err := writeStateAtomically(validatedStateDirectory, state); err != nil {
		return accountSwitcherState{}, rollbackAuthReplacement(targetAccount.AuthPath, backupAuthPath, err)
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, rollbackAuthReplacement(targetAccount.AuthPath, backupAuthPath, err)
	}
	return verifiedState, nil
}

func adoptCurrentLogin(label string, stateDirectory string) (accountSwitcherState, error) {
	validatedLabel, err := validateAccountLabel(label)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid account label: %w", err)
	}
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}

	lockFile, err := acquireExclusiveLock(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	defer releaseExclusiveLock(lockFile)

	state, activeIndex, err := loadStateForCurrentLoginAdoption(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, err
	}
	currentIdentity, err := loadAuthIdentity(state.SharedAuthPath, validatedLabel)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("current shared auth is invalid: %w", err)
	}
	previousActiveAccount := state.Accounts[activeIndex]
	if previousActiveAccount.AccountIDHash == currentIdentity.AccountIDHash {
		return loadAndVerifyState(validatedStateDirectory)
	}
	previousActiveAuthPath, copiedPreviousActiveAuthPath, err := storedAuthPathForPreviousActiveAccount(validatedStateDirectory, state, previousActiveAccount)
	previousActiveAuthIsMissing := errors.Is(err, errPreviousActiveAuthNotFound)
	if err != nil && !previousActiveAuthIsMissing {
		return accountSwitcherState{}, err
	}

	if _, err := backupStateFile(validatedStateDirectory, "adopt-current-login"); err != nil {
		return accountSwitcherState{}, err
	}

	nextState := state
	if previousActiveAuthIsMissing {
		if err := moveAccountToPendingLoginAccounts(validatedStateDirectory, previousActiveAccount, "auth_missing_after_manual_login_switch"); err != nil {
			return accountSwitcherState{}, err
		}
		nextState.Accounts = append(nextState.Accounts[:activeIndex], nextState.Accounts[activeIndex+1:]...)
	} else {
		nextState.Accounts[activeIndex].Active = false
		nextState.Accounts[activeIndex].AuthPath = previousActiveAuthPath
	}
	existingIndex, existingAccountFound := findAccountByHash(nextState, currentIdentity.AccountIDHash)
	if existingAccountFound {
		if !previousActiveAuthIsMissing && existingIndex == activeIndex {
			return accountSwitcherState{}, fmt.Errorf("active account %q has a stale hash verification state", previousActiveAccount.Label)
		}
		nextState.Accounts[existingIndex].Active = true
		nextState.Accounts[existingIndex].AuthPath = nextState.SharedAuthPath
		nextState.Accounts[existingIndex].Email = currentIdentity.Email
		nextState.Accounts[existingIndex].Name = currentIdentity.Name
		nextState.Accounts[existingIndex].LastActiveAt = currentTimestamp()
	} else {
		if _, exists := findAccountByLabel(nextState, validatedLabel); exists {
			return accountSwitcherState{}, fmt.Errorf("account label %q is already registered", validatedLabel)
		}
		nextState.Accounts = append(nextState.Accounts, accountRecordFromIdentity(currentIdentity, nextState.SharedAuthPath, true))
	}

	sortAccountsForStableOutput(nextState.Accounts)
	if err := writeStateAtomically(validatedStateDirectory, nextState); err != nil {
		return accountSwitcherState{}, rollbackCopiedAuthFile(copiedPreviousActiveAuthPath, err)
	}

	verifiedState, err := loadAndVerifyState(validatedStateDirectory)
	if err != nil {
		return accountSwitcherState{}, rollbackCopiedAuthFile(copiedPreviousActiveAuthPath, err)
	}
	return verifiedState, nil
}

func loadAndVerifyState(stateDirectory string) (accountSwitcherState, error) {
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, err
	}
	if err := verifyPrivateDirectory(validatedStateDirectory); err != nil {
		return accountSwitcherState{}, err
	}

	statePath := filepath.Join(validatedStateDirectory, stateFileName)
	state, err := readState(statePath)
	if err != nil {
		return accountSwitcherState{}, err
	}
	return verifyStateAuthFiles(state)
}

func loadStateForCurrentLoginAdoption(stateDirectory string) (accountSwitcherState, int, error) {
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return accountSwitcherState{}, -1, err
	}
	if err := verifyPrivateDirectory(validatedStateDirectory); err != nil {
		return accountSwitcherState{}, -1, err
	}

	statePath := filepath.Join(validatedStateDirectory, stateFileName)
	state, err := readState(statePath)
	if err != nil {
		return accountSwitcherState{}, -1, err
	}
	return verifyStateForCurrentLoginAdoption(state)
}

func readState(statePath string) (accountSwitcherState, error) {
	fileInfo, err := os.Lstat(statePath)
	if err != nil {
		return accountSwitcherState{}, fmt.Errorf("cannot stat account switcher state %s: %w", statePath, err)
	}
	if !fileInfo.Mode().IsRegular() || fileInfo.Mode().Perm() != privateFileMode {
		return accountSwitcherState{}, fmt.Errorf("account switcher state must be a regular file with permissions 0600: %s", statePath)
	}
	if fileInfo.Size() <= 0 || fileInfo.Size() > maximumAuthFileBytes {
		return accountSwitcherState{}, fmt.Errorf("account switcher state has invalid size %d: %s", fileInfo.Size(), statePath)
	}

	stateBytes, err := os.ReadFile(statePath)
	if err != nil {
		return accountSwitcherState{}, err
	}
	envelope := struct {
		SchemaVersion int `json:"schema_version"`
	}{}
	if err := json.Unmarshal(stateBytes, &envelope); err != nil {
		return accountSwitcherState{}, fmt.Errorf("invalid account switcher state JSON: %w", err)
	}
	switch envelope.SchemaVersion {
	case legacyAccountStateSchemaVersion:
		legacyState := legacyAccountSwitcherState{}
		if err := decodeStrictJSON(stateBytes, &legacyState, "legacy account switcher state"); err != nil {
			return accountSwitcherState{}, err
		}
		return convertLegacyState(legacyState), nil
	case accountStateSchemaVersion:
		state := accountSwitcherState{}
		if err := decodeStrictJSON(stateBytes, &state, "account switcher state"); err != nil {
			return accountSwitcherState{}, err
		}
		return state, nil
	default:
		return accountSwitcherState{}, fmt.Errorf("unsupported account switcher state schema version: %d", envelope.SchemaVersion)
	}
}

func decodeStrictJSON(data []byte, target any, description string) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("invalid %s JSON: %w", description, err)
	}
	if err := ensureJSONDocumentEnded(decoder); err != nil {
		return fmt.Errorf("invalid %s JSON: %w", description, err)
	}
	return nil
}

func convertLegacyState(legacyState legacyAccountSwitcherState) accountSwitcherState {
	return accountSwitcherState{
		SchemaVersion:  accountStateSchemaVersion,
		SharedAuthPath: legacyState.AuthPath,
		Accounts: []registeredAccount{
			accountRecordFromIdentity(legacyState.ActiveAccount, legacyState.AuthPath, true),
			accountRecordFromIdentity(legacyState.InactiveAccount, legacyState.InactiveAuthPath, false),
		},
	}
}

func writeStateAtomically(stateDirectory string, state accountSwitcherState) error {
	state.SchemaVersion = accountStateSchemaVersion
	stateBytes, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	stateBytes = append(stateBytes, '\n')

	temporaryStateFile, err := os.CreateTemp(stateDirectory, ".state-*.tmp")
	if err != nil {
		return err
	}
	temporaryStatePath := temporaryStateFile.Name()
	removeTemporaryState := true
	defer func() {
		if removeTemporaryState {
			_ = os.Remove(temporaryStatePath)
		}
	}()

	if err := temporaryStateFile.Chmod(privateFileMode); err != nil {
		temporaryStateFile.Close()
		return err
	}
	if _, err := temporaryStateFile.Write(stateBytes); err != nil {
		temporaryStateFile.Close()
		return err
	}
	if err := temporaryStateFile.Sync(); err != nil {
		temporaryStateFile.Close()
		return err
	}
	if err := temporaryStateFile.Close(); err != nil {
		return err
	}

	statePath := filepath.Join(stateDirectory, stateFileName)
	if err := os.Rename(temporaryStatePath, statePath); err != nil {
		return err
	}
	removeTemporaryState = false
	return syncDirectory(stateDirectory)
}

func moveAccountToPendingLoginAccounts(stateDirectory string, account registeredAccount, pendingReason string) error {
	pendingAccounts, err := readPendingLoginAccounts(stateDirectory)
	if err != nil {
		return err
	}
	pendingAccount := pendingLoginAccountFromRegisteredAccount(account, pendingReason)
	pendingAccounts = upsertPendingLoginAccount(pendingAccounts, pendingAccount)
	sortPendingLoginAccountsForStableOutput(pendingAccounts)
	return writePendingLoginAccountsAtomically(stateDirectory, pendingAccounts)
}

func pendingLoginAccountFromRegisteredAccount(account registeredAccount, pendingReason string) pendingLoginAccount {
	return pendingLoginAccount{
		Label:            account.Label,
		AccountIDHash:    account.AccountIDHash,
		Email:            account.Email,
		Name:             account.Name,
		LastActiveAt:     account.LastActiveAt,
		PendingReason:    pendingReason,
		MovedToPendingAt: currentTimestamp(),
	}
}

func upsertPendingLoginAccount(accounts []pendingLoginAccount, nextAccount pendingLoginAccount) []pendingLoginAccount {
	filteredAccounts := make([]pendingLoginAccount, 0, len(accounts)+1)
	for _, account := range accounts {
		if account.Label == nextAccount.Label || account.AccountIDHash == nextAccount.AccountIDHash {
			continue
		}
		filteredAccounts = append(filteredAccounts, account)
	}
	return append(filteredAccounts, nextAccount)
}

func pendingLoginAccountForImport(accounts []pendingLoginAccount, label string, accountIDHash string) (int, pendingLoginAccount, error) {
	matchingLabelIndex := -1
	matchingHashIndex := -1
	for index, account := range accounts {
		if account.Label == label {
			matchingLabelIndex = index
		}
		if account.AccountIDHash == accountIDHash {
			matchingHashIndex = index
		}
	}
	if matchingLabelIndex >= 0 {
		account := accounts[matchingLabelIndex]
		if account.AccountIDHash != accountIDHash {
			return -1, pendingLoginAccount{}, fmt.Errorf(
				"imported auth does not belong to pending account %q: expected %s, got %s",
				account.Label,
				account.AccountIDHash,
				accountIDHash,
			)
		}
		return matchingLabelIndex, account, nil
	}
	if matchingHashIndex >= 0 {
		account := accounts[matchingHashIndex]
		return -1, pendingLoginAccount{}, fmt.Errorf(
			"imported auth belongs to pending account %q; use that exact label instead of %q",
			account.Label,
			label,
		)
	}
	return -1, pendingLoginAccount{}, nil
}

func readPendingLoginAccounts(stateDirectory string) ([]pendingLoginAccount, error) {
	pendingAccountsPath := filepath.Join(stateDirectory, pendingLoginAccountsFileName)
	fileInfo, err := os.Lstat(pendingAccountsPath)
	if errors.Is(err, os.ErrNotExist) {
		return []pendingLoginAccount{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("cannot stat pending login accounts: %w", err)
	}
	if !fileInfo.Mode().IsRegular() || fileInfo.Mode().Perm() != privateFileMode {
		return nil, fmt.Errorf("pending login accounts must be a regular file with permissions 0600: %s", pendingAccountsPath)
	}
	if fileInfo.Size() <= 0 || fileInfo.Size() > maximumAuthFileBytes {
		return nil, fmt.Errorf("pending login accounts file has invalid size %d: %s", fileInfo.Size(), pendingAccountsPath)
	}
	pendingAccountsBytes, err := os.ReadFile(pendingAccountsPath)
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(pendingAccountsBytes))
	decoder.DisallowUnknownFields()
	pendingAccounts := []pendingLoginAccount{}
	if err := decoder.Decode(&pendingAccounts); err != nil {
		return nil, fmt.Errorf("invalid pending login accounts JSON: %w", err)
	}
	if err := ensureJSONDocumentEnded(decoder); err != nil {
		return nil, fmt.Errorf("invalid pending login accounts JSON: %w", err)
	}
	return validatePendingLoginAccounts(pendingAccounts)
}

func validatePendingLoginAccounts(accounts []pendingLoginAccount) ([]pendingLoginAccount, error) {
	labels := map[string]struct{}{}
	hashes := map[string]struct{}{}
	for index := range accounts {
		account := &accounts[index]
		validatedLabel, err := validateAccountLabel(account.Label)
		if err != nil {
			return nil, fmt.Errorf("pending account label is invalid: %w", err)
		}
		account.Label = validatedLabel
		if err := validateAccountHash(account.AccountIDHash); err != nil {
			return nil, fmt.Errorf("pending account %q hash is invalid: %w", account.Label, err)
		}
		if strings.TrimSpace(account.PendingReason) == "" {
			return nil, fmt.Errorf("pending account %q pending_reason is empty", account.Label)
		}
		if _, exists := labels[account.Label]; exists {
			return nil, fmt.Errorf("duplicate pending account label: %q", account.Label)
		}
		if _, exists := hashes[account.AccountIDHash]; exists {
			return nil, fmt.Errorf("duplicate pending account hash: %s", account.AccountIDHash)
		}
		labels[account.Label] = struct{}{}
		hashes[account.AccountIDHash] = struct{}{}
		if strings.TrimSpace(account.LastActiveAt) != "" {
			validatedLastActiveAt, err := validateTimestamp(account.LastActiveAt)
			if err != nil {
				return nil, fmt.Errorf("pending account %q last_active_at is invalid: %w", account.Label, err)
			}
			account.LastActiveAt = validatedLastActiveAt
		}
		validatedMovedToPendingAt, err := validateTimestamp(account.MovedToPendingAt)
		if err != nil {
			return nil, fmt.Errorf("pending account %q moved_to_pending_at is invalid: %w", account.Label, err)
		}
		account.MovedToPendingAt = validatedMovedToPendingAt
	}
	return accounts, nil
}

func writePendingLoginAccountsAtomically(stateDirectory string, pendingAccounts []pendingLoginAccount) error {
	validatedPendingAccounts, err := validatePendingLoginAccounts(pendingAccounts)
	if err != nil {
		return err
	}
	pendingAccountsBytes, err := json.MarshalIndent(validatedPendingAccounts, "", "  ")
	if err != nil {
		return err
	}
	pendingAccountsBytes = append(pendingAccountsBytes, '\n')

	temporaryPendingAccountsFile, err := os.CreateTemp(stateDirectory, ".pending-login-accounts-*.tmp")
	if err != nil {
		return err
	}
	temporaryPendingAccountsPath := temporaryPendingAccountsFile.Name()
	removeTemporaryPendingAccounts := true
	defer func() {
		if removeTemporaryPendingAccounts {
			_ = os.Remove(temporaryPendingAccountsPath)
		}
	}()

	if err := temporaryPendingAccountsFile.Chmod(privateFileMode); err != nil {
		temporaryPendingAccountsFile.Close()
		return err
	}
	if _, err := temporaryPendingAccountsFile.Write(pendingAccountsBytes); err != nil {
		temporaryPendingAccountsFile.Close()
		return err
	}
	if err := temporaryPendingAccountsFile.Sync(); err != nil {
		temporaryPendingAccountsFile.Close()
		return err
	}
	if err := temporaryPendingAccountsFile.Close(); err != nil {
		return err
	}

	pendingAccountsPath := filepath.Join(stateDirectory, pendingLoginAccountsFileName)
	if err := os.Rename(temporaryPendingAccountsPath, pendingAccountsPath); err != nil {
		return err
	}
	removeTemporaryPendingAccounts = false
	return syncDirectory(stateDirectory)
}

func backupStateFile(stateDirectory string, reason string) (string, error) {
	statePath := filepath.Join(stateDirectory, stateFileName)
	backupPath := statePath + "." + sanitizeAccountLabelForPath(reason) + "-bak-" + timestampForPath()

	sourceFile, err := os.Open(statePath)
	if err != nil {
		return "", fmt.Errorf("cannot open account switcher state for backup: %w", err)
	}
	defer sourceFile.Close()

	backupFile, err := os.OpenFile(backupPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, privateFileMode)
	if err != nil {
		return "", fmt.Errorf("cannot create account switcher state backup: %w", err)
	}
	removeBackup := true
	defer func() {
		if removeBackup {
			_ = os.Remove(backupPath)
		}
	}()

	if _, err := io.Copy(backupFile, sourceFile); err != nil {
		backupFile.Close()
		return "", fmt.Errorf("cannot write account switcher state backup: %w", err)
	}
	if err := backupFile.Sync(); err != nil {
		backupFile.Close()
		return "", fmt.Errorf("cannot sync account switcher state backup: %w", err)
	}
	if err := backupFile.Close(); err != nil {
		return "", fmt.Errorf("cannot close account switcher state backup: %w", err)
	}
	if err := syncDirectory(stateDirectory); err != nil {
		return "", err
	}
	removeBackup = false
	return backupPath, nil
}

func loadAuthIdentity(authPath string, label string) (accountIdentity, error) {
	fileInfo, err := os.Lstat(authPath)
	if err != nil {
		return accountIdentity{}, fmt.Errorf("cannot stat auth file %s: %w", authPath, err)
	}
	if !fileInfo.Mode().IsRegular() {
		return accountIdentity{}, fmt.Errorf("auth path is not a regular file: %s", authPath)
	}
	if fileInfo.Mode().Perm() != privateFileMode {
		return accountIdentity{}, fmt.Errorf("auth file permissions must be 0600, got %04o: %s", fileInfo.Mode().Perm(), authPath)
	}
	if fileInfo.Size() <= 0 || fileInfo.Size() > maximumAuthFileBytes {
		return accountIdentity{}, fmt.Errorf("auth file has invalid size %d: %s", fileInfo.Size(), authPath)
	}

	authFile, err := os.Open(authPath)
	if err != nil {
		return accountIdentity{}, err
	}
	defer authFile.Close()

	authPayload := authFilePayload{}
	decoder := json.NewDecoder(io.LimitReader(authFile, maximumAuthFileBytes+1))
	if err := decoder.Decode(&authPayload); err != nil {
		return accountIdentity{}, fmt.Errorf("invalid auth JSON: %w", err)
	}
	if err := ensureJSONDocumentEnded(decoder); err != nil {
		return accountIdentity{}, fmt.Errorf("invalid auth JSON: %w", err)
	}
	if authPayload.AuthMode != "chatgpt" {
		return accountIdentity{}, fmt.Errorf("unsupported auth_mode %q; expected chatgpt", authPayload.AuthMode)
	}
	if strings.TrimSpace(authPayload.Tokens.AccountID) == "" {
		return accountIdentity{}, errors.New("auth tokens.account_id is empty")
	}
	if strings.TrimSpace(authPayload.Tokens.AccessToken) == "" {
		return accountIdentity{}, errors.New("auth tokens.access_token is empty")
	}
	if strings.TrimSpace(authPayload.Tokens.IDToken) == "" {
		return accountIdentity{}, errors.New("auth tokens.id_token is empty")
	}
	if strings.TrimSpace(authPayload.Tokens.RefreshToken) == "" {
		return accountIdentity{}, errors.New("auth tokens.refresh_token is empty")
	}

	accountIDHash := sha256.Sum256([]byte(authPayload.Tokens.AccountID))
	email, name, err := optionalIDTokenDisplayClaims(authPayload.Tokens.IDToken)
	if err != nil {
		return accountIdentity{}, err
	}
	return accountIdentity{
		Label:         label,
		AccountIDHash: hex.EncodeToString(accountIDHash[:]),
		Email:         email,
		Name:          name,
	}, nil
}

func optionalIDTokenDisplayClaims(idToken string) (string, string, error) {
	if strings.Count(idToken, ".") != 2 {
		return "", "", nil
	}
	parts := strings.Split(idToken, ".")
	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", "", fmt.Errorf("invalid id_token payload encoding: %w", err)
	}
	claims := struct {
		Email string `json:"email"`
		Name  string `json:"name"`
	}{}
	if err := json.Unmarshal(payloadBytes, &claims); err != nil {
		return "", "", fmt.Errorf("invalid id_token payload JSON: %w", err)
	}
	return strings.TrimSpace(claims.Email), strings.TrimSpace(claims.Name), nil
}

func ensureJSONDocumentEnded(decoder *json.Decoder) error {
	additionalValue := any(nil)
	err := decoder.Decode(&additionalValue)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err != nil {
		return err
	}
	return errors.New("JSON document contains more than one value")
}

func accountRecordFromIdentity(identity accountIdentity, authPath string, active bool) registeredAccount {
	account := registeredAccount{
		Label:         identity.Label,
		AccountIDHash: identity.AccountIDHash,
		Email:         identity.Email,
		Name:          identity.Name,
		AuthPath:      authPath,
		Active:        active,
	}
	if active {
		account.LastActiveAt = currentTimestamp()
	}
	return account
}

func verifyStateAuthFiles(state accountSwitcherState) (accountSwitcherState, error) {
	if state.SchemaVersion != accountStateSchemaVersion {
		return accountSwitcherState{}, fmt.Errorf("unsupported normalized state schema version: %d", state.SchemaVersion)
	}
	if strings.TrimSpace(state.SharedAuthPath) == "" {
		return accountSwitcherState{}, errors.New("account switcher state shared_auth_path is empty")
	}
	if len(state.Accounts) < 2 {
		return accountSwitcherState{}, errors.New("account switcher state must contain at least two accounts")
	}

	sharedAuthPath, err := absolutePath(state.SharedAuthPath, "shared_auth_path")
	if err != nil {
		return accountSwitcherState{}, err
	}
	state.SharedAuthPath = sharedAuthPath

	activeCount := 0
	labels := map[string]struct{}{}
	hashes := map[string]struct{}{}
	paths := map[string]struct{}{}
	for index := range state.Accounts {
		account := &state.Accounts[index]
		validatedLabel, err := validateAccountLabel(account.Label)
		if err != nil {
			return accountSwitcherState{}, fmt.Errorf("state account label is invalid: %w", err)
		}
		account.Label = validatedLabel
		if err := validateAccountHash(account.AccountIDHash); err != nil {
			return accountSwitcherState{}, fmt.Errorf("state account %q hash is invalid: %w", account.Label, err)
		}
		accountAuthPath, err := absolutePath(account.AuthPath, "account auth_path")
		if err != nil {
			return accountSwitcherState{}, err
		}
		account.AuthPath = accountAuthPath
		if strings.TrimSpace(account.LastActiveAt) != "" {
			validatedLastActiveAt, err := validateTimestamp(account.LastActiveAt)
			if err != nil {
				return accountSwitcherState{}, fmt.Errorf("state account %q last_active_at is invalid: %w", account.Label, err)
			}
			account.LastActiveAt = validatedLastActiveAt
		}

		if _, exists := labels[account.Label]; exists {
			return accountSwitcherState{}, fmt.Errorf("duplicate account label in state: %q", account.Label)
		}
		if _, exists := hashes[account.AccountIDHash]; exists {
			return accountSwitcherState{}, fmt.Errorf("duplicate account hash in state: %s", account.AccountIDHash)
		}
		if _, exists := paths[account.AuthPath]; exists {
			return accountSwitcherState{}, fmt.Errorf("duplicate account auth path in state: %s", account.AuthPath)
		}
		labels[account.Label] = struct{}{}
		hashes[account.AccountIDHash] = struct{}{}
		paths[account.AuthPath] = struct{}{}

		if account.Active {
			activeCount++
			if account.AuthPath != state.SharedAuthPath {
				return accountSwitcherState{}, fmt.Errorf("active account %q must point at shared_auth_path", account.Label)
			}
		} else if account.AuthPath == state.SharedAuthPath {
			return accountSwitcherState{}, fmt.Errorf("inactive account %q points at shared_auth_path", account.Label)
		}

		identity, err := loadAuthIdentity(account.AuthPath, account.Label)
		if err != nil {
			return accountSwitcherState{}, fmt.Errorf("auth verification failed for account %q: %w", account.Label, err)
		}
		if identity.AccountIDHash != account.AccountIDHash {
			return accountSwitcherState{}, fmt.Errorf("auth account mismatch for %q: expected %s, got %s", account.Label, account.AccountIDHash, identity.AccountIDHash)
		}
		account.Email = identity.Email
		account.Name = identity.Name
	}
	if activeCount != 1 {
		return accountSwitcherState{}, fmt.Errorf("account switcher state must contain exactly one active account, got %d", activeCount)
	}

	sortAccountsForStableOutput(state.Accounts)
	return state, nil
}

func verifyStateForCurrentLoginAdoption(state accountSwitcherState) (accountSwitcherState, int, error) {
	if state.SchemaVersion != accountStateSchemaVersion {
		return accountSwitcherState{}, -1, fmt.Errorf("unsupported normalized state schema version: %d", state.SchemaVersion)
	}
	if strings.TrimSpace(state.SharedAuthPath) == "" {
		return accountSwitcherState{}, -1, errors.New("account switcher state shared_auth_path is empty")
	}
	if len(state.Accounts) < 2 {
		return accountSwitcherState{}, -1, errors.New("account switcher state must contain at least two accounts")
	}

	sharedAuthPath, err := absolutePath(state.SharedAuthPath, "shared_auth_path")
	if err != nil {
		return accountSwitcherState{}, -1, err
	}
	state.SharedAuthPath = sharedAuthPath

	activeIndex := -1
	labels := map[string]struct{}{}
	hashes := map[string]struct{}{}
	paths := map[string]struct{}{}
	for index := range state.Accounts {
		account := &state.Accounts[index]
		validatedLabel, err := validateAccountLabel(account.Label)
		if err != nil {
			return accountSwitcherState{}, -1, fmt.Errorf("state account label is invalid: %w", err)
		}
		account.Label = validatedLabel
		if err := validateAccountHash(account.AccountIDHash); err != nil {
			return accountSwitcherState{}, -1, fmt.Errorf("state account %q hash is invalid: %w", account.Label, err)
		}
		accountAuthPath, err := absolutePath(account.AuthPath, "account auth_path")
		if err != nil {
			return accountSwitcherState{}, -1, err
		}
		account.AuthPath = accountAuthPath
		if strings.TrimSpace(account.LastActiveAt) != "" {
			validatedLastActiveAt, err := validateTimestamp(account.LastActiveAt)
			if err != nil {
				return accountSwitcherState{}, -1, fmt.Errorf("state account %q last_active_at is invalid: %w", account.Label, err)
			}
			account.LastActiveAt = validatedLastActiveAt
		}

		if _, exists := labels[account.Label]; exists {
			return accountSwitcherState{}, -1, fmt.Errorf("duplicate account label in state: %q", account.Label)
		}
		if _, exists := hashes[account.AccountIDHash]; exists {
			return accountSwitcherState{}, -1, fmt.Errorf("duplicate account hash in state: %s", account.AccountIDHash)
		}
		if _, exists := paths[account.AuthPath]; exists {
			return accountSwitcherState{}, -1, fmt.Errorf("duplicate account auth path in state: %s", account.AuthPath)
		}
		labels[account.Label] = struct{}{}
		hashes[account.AccountIDHash] = struct{}{}
		paths[account.AuthPath] = struct{}{}

		if account.Active {
			if activeIndex != -1 {
				return accountSwitcherState{}, -1, errors.New("account switcher state must contain exactly one active account")
			}
			if account.AuthPath != state.SharedAuthPath {
				return accountSwitcherState{}, -1, fmt.Errorf("active account %q must point at shared_auth_path", account.Label)
			}
			activeIndex = index
			continue
		}
		if account.AuthPath == state.SharedAuthPath {
			return accountSwitcherState{}, -1, fmt.Errorf("inactive account %q points at shared_auth_path", account.Label)
		}

		identity, err := loadAuthIdentity(account.AuthPath, account.Label)
		if err != nil {
			return accountSwitcherState{}, -1, fmt.Errorf("auth verification failed for account %q: %w", account.Label, err)
		}
		if identity.AccountIDHash != account.AccountIDHash {
			return accountSwitcherState{}, -1, fmt.Errorf("auth account mismatch for inactive account %q: expected %s, got %s", account.Label, account.AccountIDHash, identity.AccountIDHash)
		}
		account.Email = identity.Email
		account.Name = identity.Name
	}
	if activeIndex == -1 {
		return accountSwitcherState{}, -1, errors.New("account switcher state must contain exactly one active account, got 0")
	}
	return state, activeIndex, nil
}

func validateAccountHash(hashValue string) error {
	if len(hashValue) != sha256.Size*2 {
		return fmt.Errorf("expected %d hex characters", sha256.Size*2)
	}
	if _, err := hex.DecodeString(hashValue); err != nil {
		return err
	}
	return nil
}

func findAccountByLabel(state accountSwitcherState, label string) (int, bool) {
	for index, account := range state.Accounts {
		if account.Label == label {
			return index, true
		}
	}
	return -1, false
}

func findAccountByHash(state accountSwitcherState, hashValue string) (int, bool) {
	for index, account := range state.Accounts {
		if account.AccountIDHash == hashValue {
			return index, true
		}
	}
	return -1, false
}

func activeAccountIndex(state accountSwitcherState) (int, error) {
	activeIndex := -1
	for index, account := range state.Accounts {
		if account.Active {
			if activeIndex != -1 {
				return -1, errors.New("more than one active account exists in state")
			}
			activeIndex = index
		}
	}
	if activeIndex == -1 {
		return -1, errors.New("no active account exists in state")
	}
	return activeIndex, nil
}

func sortAccountsForStableOutput(accounts []registeredAccount) {
	sort.SliceStable(accounts, func(leftIndex int, rightIndex int) bool {
		left := accounts[leftIndex]
		right := accounts[rightIndex]
		if left.Active != right.Active {
			return left.Active
		}
		return strings.ToLower(left.Label) < strings.ToLower(right.Label)
	})
}

func sortPendingLoginAccountsForStableOutput(accounts []pendingLoginAccount) {
	sort.SliceStable(accounts, func(leftIndex int, rightIndex int) bool {
		left := accounts[leftIndex]
		right := accounts[rightIndex]
		return strings.ToLower(left.Label) < strings.ToLower(right.Label)
	})
}

func accountDisplayName(label string, email string, name string, hashPrefix string) string {
	if strings.TrimSpace(email) != "" {
		return strings.TrimSpace(email)
	}
	if strings.TrimSpace(name) != "" {
		return strings.TrimSpace(name)
	}
	if strings.TrimSpace(label) != "" {
		return strings.TrimSpace(label)
	}
	return hashPrefix
}

func currentTimestamp() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func validateTimestamp(timestampValue string) (string, error) {
	parsedTimestamp, err := time.Parse(time.RFC3339, strings.TrimSpace(timestampValue))
	if err != nil {
		return "", err
	}
	return parsedTimestamp.UTC().Format(time.RFC3339), nil
}

func prepareStoredAuthDestination(stateDirectory string, identity accountIdentity) (string, error) {
	accountsDirectory := filepath.Join(stateDirectory, accountsDirectoryName)
	if err := ensurePrivateDirectory(accountsDirectory); err != nil {
		return "", err
	}
	accountDirectory := filepath.Join(accountsDirectory, accountDirectoryName(identity))
	if err := ensurePrivateDirectory(accountDirectory); err != nil {
		return "", err
	}
	storedAuthPath := filepath.Join(accountDirectory, authFileName)
	if err := requirePathDoesNotExist(storedAuthPath, "stored account auth"); err != nil {
		return "", err
	}
	return storedAuthPath, nil
}

func prepareUniqueStoredAuthDestination(stateDirectory string, identity accountIdentity) (string, error) {
	accountsDirectory := filepath.Join(stateDirectory, accountsDirectoryName)
	if err := ensurePrivateDirectory(accountsDirectory); err != nil {
		return "", err
	}
	accountDirectory := filepath.Join(accountsDirectory, accountDirectoryName(identity))
	accountAuthPath := filepath.Join(accountDirectory, authFileName)
	if _, err := os.Lstat(accountAuthPath); errors.Is(err, os.ErrNotExist) {
		if err := ensurePrivateDirectory(accountDirectory); err != nil {
			return "", err
		}
		return accountAuthPath, nil
	} else if err != nil {
		return "", fmt.Errorf("cannot stat stored auth destination: %w", err)
	}

	existingIdentity, err := loadAuthIdentity(accountAuthPath, identity.Label)
	if err == nil && existingIdentity.AccountIDHash == identity.AccountIDHash {
		return accountAuthPath, nil
	}

	timestampedAccountDirectory := accountDirectory + "-" + timestampForPath()
	if err := requirePathDoesNotExist(timestampedAccountDirectory, "timestamped stored auth directory"); err != nil {
		return "", err
	}
	if err := ensurePrivateDirectory(timestampedAccountDirectory); err != nil {
		return "", err
	}
	return filepath.Join(timestampedAccountDirectory, authFileName), nil
}

func accountDirectoryName(identity accountIdentity) string {
	sanitizedLabel := sanitizeAccountLabelForPath(identity.Label)
	return fmt.Sprintf("%s-%s", sanitizedLabel, identity.AccountIDHash[:accountHashPrefixLength])
}

func sanitizeAccountLabelForPath(label string) string {
	builder := strings.Builder{}
	for _, character := range strings.ToLower(label) {
		switch {
		case character >= 'a' && character <= 'z':
			builder.WriteRune(character)
		case character >= '0' && character <= '9':
			builder.WriteRune(character)
		case character == '-' || character == '_':
			builder.WriteRune(character)
		case unicode.IsSpace(character):
			builder.WriteRune('-')
		}
	}
	sanitized := strings.Trim(builder.String(), "-_")
	if sanitized == "" {
		return "account"
	}
	return sanitized
}

func moveImportedAuth(sourcePath string, destinationPath string) error {
	if err := os.Rename(sourcePath, destinationPath); err != nil {
		if errors.Is(err, unix.EXDEV) {
			if copyError := copyAuthFileToDestination(sourcePath, destinationPath); copyError != nil {
				return copyError
			}
			if removeError := os.Remove(sourcePath); removeError != nil {
				return rollbackCopiedAuthFile(destinationPath, fmt.Errorf("cannot remove imported auth after cross-device copy: %w", removeError))
			}
			if syncError := syncDirectory(filepath.Dir(sourcePath)); syncError != nil {
				return syncError
			}
			return nil
		}
		return fmt.Errorf("cannot move imported auth into the private vault: %w", err)
	}
	if err := syncDirectory(filepath.Dir(sourcePath)); err != nil {
		return rollbackImportedAuth(sourcePath, destinationPath, err)
	}
	if err := syncDirectory(filepath.Dir(destinationPath)); err != nil {
		return rollbackImportedAuth(sourcePath, destinationPath, err)
	}
	return nil
}

func exchangeAuthFiles(activeAuthPath string, inactiveAuthPath string) error {
	if err := unix.Renameat2(unix.AT_FDCWD, activeAuthPath, unix.AT_FDCWD, inactiveAuthPath, unix.RENAME_EXCHANGE); err != nil {
		return fmt.Errorf("atomic auth exchange failed: %w", err)
	}
	return nil
}

func verifyExchangedAuthFiles(previousState accountSwitcherState, targetIndex int) error {
	activeIndex, err := activeAccountIndex(previousState)
	if err != nil {
		return err
	}
	activeAccount := previousState.Accounts[activeIndex]
	targetAccount := previousState.Accounts[targetIndex]

	activeIdentity, err := loadAuthIdentity(previousState.SharedAuthPath, targetAccount.Label)
	if err != nil {
		return err
	}
	inactiveIdentity, err := loadAuthIdentity(targetAccount.AuthPath, activeAccount.Label)
	if err != nil {
		return err
	}
	if activeIdentity.AccountIDHash != targetAccount.AccountIDHash {
		return errors.New("active auth does not contain the expected target account after exchange")
	}
	if inactiveIdentity.AccountIDHash != activeAccount.AccountIDHash {
		return errors.New("inactive auth does not contain the previous active account after exchange")
	}
	return nil
}

func rollbackAuthExchange(previousState accountSwitcherState, targetIndex int, originalError error) error {
	targetAccount := previousState.Accounts[targetIndex]
	rollbackError := exchangeAuthFiles(previousState.SharedAuthPath, targetAccount.AuthPath)
	if rollbackError != nil {
		return errors.Join(originalError, fmt.Errorf("critical rollback failure: %w", rollbackError))
	}
	if syncError := syncDirectory(filepath.Dir(previousState.SharedAuthPath)); syncError != nil {
		return errors.Join(originalError, fmt.Errorf("critical rollback sync failure: %w", syncError))
	}
	if filepath.Dir(previousState.SharedAuthPath) != filepath.Dir(targetAccount.AuthPath) {
		if syncError := syncDirectory(filepath.Dir(targetAccount.AuthPath)); syncError != nil {
			return errors.Join(originalError, fmt.Errorf("critical rollback sync failure: %w", syncError))
		}
	}
	if _, verificationError := verifyStateAuthFiles(previousState); verificationError != nil {
		return errors.Join(originalError, fmt.Errorf("critical rollback verification failure: %w", verificationError))
	}
	return originalError
}

func rollbackImportedAuth(originalPath string, destinationPath string, originalError error) error {
	rollbackError := os.Rename(destinationPath, originalPath)
	if rollbackError != nil {
		return errors.Join(originalError, fmt.Errorf("critical imported-auth rollback failure: %w", rollbackError))
	}
	if syncError := syncDirectory(filepath.Dir(originalPath)); syncError != nil {
		return errors.Join(originalError, fmt.Errorf("critical imported-auth rollback sync failure: %w", syncError))
	}
	if filepath.Dir(originalPath) != filepath.Dir(destinationPath) {
		if syncError := syncDirectory(filepath.Dir(destinationPath)); syncError != nil {
			return errors.Join(originalError, fmt.Errorf("critical imported-auth rollback sync failure: %w", syncError))
		}
	}
	return originalError
}

func rollbackAccountImport(
	stateDirectory string,
	previousState accountSwitcherState,
	previousPendingLoginAccounts []pendingLoginAccount,
	importedAuthOriginalPath string,
	importedAuthStoredPath string,
	authWasMoved bool,
	originalError error,
) error {
	rollbackError := originalError
	if err := writeStateAtomically(stateDirectory, previousState); err != nil {
		rollbackError = errors.Join(rollbackError, fmt.Errorf("critical account-import state rollback failure: %w", err))
	}
	if err := writePendingLoginAccountsAtomically(stateDirectory, previousPendingLoginAccounts); err != nil {
		rollbackError = errors.Join(rollbackError, fmt.Errorf("critical account-import pending rollback failure: %w", err))
	}
	if authWasMoved {
		rollbackError = rollbackImportedAuth(importedAuthOriginalPath, importedAuthStoredPath, rollbackError)
	}
	return rollbackError
}

func storedAuthPathForPreviousActiveAccount(stateDirectory string, state accountSwitcherState, previousActiveAccount registeredAccount) (string, string, error) {
	registeredAuthPaths := map[string]struct{}{}
	for _, account := range state.Accounts {
		registeredAuthPaths[account.AuthPath] = struct{}{}
	}

	candidatePaths, err := previousActiveAuthCandidatePaths(stateDirectory)
	if err != nil {
		return "", "", err
	}
	for _, candidatePath := range candidatePaths {
		if candidatePath == state.SharedAuthPath {
			continue
		}
		if _, registered := registeredAuthPaths[candidatePath]; registered {
			continue
		}
		identity, err := loadAuthIdentity(candidatePath, previousActiveAccount.Label)
		if err != nil {
			continue
		}
		if identity.AccountIDHash != previousActiveAccount.AccountIDHash {
			continue
		}
		if pathIsInsideDirectory(candidatePath, stateDirectory) {
			return candidatePath, "", nil
		}

		destinationIdentity := identity
		destinationIdentity.Label = previousActiveAccount.Label
		storedAuthDestination, err := prepareUniqueStoredAuthDestination(stateDirectory, destinationIdentity)
		if err != nil {
			return "", "", err
		}
		if _, err := os.Lstat(storedAuthDestination); err == nil {
			return storedAuthDestination, "", nil
		} else if !errors.Is(err, os.ErrNotExist) {
			return "", "", fmt.Errorf("cannot stat preserved auth destination: %w", err)
		}
		if err := copyAuthFileToDestination(candidatePath, storedAuthDestination); err != nil {
			return "", "", err
		}
		return storedAuthDestination, storedAuthDestination, nil
	}
	return "", "", fmt.Errorf("%w: cannot preserve previous active account %q; no matching stored auth.json was found for hash %s outside %s", errPreviousActiveAuthNotFound, previousActiveAccount.Label, previousActiveAccount.AccountIDHash, state.SharedAuthPath)
}

func previousActiveAuthCandidatePaths(stateDirectory string) ([]string, error) {
	candidates := []string{}
	if err := filepath.WalkDir(stateDirectory, func(pathValue string, directoryEntry os.DirEntry, walkError error) error {
		if walkError != nil {
			return walkError
		}
		if directoryEntry.IsDir() || directoryEntry.Name() != authFileName {
			return nil
		}
		absoluteCandidatePath, err := absolutePath(pathValue, "candidate auth")
		if err != nil {
			return err
		}
		candidates = append(candidates, absoluteCandidatePath)
		return nil
	}); err != nil {
		return nil, fmt.Errorf("cannot scan account switcher vault for previous active auth: %w", err)
	}

	homeDirectory, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("cannot resolve user home for login auth scan: %w", err)
	}
	homeEntries, err := os.ReadDir(homeDirectory)
	if err != nil {
		return nil, fmt.Errorf("cannot scan user home for login auths: %w", err)
	}
	for _, homeEntry := range homeEntries {
		if !homeEntry.IsDir() || !strings.HasPrefix(homeEntry.Name(), ".codex-login-account-") {
			continue
		}
		candidatePath := filepath.Join(homeDirectory, homeEntry.Name(), authFileName)
		if _, err := os.Lstat(candidatePath); err == nil {
			candidates = append(candidates, candidatePath)
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("cannot stat login auth candidate %s: %w", candidatePath, err)
		}
	}
	sort.Strings(candidates)
	return uniqueStrings(candidates), nil
}

func copyAuthFileToDestination(sourcePath string, destinationPath string) error {
	if sourcePath == destinationPath {
		return errors.New("source and destination auth paths are identical")
	}
	if err := requirePathDoesNotExist(destinationPath, "copied auth destination"); err != nil {
		return err
	}
	temporaryCopiedAuthPath, err := copyAuthToTemporaryFile(sourcePath, filepath.Dir(destinationPath))
	if err != nil {
		return err
	}
	removeTemporaryCopy := true
	defer func() {
		if removeTemporaryCopy {
			_ = os.Remove(temporaryCopiedAuthPath)
		}
	}()
	if err := os.Rename(temporaryCopiedAuthPath, destinationPath); err != nil {
		return fmt.Errorf("cannot install copied auth: %w", err)
	}
	removeTemporaryCopy = false
	if err := syncDirectory(filepath.Dir(destinationPath)); err != nil {
		return rollbackCopiedAuthFile(destinationPath, err)
	}
	return nil
}

func rollbackCopiedAuthFile(copiedAuthPath string, originalError error) error {
	if copiedAuthPath == "" {
		return originalError
	}
	if removeError := os.Remove(copiedAuthPath); removeError != nil && !errors.Is(removeError, os.ErrNotExist) {
		return errors.Join(originalError, fmt.Errorf("critical copied-auth rollback failure: %w", removeError))
	}
	if syncError := syncDirectory(filepath.Dir(copiedAuthPath)); syncError != nil {
		return errors.Join(originalError, fmt.Errorf("critical copied-auth rollback sync failure: %w", syncError))
	}
	return originalError
}

func archiveAuthFile(stateDirectory string, archiveDirectoryName string, account registeredAccount) (string, error) {
	archivePath, err := archiveAuthPath(stateDirectory, archiveDirectoryName, account)
	if err != nil {
		return "", err
	}
	if err := os.Rename(account.AuthPath, archivePath); err != nil {
		return "", fmt.Errorf("cannot archive auth for account %q: %w", account.Label, err)
	}
	if err := syncDirectory(filepath.Dir(account.AuthPath)); err != nil {
		return "", rollbackArchivedAuth(archivePath, account.AuthPath, err)
	}
	if filepath.Dir(account.AuthPath) != filepath.Dir(archivePath) {
		if err := syncDirectory(filepath.Dir(archivePath)); err != nil {
			return "", rollbackArchivedAuth(archivePath, account.AuthPath, err)
		}
	}
	return archivePath, nil
}

func archiveAuthPath(stateDirectory string, archiveDirectoryName string, account registeredAccount) (string, error) {
	archiveRootDirectory := filepath.Join(stateDirectory, archiveDirectoryName)
	if err := ensurePrivateDirectory(archiveRootDirectory); err != nil {
		return "", err
	}
	archiveDirectory := filepath.Join(
		archiveRootDirectory,
		fmt.Sprintf("%s-%s-%s", timestampForPath(), sanitizeAccountLabelForPath(account.Label), account.AccountIDHash[:accountHashPrefixLength]),
	)
	if err := ensurePrivateDirectory(archiveDirectory); err != nil {
		return "", err
	}
	archivePath := filepath.Join(archiveDirectory, authFileName)
	if err := requirePathDoesNotExist(archivePath, "archived auth"); err != nil {
		return "", err
	}
	return archivePath, nil
}

func rollbackArchivedAuth(archivePath string, originalPath string, originalError error) error {
	if rollbackError := os.Rename(archivePath, originalPath); rollbackError != nil {
		return errors.Join(originalError, fmt.Errorf("critical archived-auth rollback failure: %w", rollbackError))
	}
	if syncError := syncDirectory(filepath.Dir(originalPath)); syncError != nil {
		return errors.Join(originalError, fmt.Errorf("critical archived-auth rollback sync failure: %w", syncError))
	}
	if filepath.Dir(originalPath) != filepath.Dir(archivePath) {
		if syncError := syncDirectory(filepath.Dir(archivePath)); syncError != nil {
			return errors.Join(originalError, fmt.Errorf("critical archived-auth rollback sync failure: %w", syncError))
		}
	}
	return originalError
}

func replaceAuthFile(sourcePath string, destinationPath string, stateDirectory string, account registeredAccount) (string, error) {
	temporaryReplacementPath, err := copyAuthToTemporaryFile(sourcePath, filepath.Dir(destinationPath))
	if err != nil {
		return "", err
	}
	removeTemporaryReplacement := true
	defer func() {
		if removeTemporaryReplacement {
			_ = os.Remove(temporaryReplacementPath)
		}
	}()

	backupAuthPath, err := archiveAuthPath(stateDirectory, replacedAuthDirectoryName, account)
	if err != nil {
		return "", err
	}
	if err := os.Rename(destinationPath, backupAuthPath); err != nil {
		return "", fmt.Errorf("cannot archive current auth for account %q: %w", account.Label, err)
	}
	if err := os.Rename(temporaryReplacementPath, destinationPath); err != nil {
		return "", rollbackArchivedAuth(backupAuthPath, destinationPath, fmt.Errorf("cannot install replacement auth for account %q: %w", account.Label, err))
	}
	removeTemporaryReplacement = false

	if err := syncDirectory(filepath.Dir(destinationPath)); err != nil {
		return "", rollbackAuthReplacement(destinationPath, backupAuthPath, err)
	}
	if filepath.Dir(destinationPath) != filepath.Dir(backupAuthPath) {
		if err := syncDirectory(filepath.Dir(backupAuthPath)); err != nil {
			return "", rollbackAuthReplacement(destinationPath, backupAuthPath, err)
		}
	}
	return backupAuthPath, nil
}

func copyAuthToTemporaryFile(sourcePath string, destinationDirectory string) (string, error) {
	sourceFile, err := os.Open(sourcePath)
	if err != nil {
		return "", fmt.Errorf("cannot open replacement auth: %w", err)
	}
	defer sourceFile.Close()

	temporaryFile, err := os.CreateTemp(destinationDirectory, ".auth-replace-*.tmp")
	if err != nil {
		return "", err
	}
	temporaryPath := temporaryFile.Name()
	removeTemporaryFile := true
	defer func() {
		if removeTemporaryFile {
			_ = os.Remove(temporaryPath)
		}
	}()

	if err := temporaryFile.Chmod(privateFileMode); err != nil {
		temporaryFile.Close()
		return "", err
	}
	if _, err := io.Copy(temporaryFile, io.LimitReader(sourceFile, maximumAuthFileBytes+1)); err != nil {
		temporaryFile.Close()
		return "", err
	}
	if err := temporaryFile.Sync(); err != nil {
		temporaryFile.Close()
		return "", err
	}
	if err := temporaryFile.Close(); err != nil {
		return "", err
	}
	removeTemporaryFile = false
	return temporaryPath, nil
}

func rollbackAuthReplacement(destinationPath string, backupPath string, originalError error) error {
	failedReplacementPath := destinationPath + ".failed-replace-" + timestampForPath()
	if _, statError := os.Lstat(destinationPath); statError == nil {
		if renameError := os.Rename(destinationPath, failedReplacementPath); renameError != nil {
			return errors.Join(originalError, fmt.Errorf("critical replacement rollback could not move failed replacement aside: %w", renameError))
		}
	} else if !errors.Is(statError, os.ErrNotExist) {
		return errors.Join(originalError, fmt.Errorf("critical replacement rollback could not stat destination: %w", statError))
	}
	if renameError := os.Rename(backupPath, destinationPath); renameError != nil {
		return errors.Join(originalError, fmt.Errorf("critical replacement rollback could not restore backup: %w", renameError))
	}
	if syncError := syncDirectory(filepath.Dir(destinationPath)); syncError != nil {
		return errors.Join(originalError, fmt.Errorf("critical replacement rollback sync failure: %w", syncError))
	}
	if filepath.Dir(destinationPath) != filepath.Dir(backupPath) {
		if syncError := syncDirectory(filepath.Dir(backupPath)); syncError != nil {
			return errors.Join(originalError, fmt.Errorf("critical replacement rollback sync failure: %w", syncError))
		}
	}
	return originalError
}

func timestampForPath() string {
	return time.Now().UTC().Format("20060102T150405Z")
}

func ensureCodexAppServersAreStopped() error {
	processIDs, err := codexAppServerProcessIDs()
	if err != nil {
		return err
	}
	if len(processIDs) == 0 {
		return nil
	}
	processIDStrings := make([]string, 0, len(processIDs))
	for _, processID := range processIDs {
		processIDStrings = append(processIDStrings, strconv.Itoa(processID))
	}
	return fmt.Errorf("Codex app-server is running with PID(s) %s; use --live only if you will restart the extension host immediately after switching", strings.Join(processIDStrings, ", "))
}

func codexAppServerProcessIDs() ([]int, error) {
	processEntries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, fmt.Errorf("cannot inspect /proc: %w", err)
	}

	processIDs := []int{}
	for _, processEntry := range processEntries {
		processID, err := strconv.Atoi(processEntry.Name())
		if err != nil || processID == os.Getpid() {
			continue
		}
		commandLineBytes, err := os.ReadFile(filepath.Join("/proc", processEntry.Name(), "cmdline"))
		if errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("cannot inspect process %d: %w", processID, err)
		}
		arguments := splitNullTerminatedArguments(commandLineBytes)
		if isCodexAppServerCommand(arguments) {
			processIDs = append(processIDs, processID)
		}
	}
	sort.Ints(processIDs)
	return processIDs, nil
}

func splitNullTerminatedArguments(commandLineBytes []byte) []string {
	trimmedCommandLine := strings.TrimRight(string(commandLineBytes), "\x00")
	if trimmedCommandLine == "" {
		return nil
	}
	return strings.Split(trimmedCommandLine, "\x00")
}

func isCodexAppServerCommand(arguments []string) bool {
	if len(arguments) < 2 || filepath.Base(arguments[0]) != "codex" {
		return false
	}
	for _, argument := range arguments[1:] {
		if argument == "app-server" {
			return true
		}
	}
	return false
}

func validateAccountLabel(label string) (string, error) {
	trimmedLabel := strings.TrimSpace(label)
	if trimmedLabel == "" {
		return "", errors.New("label is empty")
	}
	if trimmedLabel != label {
		return "", errors.New("label must not contain leading or trailing whitespace")
	}
	if len([]rune(trimmedLabel)) > maximumAccountLabelRunes {
		return "", fmt.Errorf("label exceeds %d characters", maximumAccountLabelRunes)
	}
	for _, character := range trimmedLabel {
		if unicode.IsControl(character) {
			return "", errors.New("label contains a control character")
		}
	}
	return trimmedLabel, nil
}

func absolutePath(pathValue string, fieldName string) (string, error) {
	trimmedPath := strings.TrimSpace(pathValue)
	if trimmedPath == "" {
		return "", fmt.Errorf("%s is empty", fieldName)
	}
	absolutePathValue, err := filepath.Abs(trimmedPath)
	if err != nil {
		return "", fmt.Errorf("cannot resolve %s: %w", fieldName, err)
	}
	return filepath.Clean(absolutePathValue), nil
}

func pathIsInsideDirectory(pathValue string, directoryPath string) bool {
	relativePath, err := filepath.Rel(directoryPath, pathValue)
	if err != nil {
		return false
	}
	return relativePath != ".." && !strings.HasPrefix(relativePath, ".."+string(os.PathSeparator))
}

func uniqueStrings(values []string) []string {
	uniqueValues := []string{}
	seenValues := map[string]struct{}{}
	for _, value := range values {
		if _, exists := seenValues[value]; exists {
			continue
		}
		seenValues[value] = struct{}{}
		uniqueValues = append(uniqueValues, value)
	}
	return uniqueValues
}

func ensurePrivateDirectory(directoryPath string) error {
	if err := os.MkdirAll(directoryPath, privateDirectoryMode); err != nil {
		return err
	}
	return verifyPrivateDirectory(directoryPath)
}

func verifyPrivateDirectory(directoryPath string) error {
	directoryInfo, err := os.Lstat(directoryPath)
	if err != nil {
		return fmt.Errorf("cannot stat private state directory %s: %w", directoryPath, err)
	}
	if !directoryInfo.IsDir() || directoryInfo.Mode().Perm() != privateDirectoryMode {
		return fmt.Errorf("private state directory must be a directory with permissions 0700: %s", directoryPath)
	}
	return nil
}

func acquireExclusiveLock(stateDirectory string) (*os.File, error) {
	if err := verifyPrivateDirectory(stateDirectory); err != nil {
		return nil, err
	}
	lockPath := filepath.Join(stateDirectory, switchLockFileName)
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, privateFileMode)
	if err != nil {
		return nil, err
	}
	if err := unix.Flock(int(lockFile.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		lockFile.Close()
		return nil, fmt.Errorf("another account switch operation is running: %w", err)
	}
	return lockFile, nil
}

func releaseExclusiveLock(lockFile *os.File) {
	_ = unix.Flock(int(lockFile.Fd()), unix.LOCK_UN)
	_ = lockFile.Close()
}

func syncDirectory(directoryPath string) error {
	directory, err := os.Open(directoryPath)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func requirePathDoesNotExist(pathValue string, description string) error {
	_, err := os.Lstat(pathValue)
	if err == nil {
		return fmt.Errorf("%s already exists: %s", description, pathValue)
	}
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return fmt.Errorf("cannot inspect %s %s: %w", description, pathValue, err)
}

func printState(action string, state accountSwitcherState, stateDirectory string, printJSON bool) error {
	output, err := buildStateOutput(action, state, stateDirectory)
	if err != nil {
		return err
	}
	if printJSON {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(output)
	}

	fmt.Printf("action: %s\n", output.Action)
	fmt.Printf("accounts_count: %d\n", output.AccountsCount)
	fmt.Printf("active_account: %s\n", output.ActiveAccount)
	fmt.Printf("active_account_display_name: %s\n", output.ActiveAccountDisplayName)
	fmt.Printf("shared_codex_home: %s\n", output.SharedCodexHome)
	for _, account := range output.Accounts {
		statusMarker := "inactive"
		if account.Active {
			statusMarker = "active"
		}
		fmt.Printf("account: %s | %s | label=%s | %s | auth_modified_at=%s\n", statusMarker, account.DisplayName, account.Label, account.AccountIDHashShort, account.AuthModifiedAt)
	}
	for _, account := range output.PendingLoginAccounts {
		fmt.Printf("pending_login: %s | label=%s | %s | reason=%s\n", account.DisplayName, account.Label, account.AccountIDHashShort, account.PendingReason)
	}
	return nil
}

func buildStateOutput(action string, state accountSwitcherState, stateDirectory string) (stateOutput, error) {
	validatedStateDirectory, err := absolutePath(stateDirectory, "state-dir")
	if err != nil {
		return stateOutput{}, err
	}
	activeIndex, err := activeAccountIndex(state)
	if err != nil {
		return stateOutput{}, err
	}
	accounts := make([]accountStatusOutput, 0, len(state.Accounts))
	for _, account := range state.Accounts {
		accountAuthFileInfo, err := os.Lstat(account.AuthPath)
		if err != nil {
			return stateOutput{}, fmt.Errorf("cannot stat auth path for account %q: %w", account.Label, err)
		}
		hashPrefix := account.AccountIDHash[:accountHashPrefixLength]
		accounts = append(accounts, accountStatusOutput{
			Label:              account.Label,
			Active:             account.Active,
			AccountIDHash:      account.AccountIDHash,
			AccountIDHashShort: hashPrefix,
			DisplayName:        accountDisplayName(account.Label, account.Email, account.Name, hashPrefix),
			Email:              account.Email,
			Name:               account.Name,
			AuthPath:           account.AuthPath,
			LastActiveAt:       account.LastActiveAt,
			AuthModifiedAt:     accountAuthFileInfo.ModTime().UTC().Format(time.RFC3339),
		})
	}
	pendingLoginAccounts, err := buildPendingLoginAccountOutputs(validatedStateDirectory, state)
	if err != nil {
		return stateOutput{}, err
	}
	activeAccount := state.Accounts[activeIndex]
	activeHashPrefix := activeAccount.AccountIDHash[:accountHashPrefixLength]
	return stateOutput{
		Action:                    action,
		AccountsCount:             len(state.Accounts),
		PendingLoginAccountsCount: len(pendingLoginAccounts),
		TotalAccountsCount:        len(state.Accounts) + len(pendingLoginAccounts),
		ActiveAccount:             activeAccount.Label,
		ActiveAccountDisplayName:  accountDisplayName(activeAccount.Label, activeAccount.Email, activeAccount.Name, activeHashPrefix),
		SharedCodexHome:           filepath.Dir(state.SharedAuthPath),
		SharedAuthPath:            state.SharedAuthPath,
		Accounts:                  accounts,
		PendingLoginAccounts:      pendingLoginAccounts,
	}, nil
}

func buildPendingLoginAccountOutputs(stateDirectory string, state accountSwitcherState) ([]pendingLoginAccountStatusOutput, error) {
	pendingAccounts, err := readPendingLoginAccounts(stateDirectory)
	if err != nil {
		return nil, err
	}
	registeredLabels := map[string]struct{}{}
	registeredHashes := map[string]struct{}{}
	for _, account := range state.Accounts {
		registeredLabels[account.Label] = struct{}{}
		registeredHashes[account.AccountIDHash] = struct{}{}
	}
	outputs := make([]pendingLoginAccountStatusOutput, 0, len(pendingAccounts))
	for _, account := range pendingAccounts {
		if _, exists := registeredLabels[account.Label]; exists {
			return nil, fmt.Errorf("pending account label %q already exists as registered account", account.Label)
		}
		if _, exists := registeredHashes[account.AccountIDHash]; exists {
			return nil, fmt.Errorf("pending account hash %s already exists as registered account", account.AccountIDHash)
		}
		hashPrefix := account.AccountIDHash[:accountHashPrefixLength]
		outputs = append(outputs, pendingLoginAccountStatusOutput{
			Label:              account.Label,
			AccountIDHash:      account.AccountIDHash,
			AccountIDHashShort: hashPrefix,
			DisplayName:        accountDisplayName(account.Label, account.Email, account.Name, hashPrefix),
			Email:              account.Email,
			Name:               account.Name,
			LastActiveAt:       account.LastActiveAt,
			PendingReason:      account.PendingReason,
			MovedToPendingAt:   account.MovedToPendingAt,
		})
	}
	return outputs, nil
}
