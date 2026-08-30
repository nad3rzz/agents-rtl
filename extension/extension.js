"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const vscode = require("vscode");
const {
  DEVTOOLS_ENDPOINT_SOURCE_ACTIVE_PORT_FILE,
  DEVTOOLS_ENDPOINT_SOURCE_FIXED_PORT,
  devtoolsActivePortFilePathFromGlobalStoragePath,
  readDevtoolsActivePortFile,
  requireConfiguredDevtoolsPort,
  resolveConfiguredFilePath,
  validateDevtoolsPort,
} = require("./devtools_endpoint");

const STATUS_BAR_PRIORITY = 100;
const MIN_WATCH_INTERVAL_MS = 500;
const DEFAULT_WATCH_INTERVAL_MS = 2500;
const DEVTOOLS_CHECK_TIMEOUT_MS = 900;
const HELPER_RESTART_DELAY_MS = 700;
const RUNTIME_ARGUMENTS_PORT_KEY = "remote-debugging-port";
const DYNAMIC_DEVTOOLS_PORT_ARGUMENT_VALUE = 0;
const RUNTIME_ARGUMENTS_SETUP_NOTIFICATION_KEY = "runtimeArgumentsSetupNotification";
const CLOSE_EDITOR_ACTION = "Close editor";
const OPENAI_CHATGPT_EXTENSION_ID = "openai.chatgpt";
const PRODUCT_PROFILES = [
  {
    productName: "Antigravity",
    appNameMatchers: ["antigravity"],
    linuxDataFolderName: ".antigravity",
    otherDataFolderName: "Antigravity",
  },
  {
    productName: "VS Code Insiders",
    appNameMatchers: ["insiders"],
    linuxDataFolderName: ".vscode-insiders",
    otherDataFolderName: "Code - Insiders",
  },
  {
    productName: "VSCodium",
    appNameMatchers: ["codium"],
    linuxDataFolderName: ".vscodium",
    otherDataFolderName: "VSCodium",
  },
  {
    productName: "Cursor",
    appNameMatchers: ["cursor"],
    linuxDataFolderName: ".cursor",
    otherDataFolderName: "Cursor",
  },
  {
    productName: "Windsurf",
    appNameMatchers: ["windsurf"],
    linuxDataFolderName: ".windsurf",
    otherDataFolderName: "Windsurf",
  },
  {
    productName: "VS Code",
    appNameMatchers: ["visual studio code", "code"],
    linuxDataFolderName: ".vscode",
    otherDataFolderName: "Code",
  },
];
const helpers = new Map();
let outputChannel;
let statusBarItem;

function configuration() {
  return vscode.workspace.getConfiguration("agentsRtl");
}

function log(message) {
  outputChannel.appendLine(`[${new Date().toISOString()}] ${message}`);
}

function currentAppName() {
  if (typeof vscode.env.appName !== "string" || !vscode.env.appName.trim()) {
    throw new Error("Cannot detect the current VS Code-compatible product name.");
  }

  return vscode.env.appName.trim();
}

function productProfileForCurrentApp() {
  const normalizedAppName = currentAppName().toLowerCase();
  const productProfile = PRODUCT_PROFILES.find((profile) =>
    profile.appNameMatchers.some((matcher) => normalizedAppName.includes(matcher))
  );

  if (!productProfile) {
    throw new Error(`Unsupported VS Code-compatible product: ${currentAppName()}`);
  }

  return productProfile;
}

function configuredFixedDevtoolsPort() {
  const port = configuration().get("devtoolsPort");
  return requireConfiguredDevtoolsPort(port, "agentsRtl.devtoolsPort");
}

function configuredDevtoolsEndpointSource() {
  const endpointSource = configuration().get("devtoolsEndpointSource");
  if (
    endpointSource !== DEVTOOLS_ENDPOINT_SOURCE_FIXED_PORT
    && endpointSource !== DEVTOOLS_ENDPOINT_SOURCE_ACTIVE_PORT_FILE
  ) {
    throw new Error(`Invalid agentsRtl.devtoolsEndpointSource value: ${endpointSource}`);
  }

  return endpointSource;
}

function configuredDevtoolsActivePortFilePath(context) {
  const configuredFilePath = configuration().get("devtoolsActivePortFilePath");
  if (typeof configuredFilePath === "string" && configuredFilePath.trim()) {
    return resolveConfiguredFilePath(configuredFilePath, "agentsRtl.devtoolsActivePortFilePath");
  }

  return devtoolsActivePortFilePathFromGlobalStoragePath(context.globalStorageUri.fsPath);
}

function configuredDevtoolsActivePort(context) {
  const activePortFilePath = configuredDevtoolsActivePortFilePath(context);
  return readDevtoolsActivePortFile(activePortFilePath, "agentsRtl.devtoolsActivePortFilePath");
}

function configuredPrimaryDevtoolsPort(context) {
  if (configuredDevtoolsEndpointSource() === DEVTOOLS_ENDPOINT_SOURCE_FIXED_PORT) {
    return configuredFixedDevtoolsPort();
  }

  return configuredDevtoolsActivePort(context).port;
}

function configuredExtraDevtoolsPorts() {
  const ports = configuration().get("extraDevtoolsPorts");
  if (!Array.isArray(ports)) {
    throw new Error(`Invalid agentsRtl.extraDevtoolsPorts value: ${ports}`);
  }

  return ports.map((port) => {
    validateDevtoolsPort(port, "agentsRtl.extraDevtoolsPorts");
    return port;
  });
}

function configuredWatchedDevtoolsPorts(context) {
  return [...new Set([configuredPrimaryDevtoolsPort(context), ...configuredExtraDevtoolsPorts()])];
}

function configuredWorkspaceCwds() {
  const workspaceFolders = vscode.workspace.workspaceFolders || [];
  return [...new Set(workspaceFolders.map((folder) => folder.uri.fsPath).filter(Boolean))];
}

function configuredWatchIntervalMs() {
  const interval = configuration().get("watchIntervalMs");
  if (!Number.isInteger(interval) || interval < MIN_WATCH_INTERVAL_MS) {
    throw new Error(`Invalid agentsRtl.watchIntervalMs value: ${interval}`);
  }
  return interval;
}

function helperFileName() {
  if (process.platform === "win32") return "agents-rtl-helper-windows.exe";
  if (process.platform === "darwin") return "agents-rtl-helper-macos";
  if (process.platform === "linux") return "agents-rtl-helper-linux";
  throw new Error(`Unsupported platform: ${process.platform}`);
}

function helperPath(context) {
  const resolvedPath = path.join(context.extensionPath, "bin", helperFileName());
  if (!fs.existsSync(resolvedPath)) {
    throw new Error(`Bundled helper binary is missing: ${resolvedPath}`);
  }
  return resolvedPath;
}

function codexExecutableFileName() {
  return process.platform === "win32" ? "codex.exe" : "codex";
}

function platformNameMatchesCurrentRuntime(value) {
  const normalizedValue = value.toLowerCase();
  const platformAliases = {
    win32: ["win", "windows"],
    linux: ["linux"],
    darwin: ["darwin", "macos", "mac"],
  }[process.platform];
  if (!platformAliases) {
    throw new Error(`Unsupported platform for Codex CLI discovery: ${process.platform}`);
  }
  return platformAliases.some((alias) => normalizedValue.includes(alias));
}

function archNameMatchesCurrentRuntime(value) {
  const normalizedValue = value.toLowerCase();
  const archAliases = {
    x64: ["x64", "x86_64", "amd64"],
    arm64: ["arm64", "aarch64"],
  }[process.arch];
  if (!archAliases) {
    throw new Error(`Unsupported architecture for Codex CLI discovery: ${process.arch}`);
  }
  return archAliases.some((alias) => normalizedValue.includes(alias));
}

function findCodexExecutableCandidates(directoryPath, executableFileName) {
  if (!fs.existsSync(directoryPath)) {
    return [];
  }

  const candidates = [];
  const entries = fs.readdirSync(directoryPath, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(directoryPath, entry.name);
    if (entry.isDirectory()) {
      candidates.push(...findCodexExecutableCandidates(entryPath, executableFileName));
      continue;
    }
    if (entry.isFile() && entry.name === executableFileName) {
      candidates.push(entryPath);
    }
  }
  return candidates;
}

function openAICodexCliPath() {
  const openAIExtension = vscode.extensions.getExtension(OPENAI_CHATGPT_EXTENSION_ID);
  if (!openAIExtension) {
    log(`OpenAI extension is not installed. Codex archive CLI path will not be passed.`);
    return "";
  }

  const binDirectoryPath = path.join(openAIExtension.extensionPath, "bin");
  const candidates = findCodexExecutableCandidates(binDirectoryPath, codexExecutableFileName());
  if (candidates.length === 0) {
    throw new Error(`Codex CLI is missing inside ${OPENAI_CHATGPT_EXTENSION_ID}: ${binDirectoryPath}`);
  }

  const runtimeCandidates = candidates.filter((candidate) =>
    platformNameMatchesCurrentRuntime(candidate) && archNameMatchesCurrentRuntime(candidate)
  );
  if (runtimeCandidates.length === 1) {
    return runtimeCandidates[0];
  }
  if (runtimeCandidates.length > 1) {
    throw new Error(`Multiple matching Codex CLI binaries found: ${runtimeCandidates.join(", ")}`);
  }
  if (candidates.length === 1) {
    return candidates[0];
  }

  throw new Error(`Cannot choose Codex CLI binary for ${process.platform}/${process.arch}: ${candidates.join(", ")}`);
}

function runningProcess() {
  return helpers.get("main") || null;
}

function updateStatusBar(text) {
  statusBarItem.text = text;
  statusBarItem.show();
}

function devtoolsPortIsOpen(port) {
  return new Promise((resolve) => {
    const request = http.get({
      host: "127.0.0.1",
      port,
      path: "/json/version",
      timeout: DEVTOOLS_CHECK_TIMEOUT_MS,
    }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });

    request.on("timeout", () => {
      request.destroy(new Error(`Timed out checking DevTools port ${port}`));
    });
    request.on("error", () => resolve(false));
  });
}

function configuredArgvFilePath() {
  const configuredPath = configuration().get("argvFilePath");
  if (typeof configuredPath === "string" && configuredPath.trim()) {
    return configuredPath.trim();
  }

  return defaultArgvFilePath();
}

function defaultArgvFilePath() {
  if (process.env.VSCODE_PORTABLE) {
    return path.join(process.env.VSCODE_PORTABLE, "argv.json");
  }

  if (process.platform === "win32") {
    return path.join(windowsAppDataFolderPath(), productDataFolderName(), "User", "argv.json");
  }

  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", productDataFolderName(), "User", "argv.json");
  }

  return path.join(os.homedir(), productDataFolderName(), "argv.json");
}

function windowsAppDataFolderPath() {
  if (process.env.APPDATA) {
    return process.env.APPDATA;
  }

  return path.join(os.homedir(), "AppData", "Roaming");
}

function productDataFolderName() {
  const productProfile = productProfileForCurrentApp();
  return process.platform === "linux" ? productProfile.linuxDataFolderName : productProfile.otherDataFolderName;
}

function stripJsonComments(jsonText) {
  let strippedText = "";
  let isInsideString = false;
  let isInsideLineComment = false;
  let isInsideBlockComment = false;
  let previousCharacterWasEscape = false;

  for (let index = 0; index < jsonText.length; index += 1) {
    const currentCharacter = jsonText[index];
    const nextCharacter = jsonText[index + 1];

    if (isInsideLineComment) {
      if (currentCharacter === "\n" || currentCharacter === "\r") {
        isInsideLineComment = false;
        strippedText += currentCharacter;
      }
      continue;
    }

    if (isInsideBlockComment) {
      if (currentCharacter === "*" && nextCharacter === "/") {
        isInsideBlockComment = false;
        index += 1;
        continue;
      }
      if (currentCharacter === "\n" || currentCharacter === "\r") {
        strippedText += currentCharacter;
      }
      continue;
    }

    if (isInsideString) {
      strippedText += currentCharacter;
      if (previousCharacterWasEscape) {
        previousCharacterWasEscape = false;
        continue;
      }
      if (currentCharacter === "\\") {
        previousCharacterWasEscape = true;
        continue;
      }
      if (currentCharacter === "\"") {
        isInsideString = false;
      }
      continue;
    }

    if (currentCharacter === "\"") {
      isInsideString = true;
      strippedText += currentCharacter;
      continue;
    }

    if (currentCharacter === "/" && nextCharacter === "/") {
      isInsideLineComment = true;
      index += 1;
      continue;
    }

    if (currentCharacter === "/" && nextCharacter === "*") {
      isInsideBlockComment = true;
      index += 1;
      continue;
    }

    strippedText += currentCharacter;
  }

  return strippedText;
}

function parseRuntimeArgumentsFileContent(fileContent, filePath) {
  const trimmedContent = fileContent.trim();
  if (!trimmedContent) {
    return {};
  }

  try {
    const parsedPayload = JSON.parse(stripJsonComments(trimmedContent));
    if (!parsedPayload || Array.isArray(parsedPayload) || typeof parsedPayload !== "object") {
      throw new Error("argv.json root must be an object.");
    }
    return parsedPayload;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Invalid VS Code runtime arguments file ${filePath}: ${message}`);
  }
}

function runtimeArgumentValueLiteral(value) {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return JSON.stringify(value);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceRuntimeArgumentValue(fileContent, runtimeArgumentName, runtimeArgumentValue) {
  const valuePattern = "(?:-?\\d+(?:\\.\\d+)?|\"(?:[^\"\\\\]|\\\\.)*\"|true|false|null)";
  const propertyPattern = new RegExp(`("${escapeRegExp(runtimeArgumentName)}"\\s*:\\s*)${valuePattern}`, "m");

  if (!propertyPattern.test(fileContent)) {
    return null;
  }

  return fileContent.replace(propertyPattern, `$1${runtimeArgumentValueLiteral(runtimeArgumentValue)}`);
}

function insertRuntimeArgumentValue(fileContent, runtimeArguments, runtimeArgumentName, runtimeArgumentValue) {
  const closingBraceIndex = fileContent.lastIndexOf("}");
  if (closingBraceIndex === -1) {
    throw new Error("Cannot update argv.json because the root closing brace is missing.");
  }

  const fileContentBeforeClosingBrace = fileContent.slice(0, closingBraceIndex).trimEnd();
  const fileContentAfterClosingBrace = fileContent.slice(closingBraceIndex);
  const commaPrefix = Object.keys(runtimeArguments).length > 0 ? "," : "";

  return [
    fileContentBeforeClosingBrace,
    commaPrefix,
    `\n  "${runtimeArgumentName}": ${runtimeArgumentValueLiteral(runtimeArgumentValue)}\n`,
    fileContentAfterClosingBrace,
  ].join("");
}

function configuredRuntimeArgumentsFileContent(fileContent, runtimeArguments, runtimeArgumentName, runtimeArgumentValue) {
  const replacedContent = replaceRuntimeArgumentValue(fileContent, runtimeArgumentName, runtimeArgumentValue);
  if (replacedContent !== null) {
    return replacedContent;
  }

  return insertRuntimeArgumentValue(fileContent, runtimeArguments, runtimeArgumentName, runtimeArgumentValue);
}

function writeRuntimeArgumentsPortIfNeeded(port) {
  const runtimeArgumentsPortValue = String(port);
  const argvFilePath = configuredArgvFilePath();
  const fileContent = fs.existsSync(argvFilePath) ? fs.readFileSync(argvFilePath, "utf8") : "{\n}\n";
  const runtimeArguments = parseRuntimeArgumentsFileContent(fileContent, argvFilePath);

  if (runtimeArguments[RUNTIME_ARGUMENTS_PORT_KEY] === runtimeArgumentsPortValue) {
    return { argvFilePath, didChange: false, port };
  }

  const nextFileContent = configuredRuntimeArgumentsFileContent(
    fileContent,
    runtimeArguments,
    RUNTIME_ARGUMENTS_PORT_KEY,
    runtimeArgumentsPortValue
  );
  const nextRuntimeArguments = parseRuntimeArgumentsFileContent(nextFileContent, argvFilePath);
  if (nextRuntimeArguments[RUNTIME_ARGUMENTS_PORT_KEY] !== runtimeArgumentsPortValue) {
    throw new Error(`Failed to verify ${RUNTIME_ARGUMENTS_PORT_KEY} in ${argvFilePath}.`);
  }

  fs.mkdirSync(path.dirname(argvFilePath), { recursive: true });
  fs.writeFileSync(argvFilePath, nextFileContent);
  return { argvFilePath, didChange: true, port };
}

async function showRestartNotificationIfNeeded(context, port, argvFilePath) {
  const notificationIdentity = `${argvFilePath}:${port}`;
  const previousNotificationIdentity = context.globalState.get(RUNTIME_ARGUMENTS_SETUP_NOTIFICATION_KEY);
  if (previousNotificationIdentity === notificationIdentity) {
    return;
  }

  await context.globalState.update(RUNTIME_ARGUMENTS_SETUP_NOTIFICATION_KEY, notificationIdentity);
  const selectedAction = await vscode.window.showInformationMessage(
    "Agents RTL is enabled. Restart the editor to apply RTL.",
    CLOSE_EDITOR_ACTION
  );

  if (selectedAction === CLOSE_EDITOR_ACTION) {
    vscode.commands.executeCommand("workbench.action.quit");
  }
}

async function configureRuntimeArgumentsAndStartIfReady(context) {
  const productProfile = productProfileForCurrentApp();
  const endpointSource = configuredDevtoolsEndpointSource();

  if (endpointSource === DEVTOOLS_ENDPOINT_SOURCE_ACTIVE_PORT_FILE) {
    const activePortFilePath = configuredDevtoolsActivePortFilePath(context);
    const result = writeRuntimeArgumentsPortIfNeeded(DYNAMIC_DEVTOOLS_PORT_ARGUMENT_VALUE);
    log(
      `Product profile. appName="${currentAppName()}" product="${productProfile.productName}"`
      + ` endpointSource=${endpointSource} activePortFile=${activePortFilePath}`
    );
    log(
      `Dynamic runtime arguments ready. argv=${result.argvFilePath}`
      + ` port=${result.port} changed=${result.didChange}`
    );
    if (result.didChange) {
      updateStatusBar("Agents RTL: restart required");
      await showRestartNotificationIfNeeded(context, result.port, result.argvFilePath);
      return;
    }

    if (fs.existsSync(activePortFilePath)) {
      const { port } = configuredDevtoolsActivePort(context);
      const isOpen = await devtoolsPortIsOpen(port);
      log(
        `Dynamic DevTools endpoint. port=${port} open=${isOpen}`
      );
      if (isOpen) {
        await context.globalState.update(RUNTIME_ARGUMENTS_SETUP_NOTIFICATION_KEY, undefined);
        startHelper(context);
        return;
      }
    }

    updateStatusBar("Agents RTL: restart required");
    await showRestartNotificationIfNeeded(context, result.port, result.argvFilePath);
    return;
  }

  const port = configuredFixedDevtoolsPort();
  log(
    `Product profile. appName="${currentAppName()}" product="${productProfile.productName}"`
    + ` endpointSource=${endpointSource} port=${port}`
  );
  const isOpen = await devtoolsPortIsOpen(port);
  if (isOpen) {
    await context.globalState.update(RUNTIME_ARGUMENTS_SETUP_NOTIFICATION_KEY, undefined);
    startHelper(context);
    return;
  }

  const result = writeRuntimeArgumentsPortIfNeeded(port);
  log(`Runtime arguments ready. argv=${result.argvFilePath} port=${result.port} changed=${result.didChange}`);
  updateStatusBar("Agents RTL: restart required");
  await showRestartNotificationIfNeeded(context, result.port, result.argvFilePath);
}

function showCommandError(error) {
  const message = error instanceof Error ? error.message : String(error);
  log(`Command failed: ${message}`);
  vscode.window.showErrorMessage(`Agents RTL: ${message}`);
}

function runCommandWithErrors(commandBody) {
  try {
    const commandResult = commandBody();
    if (commandResult && typeof commandResult.then === "function") {
      return commandResult.catch(showCommandError);
    }
    return commandResult;
  } catch (error) {
    showCommandError(error);
    return undefined;
  }
}

function startHelper(context) {
  const existingProcess = runningProcess();
  if (existingProcess && existingProcess.exitCode === null) {
    log(`Helper already running. pid=${existingProcess.pid}`);
    updateStatusBar("Agents RTL: active");
    return;
  }

  const executablePath = helperPath(context);
  const ports = configuredWatchedDevtoolsPorts(context).map(String);
  const workspaceCwds = configuredWorkspaceCwds();
  const interval = String(configuredWatchIntervalMs());
  const codexCliPath = openAICodexCliPath();
  if (codexCliPath) {
    log(`Codex CLI path: ${codexCliPath}`);
  }
  const helperArguments = ports.flatMap((port) => ["--port", port]);
  helperArguments.push(...workspaceCwds.flatMap((workspaceCwd) => ["--workspace-cwd", workspaceCwd]));
  helperArguments.push("--interval-ms", interval);
  helperArguments.push("--resource-monitor-port", String(configuredPrimaryDevtoolsPort(context)));
  helperArguments.push("--extension-host-pid", String(process.pid));
  if (codexCliPath) {
    helperArguments.push("--codex-cli", codexCliPath);
  }
  const helperProcess = childProcess.spawn(executablePath, helperArguments, {
    cwd: context.extensionPath,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  helpers.set("main", helperProcess);
  log(`Helper started. pid=${helperProcess.pid} ports=${ports.join(",")} workspaces=${workspaceCwds.length}`);
  updateStatusBar("Agents RTL: active");

  helperProcess.stdout.on("data", (chunk) => outputChannel.append(chunk.toString()));
  helperProcess.stderr.on("data", (chunk) => outputChannel.append(chunk.toString()));
  helperProcess.on("exit", (code, signal) => {
    log(`Helper exited. code=${code} signal=${signal}`);
    if (helpers.get("main") === helperProcess) {
      helpers.delete("main");
    }
    updateStatusBar("Agents RTL: stopped");
  });
  helperProcess.on("error", (error) => {
    log(`Helper failed: ${error.message}`);
    helpers.delete("main");
    updateStatusBar("Agents RTL: error");
    vscode.window.showErrorMessage(`Agents RTL helper failed: ${error.message}`);
  });
}

function stopHelper() {
  const helperProcess = runningProcess();
  if (!helperProcess || helperProcess.exitCode !== null) {
    helpers.delete("main");
    log("Helper is not running.");
    updateStatusBar("Agents RTL: stopped");
    return;
  }

  log(`Stopping helper. pid=${helperProcess.pid}`);
  helperProcess.kill("SIGTERM");
}

function restartHelper(context) {
  stopHelper();
  setTimeout(() => runCommandWithErrors(() => startHelper(context)), HELPER_RESTART_DELAY_MS);
}

function reconfigureHelper(context) {
  stopHelper();
  setTimeout(
    () => runCommandWithErrors(() => configureRuntimeArgumentsAndStartIfReady(context)),
    HELPER_RESTART_DELAY_MS
  );
}

function statusMessage() {
  const helperProcess = runningProcess();
  if (!helperProcess || helperProcess.exitCode !== null) {
    return "Agents RTL: stopped";
  }
  return `Agents RTL: running pid=${helperProcess.pid}`;
}

function activate(context) {
  outputChannel = vscode.window.createOutputChannel("Agents RTL");
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, STATUS_BAR_PRIORITY);
  statusBarItem.command = "agentsRtl.status";
  context.subscriptions.push(outputChannel, statusBarItem);

  context.subscriptions.push(vscode.commands.registerCommand("agentsRtl.start", () => runCommandWithErrors(() => configureRuntimeArgumentsAndStartIfReady(context))));
  context.subscriptions.push(vscode.commands.registerCommand("agentsRtl.stop", () => runCommandWithErrors(() => stopHelper())));
  context.subscriptions.push(vscode.commands.registerCommand("agentsRtl.restart", () => runCommandWithErrors(() => reconfigureHelper(context))));
  context.subscriptions.push(vscode.commands.registerCommand("agentsRtl.configureRuntimeArguments", () => runCommandWithErrors(() => configureRuntimeArgumentsAndStartIfReady(context))));
  context.subscriptions.push(vscode.commands.registerCommand("agentsRtl.status", () => {
    const message = statusMessage();
    log(message);
    vscode.window.showInformationMessage(message);
  }));
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => {
    log("Workspace folders changed. Restarting helper.");
    restartHelper(context);
  }));
  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration("agentsRtl")) return;
    log("Agents RTL configuration changed. Reconfiguring helper.");
    reconfigureHelper(context);
  }));

  updateStatusBar("Agents RTL: stopped");
  if (configuration().get("autoStart")) {
    runCommandWithErrors(() => configureRuntimeArgumentsAndStartIfReady(context));
  }
}

function deactivate() {
  stopHelper();
}

module.exports = { activate, deactivate };
