package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestRegisterAddSwitchAndSwitchBack(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	thirdLoginHome := filepath.Join(temporaryDirectory, "third-login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)
	createPrivateDirectoryForTest(t, thirdLoginHome)

	activeAuthPath := filepath.Join(codexHome, "auth.json")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	thirdSourcePath := filepath.Join(thirdLoginHome, "auth.json")
	writeAuthFileForTest(t, activeAuthPath, "account-a")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	writeAuthFileForTest(t, thirdSourcePath, "account-c")

	registeredState, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory)
	if err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}
	assertActiveLabelForTest(t, registeredState, "Primary")
	assertAccountCountForTest(t, registeredState, 2)
	assertLastActiveRecordedForTest(t, registeredState, "Primary")
	if _, err := os.Lstat(inactiveSourcePath); !os.IsNotExist(err) {
		t.Fatalf("inactive source auth still exists after registration: %s", inactiveSourcePath)
	}

	addedState, err := addAccount("Third", thirdSourcePath, stateDirectory)
	if err != nil {
		t.Fatalf("addAccount failed: %v", err)
	}
	assertActiveLabelForTest(t, addedState, "Primary")
	assertAccountCountForTest(t, addedState, 3)
	if _, err := os.Lstat(thirdSourcePath); !os.IsNotExist(err) {
		t.Fatalf("third source auth still exists after add: %s", thirdSourcePath)
	}

	switchedState, err := switchAccounts("Third", stateDirectory, skipAppServerProcessCheck)
	if err != nil {
		t.Fatalf("switchAccounts failed: %v", err)
	}
	assertAuthAccountForTest(t, activeAuthPath, "account-c")
	assertActiveLabelForTest(t, switchedState, "Third")
	assertLastActiveRecordedForTest(t, switchedState, "Third")

	restoredState, err := switchAccounts("Primary", stateDirectory, skipAppServerProcessCheck)
	if err != nil {
		t.Fatalf("switch back failed: %v", err)
	}
	assertAuthAccountForTest(t, activeAuthPath, "account-a")
	assertActiveLabelForTest(t, restoredState, "Primary")
	assertAccountCountForTest(t, restoredState, 3)
	assertLastActiveRecordedForTest(t, restoredState, "Primary")
}

func TestRegisterRejectsSameAccount(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)

	writeAuthFileForTest(t, filepath.Join(codexHome, "auth.json"), "same-account")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, inactiveSourcePath, "same-account")

	_, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory)
	if err == nil {
		t.Fatal("registerAccounts accepted two auth files for the same account")
	}
}

func TestAddRejectsExistingAccountHash(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	duplicateLoginHome := filepath.Join(temporaryDirectory, "duplicate-login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)
	createPrivateDirectoryForTest(t, duplicateLoginHome)

	writeAuthFileForTest(t, filepath.Join(codexHome, "auth.json"), "account-a")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	duplicateSourcePath := filepath.Join(duplicateLoginHome, "auth.json")
	writeAuthFileForTest(t, duplicateSourcePath, "account-b")
	if _, err := addAccount("Duplicate", duplicateSourcePath, stateDirectory); err == nil {
		t.Fatal("addAccount accepted an already registered account")
	}
}

func TestAddUsesUniqueDestinationWhenCanonicalPathContainsAnotherAuth(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	thirdLoginHome := filepath.Join(temporaryDirectory, "third-login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)
	createPrivateDirectoryForTest(t, thirdLoginHome)

	writeAuthFileForTest(t, filepath.Join(codexHome, "auth.json"), "account-a")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	thirdSourcePath := filepath.Join(thirdLoginHome, "auth.json")
	writeAuthFileForTest(t, thirdSourcePath, "account-c")
	thirdIdentity, err := loadAuthIdentity(thirdSourcePath, "Third")
	if err != nil {
		t.Fatalf("cannot load third identity: %v", err)
	}
	canonicalThirdDirectory := filepath.Join(stateDirectory, accountsDirectoryName, accountDirectoryName(thirdIdentity))
	createPrivateDirectoryForTest(t, canonicalThirdDirectory)
	canonicalThirdAuthPath := filepath.Join(canonicalThirdDirectory, authFileName)
	writeAuthFileForTest(t, canonicalThirdAuthPath, "stale-account")

	addedState, err := addAccount("Third", thirdSourcePath, stateDirectory)
	if err != nil {
		t.Fatalf("addAccount failed: %v", err)
	}
	thirdIndex, exists := findAccountByLabel(addedState, "Third")
	if !exists {
		t.Fatal("Third account was not registered")
	}
	if addedState.Accounts[thirdIndex].AuthPath == canonicalThirdAuthPath {
		t.Fatal("addAccount reused a canonical path that belonged to another auth")
	}
	assertAuthAccountForTest(t, addedState.Accounts[thirdIndex].AuthPath, "account-c")
	assertAuthAccountForTest(t, canonicalThirdAuthPath, "stale-account")
}

func TestSwitchRejectsUnknownTarget(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)

	writeAuthFileForTest(t, filepath.Join(codexHome, "auth.json"), "account-a")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	if _, err := switchAccounts("Unknown", stateDirectory, skipAppServerProcessCheck); err == nil {
		t.Fatal("switchAccounts accepted an unknown target account")
	}
	assertAuthAccountForTest(t, filepath.Join(codexHome, "auth.json"), "account-a")
}

func TestRenameRemoveAndReplaceAuth(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	thirdLoginHome := filepath.Join(temporaryDirectory, "third-login-home")
	replacementLoginHome := filepath.Join(temporaryDirectory, "replacement-login-home")
	wrongReplacementLoginHome := filepath.Join(temporaryDirectory, "wrong-replacement-login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)
	createPrivateDirectoryForTest(t, thirdLoginHome)
	createPrivateDirectoryForTest(t, replacementLoginHome)
	createPrivateDirectoryForTest(t, wrongReplacementLoginHome)

	activeAuthPath := filepath.Join(codexHome, "auth.json")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	thirdSourcePath := filepath.Join(thirdLoginHome, "auth.json")
	replacementAuthPath := filepath.Join(replacementLoginHome, "auth.json")
	wrongReplacementAuthPath := filepath.Join(wrongReplacementLoginHome, "auth.json")
	writeAuthFileForTest(t, activeAuthPath, "account-a")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	writeAuthFileForTest(t, thirdSourcePath, "account-c")
	writeAuthFileForTest(t, replacementAuthPath, "account-c")
	writeAuthFileForTest(t, wrongReplacementAuthPath, "account-d")

	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}
	addedState, err := addAccount("Third", thirdSourcePath, stateDirectory)
	if err != nil {
		t.Fatalf("addAccount failed: %v", err)
	}
	secondaryIndex, exists := findAccountByLabel(addedState, "Secondary")
	if !exists {
		t.Fatal("Secondary account was not registered")
	}
	secondaryAuthPath := addedState.Accounts[secondaryIndex].AuthPath

	renamedState, err := renameAccount("Third", "Account 3", stateDirectory)
	if err != nil {
		t.Fatalf("renameAccount failed: %v", err)
	}
	if _, exists := findAccountByLabel(renamedState, "Third"); exists {
		t.Fatal("old account label still exists after rename")
	}
	if _, exists := findAccountByLabel(renamedState, "Account 3"); !exists {
		t.Fatal("new account label does not exist after rename")
	}
	if _, err := renameAccount("Account 3", "Primary", stateDirectory); err == nil {
		t.Fatal("renameAccount accepted a duplicate target label")
	}

	if _, err := removeAccount("Primary", stateDirectory); err == nil {
		t.Fatal("removeAccount accepted the active account")
	}
	removedState, err := removeAccount("Secondary", stateDirectory)
	if err != nil {
		t.Fatalf("removeAccount failed: %v", err)
	}
	assertAccountCountForTest(t, removedState, 2)
	if _, exists := findAccountByLabel(removedState, "Secondary"); exists {
		t.Fatal("removed account label still exists")
	}
	if _, err := os.Lstat(secondaryAuthPath); !os.IsNotExist(err) {
		t.Fatalf("removed account auth still exists at original path: %s", secondaryAuthPath)
	}

	if _, err := replaceAccountAuth("Account 3", wrongReplacementAuthPath, stateDirectory, skipAppServerProcessCheck); err == nil {
		t.Fatal("replaceAccountAuth accepted auth for a different account")
	}
	replacedState, err := replaceAccountAuth("Account 3", replacementAuthPath, stateDirectory, skipAppServerProcessCheck)
	if err != nil {
		t.Fatalf("replaceAccountAuth failed: %v", err)
	}
	accountIndex, exists := findAccountByLabel(replacedState, "Account 3")
	if !exists {
		t.Fatal("Account 3 was not found after auth replacement")
	}
	assertAuthAccountForTest(t, replacedState.Accounts[accountIndex].AuthPath, "account-c")
	assertActiveLabelForTest(t, replacedState, "Primary")
}

func TestAdoptCurrentLoginAfterManualLogin(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)

	activeAuthPath := filepath.Join(codexHome, "auth.json")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, activeAuthPath, "account-a")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	preservedActiveDirectory := filepath.Join(stateDirectory, accountsDirectoryName, "primary-preserved")
	createPrivateDirectoryForTest(t, preservedActiveDirectory)
	preservedActiveAuthPath := filepath.Join(preservedActiveDirectory, authFileName)
	writeAuthFileForTest(t, preservedActiveAuthPath, "account-a")

	writeAuthFileForTest(t, activeAuthPath, "account-c")
	if _, err := loadAndVerifyState(stateDirectory); err == nil {
		t.Fatal("loadAndVerifyState accepted a manually replaced active auth")
	}

	adoptedState, err := adoptCurrentLogin("Account 3", stateDirectory)
	if err != nil {
		t.Fatalf("adoptCurrentLogin failed: %v", err)
	}
	assertActiveLabelForTest(t, adoptedState, "Account 3")
	assertAuthAccountForTest(t, activeAuthPath, "account-c")
	assertAccountCountForTest(t, adoptedState, 3)
	primaryIndex, exists := findAccountByLabel(adoptedState, "Primary")
	if !exists {
		t.Fatal("previous active account was deleted during adoption")
	}
	if adoptedState.Accounts[primaryIndex].Active {
		t.Fatal("previous active account is still marked active after adoption")
	}
	assertAuthAccountForTest(t, adoptedState.Accounts[primaryIndex].AuthPath, "account-a")
	if _, err := loadAndVerifyState(stateDirectory); err != nil {
		t.Fatalf("loadAndVerifyState failed after adoption: %v", err)
	}
}

func TestAdoptCurrentLoginMovesPreviousActiveToPendingWhenAuthIsMissing(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)

	activeAuthPath := filepath.Join(codexHome, "auth.json")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, activeAuthPath, "account-a")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	writeAuthFileForTest(t, activeAuthPath, "account-c")
	adoptedState, err := adoptCurrentLogin("Account 3", stateDirectory)
	if err != nil {
		t.Fatalf("adoptCurrentLogin failed: %v", err)
	}

	assertActiveLabelForTest(t, adoptedState, "Account 3")
	assertAccountCountForTest(t, adoptedState, 2)
	if _, exists := findAccountByLabel(adoptedState, "Primary"); exists {
		t.Fatal("previous active account stayed registered without auth")
	}
	pendingAccounts, err := readPendingLoginAccounts(stateDirectory)
	if err != nil {
		t.Fatalf("cannot read pending accounts after adoption: %v", err)
	}
	if len(pendingAccounts) != 1 {
		t.Fatalf("expected one pending account, got %d", len(pendingAccounts))
	}
	if pendingAccounts[0].Label != "Primary" {
		t.Fatalf("expected Primary pending account, got %q", pendingAccounts[0].Label)
	}
	output, err := buildStateOutput("test", adoptedState, stateDirectory)
	if err != nil {
		t.Fatalf("buildStateOutput failed: %v", err)
	}
	if output.TotalAccountsCount != 3 {
		t.Fatalf("expected total accounts count 3, got %d", output.TotalAccountsCount)
	}
	if output.PendingLoginAccountsCount != 1 {
		t.Fatalf("expected pending accounts count 1, got %d", output.PendingLoginAccountsCount)
	}
}

func TestAddRestoresPendingLoginAccountOnlyWithMatchingIdentity(t *testing.T) {
	temporaryDirectory := t.TempDir()
	codexHome := filepath.Join(temporaryDirectory, "codex-home")
	loginHome := filepath.Join(temporaryDirectory, "login-home")
	wrongReloginHome := filepath.Join(temporaryDirectory, "wrong-relogin-home")
	matchingReloginHome := filepath.Join(temporaryDirectory, "matching-relogin-home")
	stateDirectory := filepath.Join(temporaryDirectory, "state")
	createPrivateDirectoryForTest(t, codexHome)
	createPrivateDirectoryForTest(t, loginHome)
	createPrivateDirectoryForTest(t, wrongReloginHome)
	createPrivateDirectoryForTest(t, matchingReloginHome)

	activeAuthPath := filepath.Join(codexHome, "auth.json")
	inactiveSourcePath := filepath.Join(loginHome, "auth.json")
	writeAuthFileForTest(t, activeAuthPath, "account-a")
	writeAuthFileForTest(t, inactiveSourcePath, "account-b")
	if _, err := registerAccounts("Primary", "Secondary", inactiveSourcePath, codexHome, stateDirectory); err != nil {
		t.Fatalf("registerAccounts failed: %v", err)
	}

	writeAuthFileForTest(t, activeAuthPath, "account-c")
	if _, err := adoptCurrentLogin("Account 3", stateDirectory); err != nil {
		t.Fatalf("adoptCurrentLogin failed: %v", err)
	}

	wrongAuthPath := filepath.Join(wrongReloginHome, "auth.json")
	writeAuthFileForTest(t, wrongAuthPath, "account-d")
	if _, err := addAccount("Primary", wrongAuthPath, stateDirectory); err == nil {
		t.Fatal("addAccount restored a pending label with a different account identity")
	}
	if _, err := os.Lstat(wrongAuthPath); err != nil {
		t.Fatalf("wrong auth was moved despite rejected pending restore: %v", err)
	}
	pendingAccountsAfterRejection, err := readPendingLoginAccounts(stateDirectory)
	if err != nil {
		t.Fatalf("cannot read pending accounts after rejected restore: %v", err)
	}
	if len(pendingAccountsAfterRejection) != 1 || pendingAccountsAfterRejection[0].Label != "Primary" {
		t.Fatalf("pending account changed after rejected restore: %#v", pendingAccountsAfterRejection)
	}

	matchingAuthPath := filepath.Join(matchingReloginHome, "auth.json")
	writeAuthFileForTest(t, matchingAuthPath, "account-a")
	restoredState, err := addAccount("Primary", matchingAuthPath, stateDirectory)
	if err != nil {
		t.Fatalf("addAccount failed to restore pending account: %v", err)
	}
	assertAccountCountForTest(t, restoredState, 3)
	primaryIndex, exists := findAccountByLabel(restoredState, "Primary")
	if !exists {
		t.Fatal("restored pending account is missing from state")
	}
	if restoredState.Accounts[primaryIndex].Active {
		t.Fatal("restored pending account unexpectedly became active")
	}
	assertAuthAccountForTest(t, restoredState.Accounts[primaryIndex].AuthPath, "account-a")
	pendingAccountsAfterRestore, err := readPendingLoginAccounts(stateDirectory)
	if err != nil {
		t.Fatalf("cannot read pending accounts after restore: %v", err)
	}
	if len(pendingAccountsAfterRestore) != 0 {
		t.Fatalf("pending account was not removed after restore: %#v", pendingAccountsAfterRestore)
	}
	output, err := buildStateOutput("test", restoredState, stateDirectory)
	if err != nil {
		t.Fatalf("buildStateOutput failed after pending restore: %v", err)
	}
	if output.TotalAccountsCount != 3 || output.PendingLoginAccountsCount != 0 {
		t.Fatalf("unexpected output after pending restore: %#v", output)
	}
}

func createPrivateDirectoryForTest(t *testing.T, directoryPath string) {
	t.Helper()
	if err := os.MkdirAll(directoryPath, privateDirectoryMode); err != nil {
		t.Fatalf("cannot create test directory: %v", err)
	}
}

func writeAuthFileForTest(t *testing.T, authPath string, accountID string) {
	t.Helper()
	authPayload := authFilePayload{
		AuthMode: "chatgpt",
		Tokens: authTokens{
			AccessToken:  "access-" + accountID,
			AccountID:    accountID,
			IDToken:      "id-" + accountID,
			RefreshToken: "refresh-" + accountID,
		},
	}
	authBytes, err := json.Marshal(authPayload)
	if err != nil {
		t.Fatalf("cannot marshal test auth: %v", err)
	}
	if err := os.WriteFile(authPath, authBytes, privateFileMode); err != nil {
		t.Fatalf("cannot write test auth: %v", err)
	}
}

func assertAuthAccountForTest(t *testing.T, authPath string, expectedAccountID string) {
	t.Helper()
	authBytes, err := os.ReadFile(authPath)
	if err != nil {
		t.Fatalf("cannot read auth file: %v", err)
	}
	authPayload := authFilePayload{}
	if err := json.Unmarshal(authBytes, &authPayload); err != nil {
		t.Fatalf("cannot decode auth file: %v", err)
	}
	if authPayload.Tokens.AccountID != expectedAccountID {
		t.Fatalf("expected account %q, got %q", expectedAccountID, authPayload.Tokens.AccountID)
	}
}

func assertActiveLabelForTest(t *testing.T, state accountSwitcherState, expectedLabel string) {
	t.Helper()
	activeIndex, err := activeAccountIndex(state)
	if err != nil {
		t.Fatalf("cannot find active account: %v", err)
	}
	if state.Accounts[activeIndex].Label != expectedLabel {
		t.Fatalf("expected active account %q, got %q", expectedLabel, state.Accounts[activeIndex].Label)
	}
}

func assertAccountCountForTest(t *testing.T, state accountSwitcherState, expectedCount int) {
	t.Helper()
	if len(state.Accounts) != expectedCount {
		t.Fatalf("expected %d accounts, got %d", expectedCount, len(state.Accounts))
	}
}

func assertLastActiveRecordedForTest(t *testing.T, state accountSwitcherState, label string) {
	t.Helper()
	accountIndex, exists := findAccountByLabel(state, label)
	if !exists {
		t.Fatalf("account %q not found", label)
	}
	if state.Accounts[accountIndex].LastActiveAt == "" {
		t.Fatalf("expected account %q to have last_active_at", label)
	}
	if _, err := time.Parse(time.RFC3339, state.Accounts[accountIndex].LastActiveAt); err != nil {
		t.Fatalf("invalid last_active_at for account %q: %v", label, err)
	}
}
