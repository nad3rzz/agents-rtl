"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const vscode = require("vscode");
const {
  registerNativeRepositoryVisibilityController,
} = require("./native_repository_visibility_controller");

const EXECUTION_MAX_BUFFER_BYTES = 1024 * 1024;
const LOGIN_OUTPUT_TAIL_MAX_CHARACTERS = 4000;
const ACTIVE_ACCOUNT_MARK = "●";
const INACTIVE_ACCOUNT_MARK = "○";
const REFRESH_ACTION_TYPE = "refresh";
const ADOPT_CURRENT_LOGIN_ACTION = "Add/Activate Current Login";

let accountsStatusBarItem;
let accountLoginOutputChannel;
let accountLoginIsRunning = false;
let lastKnownStatus;
let lastRefreshTimeText = "not refreshed yet";

async function activate(context) {
  accountsStatusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 95);
  accountsStatusBarItem.command = "agentsRtlPersonal.openAccountsPanel";
  setStatusBarLoading();
  accountsStatusBarItem.show();
  accountLoginOutputChannel = vscode.window.createOutputChannel("Codex Account Login");

  context.subscriptions.push(
    accountsStatusBarItem,
    accountLoginOutputChannel,
    vscode.commands.registerCommand("agentsRtlPersonal.openAccountsPanel", () => openAccountsQuickPick(context)),
    vscode.commands.registerCommand("agentsRtlPersonal.refreshAccounts", () => refreshAccountsStatus(context, true))
  );

  await registerNativeRepositoryVisibilityController(context);
  refreshAccountsStatus(context, false);
}

function deactivate() {
  if (accountsStatusBarItem) {
    accountsStatusBarItem.dispose();
    accountsStatusBarItem = undefined;
  }
  accountLoginOutputChannel = undefined;
  accountLoginIsRunning = false;
}

async function openAccountsQuickPick(context) {
  let keepPickerOpen = true;
  while (keepPickerOpen) {
    let status;
    try {
      status = await refreshAccountsStatus(context, false);
    } catch (error) {
      await openAccountsRecoveryQuickPick(context, error);
      return;
    }
    const selectedItem = await vscode.window.showQuickPick(buildAccountQuickPickItems(status), {
      title: `Codex Accounts · refreshed ${lastRefreshTimeText}`,
      placeHolder: "Switch account or run an account action",
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (!selectedItem) {
      return;
    }
    keepPickerOpen = selectedItem.action && selectedItem.action.type === REFRESH_ACTION_TYPE;
    await runQuickPickAction(context, selectedItem.action);
  }
}

async function openAccountsRecoveryQuickPick(context, error) {
  const items = [];
  if (isAuthAccountMismatchError(error)) {
    items.push({
      label: "＋ Add/Activate Current Login",
      description: "Preserve the previous active account, then register or activate the current login",
      detail: errorMessage(error),
      action: { type: "adoptCurrentLogin" },
    });
  }
  items.push(
    {
      label: "↻ Refresh",
      description: "Reload account status",
      detail: errorMessage(error),
      action: { type: REFRESH_ACTION_TYPE },
    },
    {
      label: "＋ Login",
      description: "Log in with the browser and register the account automatically",
      action: { type: "automaticLogin" },
    }
  );

  const selectedItem = await vscode.window.showQuickPick(items, {
    title: "Codex Accounts needs attention",
    placeHolder: errorMessage(error),
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!selectedItem) {
    return;
  }
  await runQuickPickAction(context, selectedItem.action);
}

function buildAccountQuickPickItems(status) {
  const accountItems = status.accounts.map((account) => {
    const displayName = accountDisplayName(account);
    const lastActiveText = formatLastActive(account.last_active_at);
    const authUpdatedText = formatLastActive(account.auth_modified_at);
    const activeMarker = account.active ? ACTIVE_ACCOUNT_MARK : INACTIVE_ACCOUNT_MARK;
    return {
      label: `${activeMarker} ${displayName}`,
      description: account.active ? "Active" : "Ready",
      detail: `Label: ${account.label} · Last active: ${lastActiveText} · Auth updated: ${authUpdatedText} · ${account.auth_path}`,
      action: {
        type: account.active ? "noop" : "switch",
        label: account.label,
      },
    };
  });
  const pendingItems = pendingLoginAccounts(status).map((account) => ({
    label: `⚠ ${accountDisplayName(account)}`,
    description: "Needs login",
    detail: `Label: ${account.label} · ${account.pending_reason} · Last active: ${formatLastActive(account.last_active_at)}`,
    action: {
      type: "automaticLogin",
      label: account.label,
    },
  }));
  const pendingSection = pendingItems.length ? [
    {
      label: "Pending login",
      kind: vscode.QuickPickItemKind.Separator,
    },
    ...pendingItems,
  ] : [];

  return [
    ...accountItems,
    ...pendingSection,
    {
      label: "──────────",
      kind: vscode.QuickPickItemKind.Separator,
    },
    {
      label: "↻ Refresh",
      description: "Reload account status",
      detail: `Last refresh: ${lastRefreshTimeText}`,
      action: { type: REFRESH_ACTION_TYPE },
    },
    {
      label: "＋ Login",
      description: "Log in with the browser and register the account automatically",
      action: { type: "automaticLogin" },
    },
    {
      label: "✎ Rename",
      description: "Rename an account label",
      action: { type: "renameAccount" },
    },
    {
      label: "🗑 Remove",
      description: "Remove an inactive account from the list",
      action: { type: "removeAccount" },
    },
    {
      label: "↺ Re-login",
      description: "Refresh auth for an existing account",
      action: { type: "reloginAccount" },
    },
    {
      label: "↯ Restart Extension Host",
      description: "Apply the active Codex account to running agents",
      action: { type: "restartHost" },
    },
  ];
}

function formatLastActive(lastActiveAt) {
  if (!lastActiveAt) {
    return "not recorded yet";
  }
  const parsedDate = new Date(lastActiveAt);
  if (Number.isNaN(parsedDate.getTime())) {
    return lastActiveAt;
  }
  return parsedDate.toLocaleString();
}

function accountDisplayName(account) {
  return account.display_name || account.email || account.name || account.label || account.account_id_sha256_short;
}

function pendingLoginAccounts(status) {
  return Array.isArray(status.pending_login_accounts) ? status.pending_login_accounts : [];
}

function totalStatusAccountCount(status) {
  return typeof status.total_accounts_count === "number"
    ? status.total_accounts_count
    : status.accounts_count + pendingLoginAccounts(status).length;
}

async function runQuickPickAction(context, action) {
  if (!action || typeof action.type !== "string") {
    throw new Error("Invalid quick pick action.");
  }
  if (action.type === "noop") {
    return;
  }
  if (action.type === REFRESH_ACTION_TYPE) {
    await refreshAccountsStatus(context, true);
    return;
  }
  if (action.type === "switch") {
    await switchAccount(context, action.label);
    return;
  }
  if (action.type === "restartHost") {
    await vscode.commands.executeCommand("workbench.action.restartExtensionHost");
    return;
  }
  if (action.type === "automaticLogin") {
    await loginAndImportAccount(context, action.label);
    return;
  }
  if (action.type === "renameAccount") {
    await renameAccount(context);
    return;
  }
  if (action.type === "removeAccount") {
    await removeAccount(context);
    return;
  }
  if (action.type === "reloginAccount") {
    await reloginAccount(context);
    return;
  }
  if (action.type === "adoptCurrentLogin") {
    await adoptCurrentLogin(context);
    return;
  }
  throw new Error(`Unsupported quick pick action type: ${action.type}`);
}

async function refreshAccountsStatus(context, showMessage) {
  try {
    const status = await runSwitcherJSON(context, ["status", "--json"]);
    lastKnownStatus = status;
    lastRefreshTimeText = new Date().toLocaleTimeString();
    updateStatusBar(status);
    if (showMessage) {
      vscode.window.showInformationMessage(`Codex accounts refreshed: ${totalStatusAccountCount(status)}`);
    }
    return status;
  } catch (error) {
    setStatusBarError(error);
    throw error;
  }
}

function updateStatusBar(status) {
  if (!accountsStatusBarItem) {
    return;
  }
  const activeAccount = status.accounts.find((account) => account.active);
  const activeLabel = activeAccount ? accountDisplayName(activeAccount) : "No active account";
  const activeInternalLabel = activeAccount ? activeAccount.label : "none";
  accountsStatusBarItem.text = `$(account) ${activeLabel}`;
  accountsStatusBarItem.tooltip = `Codex Accounts\n${totalStatusAccountCount(status)} accounts\nActive label: ${activeInternalLabel}`;
}

function setStatusBarLoading() {
  if (!accountsStatusBarItem) {
    return;
  }
  accountsStatusBarItem.text = "$(account) Codex Accounts";
  accountsStatusBarItem.tooltip = "Open Codex account switcher";
}

function setStatusBarError(error) {
  if (!accountsStatusBarItem) {
    return;
  }
  accountsStatusBarItem.text = "$(warning) Codex Accounts";
  accountsStatusBarItem.tooltip = errorMessage(error);
}

async function switchAccount(context, label) {
  if (typeof label !== "string" || !label.trim()) {
    throw new Error("Missing target account label.");
  }
  const targetAccount = lastKnownStatus && Array.isArray(lastKnownStatus.accounts)
    ? lastKnownStatus.accounts.find((account) => account.label === label)
    : undefined;
  const targetDisplayName = targetAccount ? accountDisplayName(targetAccount) : label;
  const accepted = await vscode.window.showWarningMessage(
    `Switch Codex account to "${targetDisplayName}"?`,
    { modal: true },
    "Switch"
  );
  if (accepted !== "Switch") {
    return;
  }

  const status = await runSwitcherJSON(context, ["switch", "--to", label, "--live", "--json"]);
  lastKnownStatus = status;
  updateStatusBar(status);
  const restartAccepted = await vscode.window.showInformationMessage(
    "Codex account switched. Restart the extension host now?",
    { modal: true },
    "Restart Extension Host"
  );
  if (restartAccepted === "Restart Extension Host") {
    await vscode.commands.executeCommand("workbench.action.restartExtensionHost");
  }
}

async function loginAndImportAccount(context, preselectedLabel) {
  const label = preselectedLabel || await vscode.window.showInputBox({
    prompt: "New account label",
    placeHolder: nextDefaultAccountLabel(),
    validateInput: validateAdoptLabelInput,
  });
  if (!label) {
    return;
  }

  const loginResult = await runAutomaticBrowserLogin(context, label);
  try {
    const status = await runSwitcherJSON(context, ["add", "--label", label, "--auth", loginResult.authPath, "--json"]);
    lastKnownStatus = status;
    updateStatusBar(status);
    vscode.window.showInformationMessage(`Codex account is ready: ${accountDisplayName(status.accounts.find((account) => account.label === label) || { label })}`);
  } finally {
    removeTemporaryLoginHome(loginResult.loginHome);
  }
}

async function renameAccount(context) {
  const status = await refreshAccountsStatus(context, false);
  const account = await pickAccount(status, "Rename Codex account", status.accounts);
  if (!account) {
    return;
  }
  const newLabel = await vscode.window.showInputBox({
    prompt: "New account label",
    value: account.label,
    validateInput: (value) => validateRenameLabelInput(value, status, account.label),
  });
  if (!newLabel || newLabel === account.label) {
    return;
  }
  const accepted = await vscode.window.showWarningMessage(
    `Rename Codex account?\n\nFrom: ${account.label}\nTo: ${newLabel}`,
    { modal: true },
    "Rename"
  );
  if (accepted !== "Rename") {
    return;
  }
  const updatedStatus = await runSwitcherJSON(context, ["rename", "--from", account.label, "--to", newLabel, "--json"]);
  lastKnownStatus = updatedStatus;
  updateStatusBar(updatedStatus);
  vscode.window.showInformationMessage(`Renamed Codex account: ${account.label} → ${newLabel}`);
}

async function removeAccount(context) {
  const status = await refreshAccountsStatus(context, false);
  const removableAccounts = status.accounts.filter((account) => !account.active);
  const account = await pickAccount(status, "Remove inactive Codex account", removableAccounts);
  if (!account) {
    return;
  }
  const accepted = await vscode.window.showWarningMessage(
    `Remove Codex account "${accountDisplayName(account)}"?\n\nLabel: ${account.label}\n\nThe auth file will be archived, not destroyed.`,
    { modal: true },
    "Remove"
  );
  if (accepted !== "Remove") {
    return;
  }
  const updatedStatus = await runSwitcherJSON(context, ["remove", "--label", account.label, "--json"]);
  lastKnownStatus = updatedStatus;
  updateStatusBar(updatedStatus);
  vscode.window.showInformationMessage(`Removed Codex account: ${account.label}`);
}

async function reloginAccount(context) {
  const status = await refreshAccountsStatus(context, false);
  const account = await pickAccount(status, "Re-login Codex account", status.accounts);
  if (!account) {
    return;
  }
  const accepted = await vscode.window.showWarningMessage(
    `Re-login Codex account?\n\n${accountDisplayName(account)}\nLabel: ${account.label}\n\nThe browser login must use this same ChatGPT account.`,
    { modal: true },
    "Re-login"
  );
  if (accepted !== "Re-login") {
    return;
  }
  const loginResult = await runAutomaticBrowserLogin(context, account.label);
  try {
    const updatedStatus = await runSwitcherJSON(context, ["replace-auth", "--label", account.label, "--auth", loginResult.authPath, "--live", "--json"]);
    lastKnownStatus = updatedStatus;
    updateStatusBar(updatedStatus);
  } finally {
    removeTemporaryLoginHome(loginResult.loginHome);
  }
  if (account.active) {
    const restartAccepted = await vscode.window.showInformationMessage(
      "Active Codex auth replaced. Restart the extension host now?",
      { modal: true },
      "Restart Extension Host"
    );
    if (restartAccepted === "Restart Extension Host") {
      await vscode.commands.executeCommand("workbench.action.restartExtensionHost");
    }
    return;
  }
  vscode.window.showInformationMessage(`Auth replaced for Codex account: ${account.label}`);
}

async function adoptCurrentLogin(context) {
  const label = await vscode.window.showInputBox({
    prompt: "Label to use if the current Codex login is new",
    value: suggestedNextAccountLabelFromState(),
    validateInput: validateAdoptLabelInput,
  });
  if (!label) {
    return;
  }
  const accepted = await vscode.window.showWarningMessage(
    `Add or activate current Codex login?\n\nNew account label: ${label}\n\nThe previous active account must stay registered.`,
    { modal: true },
    ADOPT_CURRENT_LOGIN_ACTION
  );
  if (accepted !== ADOPT_CURRENT_LOGIN_ACTION) {
    return;
  }

  const status = await runSwitcherJSON(context, ["adopt-current-login", "--label", label, "--json"]);
  lastKnownStatus = status;
  lastRefreshTimeText = new Date().toLocaleTimeString();
  updateStatusBar(status);
  vscode.window.showInformationMessage(`Current Codex login is active: ${status.active_account}`);
}

async function pickAccount(status, title, accounts) {
  if (!accounts.length) {
    vscode.window.showInformationMessage("No matching Codex accounts.");
    return undefined;
  }
  const items = accounts.map((account) => ({
    label: accountDisplayName(account),
    description: account.active ? "Active" : "Ready",
    detail: `Label: ${account.label} · ${account.auth_path}`,
    account,
  }));
  const selectedItem = await vscode.window.showQuickPick(items, {
    title,
    placeHolder: `${status.accounts_count} registered accounts`,
    matchOnDescription: true,
    matchOnDetail: true,
  });
  return selectedItem && selectedItem.account;
}

function nextDefaultAccountLabel() {
  const labels = lastKnownStatus && Array.isArray(lastKnownStatus.accounts)
    ? lastKnownStatus.accounts.map((account) => account.label)
    : [];
  return nextGeneratedAccountLabel(labels);
}

function validateNonEmptyInput(value) {
  return value.trim() ? undefined : "Required.";
}

function validateRenameLabelInput(value, status, currentLabel) {
  const baseValidation = validateNonEmptyInput(value);
  if (baseValidation) {
    return baseValidation;
  }
  if (value !== value.trim()) {
    return "No leading or trailing spaces.";
  }
  if (value.length > 80) {
    return "Too long.";
  }
  if (value === currentLabel) {
    return undefined;
  }
  if (status.accounts.some((account) => account.label === value)) {
    return "Already used.";
  }
  return undefined;
}

function validateAdoptLabelInput(value) {
  const baseValidation = validateNonEmptyInput(value);
  if (baseValidation) {
    return baseValidation;
  }
  if (value !== value.trim()) {
    return "No leading or trailing spaces.";
  }
  if (value.length > 80) {
    return "Too long.";
  }
  try {
    if (readStateAccountLabels().includes(value)) {
      return "Already used.";
    }
  } catch (error) {
    return errorMessage(error);
  }
  return undefined;
}

function personalConfiguration() {
  return vscode.workspace.getConfiguration("agentsRtlPersonal");
}

async function runAutomaticBrowserLogin(context, label) {
  if (accountLoginIsRunning) {
    throw new Error("Another Codex account login is already running.");
  }
  if (!accountLoginOutputChannel) {
    throw new Error("Codex account login output channel is not initialized.");
  }

  accountLoginIsRunning = true;
  accountLoginOutputChannel.clear();
  accountLoginOutputChannel.appendLine(`Starting browser login for ${label}`);
  accountLoginOutputChannel.show(true);

  let loginHome;

  try {
	await recordAccountAuditEvent(context, "login", "started", label);
	loginHome = fs.mkdtempSync(path.join(os.tmpdir(), `agents-rtl-personal-${sanitizeLabelForPath(label)}-`));
	fs.chmodSync(loginHome, 0o700);
	accountLoginOutputChannel.appendLine(`Temporary CODEX_HOME: ${loginHome}`);
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Codex login · ${label}`,
        cancellable: false,
      },
      () => runCodexLoginProcess(loginHome)
    );
    const authPath = path.join(loginHome, "auth.json");
    if (!fs.existsSync(authPath)) {
      throw new Error(`Codex login succeeded without creating auth.json: ${authPath}`);
    }
	await recordAccountAuditEvent(context, "login", "success", label);
    return { loginHome, authPath };
  } catch (error) {
	let loginFailure = error;
	if (loginHome) {
	  try {
		removeTemporaryLoginHome(loginHome);
	  } catch (cleanupError) {
		loginFailure = new Error(`Codex login failed: ${errorMessage(error)}\nTemporary login cleanup also failed: ${errorMessage(cleanupError)}`);
	  }
	}
	await recordLoginFailureAndRethrow(context, label, loginFailure);
  } finally {
    accountLoginIsRunning = false;
  }
}

async function recordLoginFailureAndRethrow(context, label, loginError) {
  try {
	await recordAccountAuditEvent(context, "login", "failure", label);
  } catch (auditError) {
	throw new Error(`Codex login failed: ${errorMessage(loginError)}\nAudit logging also failed: ${errorMessage(auditError)}`);
  }
  throw loginError;
}

async function recordAccountAuditEvent(context, action, result, label) {
  const args = argsWithConfiguredStateDir(["record-event", "--action", action, "--result", result, "--label", label]);
  await runExecutable(resolveSwitcherPath(context), args);
}

function runCodexLoginProcess(loginHome) {
  return new Promise((resolve, reject) => {
    const loginProcess = childProcess.spawn("codex", ["login"], {
      cwd: os.homedir(),
      env: { ...process.env, CODEX_HOME: loginHome },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let loginOutputTail = "";
    let loginOutputByteCount = 0;
    let processFinished = false;

    const recordOutput = (chunk) => {
      const text = chunk.toString();
      accountLoginOutputChannel.append(text);
      loginOutputTail = `${loginOutputTail}${text}`.slice(-LOGIN_OUTPUT_TAIL_MAX_CHARACTERS);
      loginOutputByteCount += chunk.length;
      if (loginOutputByteCount > EXECUTION_MAX_BUFFER_BYTES) {
        loginProcess.kill();
      }
    };

    loginProcess.stdout.on("data", recordOutput);
    loginProcess.stderr.on("data", recordOutput);
    loginProcess.once("error", (error) => {
      if (processFinished) {
        return;
      }
      processFinished = true;
      reject(new Error(`Cannot start codex login: ${error.message}`));
    });
    loginProcess.once("close", (exitCode, signal) => {
      if (processFinished) {
        return;
      }
      processFinished = true;
      if (exitCode !== 0) {
        reject(new Error(`codex login failed with exit code ${exitCode} and signal ${signal || "none"}.\n${loginOutputTail}`.trim()));
        return;
      }
      resolve();
    });
  });
}

function removeTemporaryLoginHome(loginHome) {
  if (!fs.existsSync(loginHome)) {
    return;
  }
  fs.rmSync(loginHome, { recursive: true, force: false });
}

function suggestedNextAccountLabelFromState() {
  return nextGeneratedAccountLabel(readStateAccountLabels());
}

function nextGeneratedAccountLabel(labels) {
  const highestAccountNumber = labels.reduce((highest, label) => {
    const match = /^Account\s+(\d+)$/.exec(label);
    if (!match) {
      return highest;
    }
    return Math.max(highest, Number(match[1]));
  }, 0);
  return `Account ${highestAccountNumber + 1}`;
}

function readStateAccountLabels() {
  const statePath = path.join(configuredStateDir(), "state.json");
  const stateText = fs.readFileSync(statePath, "utf8");
  const state = JSON.parse(stateText);
  if (!Array.isArray(state.accounts)) {
    throw new Error(`Invalid account switcher state: ${statePath}`);
  }
  const registeredLabels = state.accounts.map((account) => account.label).filter((label) => typeof label === "string");
  return [...registeredLabels, ...readPendingAccountLabels()];
}

function readPendingAccountLabels() {
  const pendingPath = path.join(configuredStateDir(), "pending-login-accounts.json");
  if (!fs.existsSync(pendingPath)) {
    return [];
  }
  const pendingText = fs.readFileSync(pendingPath, "utf8");
  const pendingAccounts = JSON.parse(pendingText);
  if (!Array.isArray(pendingAccounts)) {
    throw new Error(`Invalid pending login accounts: ${pendingPath}`);
  }
  return pendingAccounts.map((account) => account.label).filter((label) => typeof label === "string");
}

function configuredStateDir() {
  const stateDir = personalConfiguration().get("stateDir");
  if (stateDir && stateDir.trim()) {
    return stateDir.trim();
  }
  return path.join(os.homedir(), ".local", "share", "agents-rtl-personal", "codex-account-switcher");
}

function sanitizeLabelForPath(label) {
  const normalized = label.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || "account";
}

async function runSwitcherJSON(context, args) {
  const fullArgs = argsWithConfiguredStateDir(args);
  const stdout = await runExecutable(resolveSwitcherPath(context), fullArgs);
  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`Switcher returned invalid JSON: ${error.message}\n${stdout}`);
  }
}

function argsWithConfiguredStateDir(args) {
  const stateDir = personalConfiguration().get("stateDir");
  if (!stateDir || !stateDir.trim()) {
    return args;
  }
  return [...args, "--state-dir", stateDir.trim()];
}

function resolveSwitcherPath(context) {
  const configuredPath = personalConfiguration().get("switcherPath");
  if (configuredPath && configuredPath.trim()) {
    return requireExecutablePath(configuredPath.trim());
  }

  const candidates = [
    path.join(context.extensionPath, "..", "codex-account-switcher"),
    path.join(context.extensionPath, "bin", executableFileName()),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error("codex-account-switcher was not found. Configure agentsRtlPersonal.switcherPath.");
}

function executableFileName() {
  return process.platform === "win32" ? "codex-account-switcher.exe" : "codex-account-switcher";
}

function requireExecutablePath(executablePath) {
  if (!path.isAbsolute(executablePath)) {
    throw new Error(`Switcher path must be absolute: ${executablePath}`);
  }
  if (!fs.existsSync(executablePath)) {
    throw new Error(`Switcher path does not exist: ${executablePath}`);
  }
  return executablePath;
}

function runExecutable(executablePath, args) {
	const applicationName = vscode.env.appName.trim();
	if (!applicationName) {
	  throw new Error("VS Code application name is empty; account audit client cannot be identified.");
	}
  return new Promise((resolve, reject) => {
    childProcess.execFile(
      executablePath,
      args,
	  {
		maxBuffer: EXECUTION_MAX_BUFFER_BYTES,
		env: { ...process.env, AGENTS_RTL_ACCOUNT_SWITCHER_CLIENT: applicationName },
	  },
      (error, stdout, stderr) => handleExecutableResult(resolve, reject, error, stdout, stderr)
    );
  });
}

function handleExecutableResult(resolve, reject, error, stdout, stderr) {
  if (error) {
    reject(new Error(`${error.message}\n${stderr || stdout}`.trim()));
    return;
  }
  if (stderr.trim()) {
    reject(new Error(stderr.trim()));
    return;
  }
  resolve(stdout);
}

function errorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function isAuthAccountMismatchError(error) {
  return /auth account mismatch for /.test(errorMessage(error));
}

module.exports = {
  activate,
  deactivate,
};
