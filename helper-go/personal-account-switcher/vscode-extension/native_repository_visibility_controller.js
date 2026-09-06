"use strict";

const vscode = require("vscode");
const {
  REPOSITORY_FILE_EVENT_ACTION,
  findClosedManagedRepositoryRootPaths,
  findManagedRepositoryRootPath,
  repositoryFileEventAction,
  repositoryNativeStateIsReady,
  repositoryShouldRemainVisible,
} = require("./native_repository_visibility_model");

const GIT_EXTENSION_ID = "vscode.git";
const GIT_API_VERSION = 1;
const MANAGED_REPOSITORY_ROOT_PATHS_STATE_KEY =
  "agentsRtlPersonal.nativeRepositoryVisibility.managedRootPaths";
const REPOSITORY_CLOSE_DELAY_MILLISECONDS = 1500;
const REPOSITORY_OPEN_DELAY_MILLISECONDS = 1500;

let nativeRepositoryVisibilityContext;
let nativeRepositoryVisibilityGitApi;
let nativeRepositoryVisibilityOutputChannel;
let workspaceFileSystemWatcher;
let controllerFailureReported = false;
let nativeRepositoryVisibilityInitialized = false;
let managedRepositoryRootPathPersistencePromise = Promise.resolve();
const managedRepositoryRootPaths = new Set();
const repositoryStateSubscriptionsByRootPath = new Map();
const repositoryCloseTimeoutsByRootPath = new Map();
const repositoryOpenTimeoutsByRootPath = new Map();
const repositoryRootPathsAwaitingNativeState = new Set();

function requireControllerContext() {
  if (!nativeRepositoryVisibilityContext) {
    throw new Error("Native repository visibility context is not initialized.");
  }
  return nativeRepositoryVisibilityContext;
}

function requireGitApi() {
  if (!nativeRepositoryVisibilityGitApi) {
    throw new Error("Native repository visibility Git API is not initialized.");
  }
  return nativeRepositoryVisibilityGitApi;
}

function requireOutputChannel() {
  if (!nativeRepositoryVisibilityOutputChannel) {
    throw new Error("Native repository visibility output channel is not initialized.");
  }
  return nativeRepositoryVisibilityOutputChannel;
}

function repositoryRootPath(repository) {
  const rootPath = repository?.rootUri?.fsPath;
  if (typeof rootPath !== "string" || !rootPath) {
    throw new Error("Git repository root URI is missing its file-system path.");
  }
  return rootPath;
}

function reportControllerFailure(operationName, error) {
  const message = error instanceof Error ? error.message : String(error);
  requireOutputChannel().error(`${operationName}: ${message}`);
  if (!controllerFailureReported) {
    controllerFailureReported = true;
    vscode.window.showErrorMessage(`Agents RTL Personal SCM failed: ${message}`);
  }
}

function runControllerOperation(operationName, operationPromise) {
  operationPromise.catch(reportControllerFailure.bind(null, operationName));
}

function loadManagedRepositoryRootPaths() {
  const storedRootPaths = requireControllerContext().workspaceState.get(
    MANAGED_REPOSITORY_ROOT_PATHS_STATE_KEY,
    [],
  );
  if (!Array.isArray(storedRootPaths)) {
    throw new Error("Stored managed Git repository roots must be an array.");
  }

  for (const rootPath of storedRootPaths) {
    if (typeof rootPath !== "string" || !rootPath) {
      throw new Error("Stored managed Git repository root is invalid.");
    }
    managedRepositoryRootPaths.add(rootPath);
  }
}

async function persistManagedRepositoryRootPaths() {
  const sortedRootPaths = Array.from(managedRepositoryRootPaths).sort((leftPath, rightPath) =>
    leftPath.localeCompare(rightPath),
  );
  await requireControllerContext().workspaceState.update(
    MANAGED_REPOSITORY_ROOT_PATHS_STATE_KEY,
    sortedRootPaths,
  );
}

function rememberManagedRepositoryRootPath(rootPath) {
  if (managedRepositoryRootPaths.has(rootPath)) {
    return managedRepositoryRootPathPersistencePromise;
  }
  managedRepositoryRootPaths.add(rootPath);
  requireOutputChannel().info(`Managing repository: ${rootPath}`);
  managedRepositoryRootPathPersistencePromise =
    managedRepositoryRootPathPersistencePromise.then(persistManagedRepositoryRootPaths);
  return managedRepositoryRootPathPersistencePromise;
}

function cancelRepositoryClose(rootPath) {
  const closeTimeout = repositoryCloseTimeoutsByRootPath.get(rootPath);
  if (closeTimeout !== undefined) {
    clearTimeout(closeTimeout);
    repositoryCloseTimeoutsByRootPath.delete(rootPath);
  }
}

function cancelRepositoryOpen(rootPath) {
  const openTimeout = repositoryOpenTimeoutsByRootPath.get(rootPath);
  if (openTimeout !== undefined) {
    clearTimeout(openTimeout);
    repositoryOpenTimeoutsByRootPath.delete(rootPath);
  }
}

function scheduleRepositoryClose(repository) {
  const rootPath = repositoryRootPath(repository);
  cancelRepositoryClose(rootPath);
  const closeTimeout = setTimeout(
    closeRepositoryIfStillClean.bind(null, rootPath),
    REPOSITORY_CLOSE_DELAY_MILLISECONDS,
  );
  repositoryCloseTimeoutsByRootPath.set(rootPath, closeTimeout);
}

function evaluateNativeRepositoryState(repository) {
  const rootPath = repositoryRootPath(repository);
  if (!repositoryNativeStateIsReady(repository)) {
    return;
  }

  repositoryRootPathsAwaitingNativeState.delete(rootPath);
  if (repositoryShouldRemainVisible(repository)) {
    cancelRepositoryClose(rootPath);
    return;
  }
  scheduleRepositoryClose(repository);
}

function handleRepositoryStateChange(repository) {
  evaluateNativeRepositoryState(repository);
}

function subscribeToRepositoryState(repository) {
  const rootPath = repositoryRootPath(repository);
  const existingSubscription = repositoryStateSubscriptionsByRootPath.get(rootPath);
  if (existingSubscription) {
    existingSubscription.dispose();
  }
  repositoryStateSubscriptionsByRootPath.set(
    rootPath,
    repository.state.onDidChange(handleRepositoryStateChange.bind(null, repository)),
  );
}

function disposeRepositoryStateSubscription(rootPath) {
  const repositoryStateSubscription = repositoryStateSubscriptionsByRootPath.get(rootPath);
  if (repositoryStateSubscription) {
    repositoryStateSubscription.dispose();
    repositoryStateSubscriptionsByRootPath.delete(rootPath);
  }
}

function handleRepositoryOpened(repository) {
  const rootPath = repositoryRootPath(repository);
  subscribeToRepositoryState(repository);
  runControllerOperation(
    `Persist repository ${rootPath}`,
    rememberManagedRepositoryRootPath(rootPath),
  );

  if (!repositoryRootPathsAwaitingNativeState.has(rootPath)) {
    evaluateNativeRepositoryState(repository);
  }
}

function handleRepositoryClosed(repository) {
  const rootPath = repositoryRootPath(repository);
  cancelRepositoryClose(rootPath);
  disposeRepositoryStateSubscription(rootPath);
}

async function initializeNativeRepositoryVisibilityAfterGitApiReady() {
  if (nativeRepositoryVisibilityInitialized) {
    return;
  }
  const gitApi = requireGitApi();
  if (gitApi.state !== "initialized") {
    throw new Error(`Cannot initialize repository visibility from Git state: ${gitApi.state}`);
  }

  nativeRepositoryVisibilityInitialized = true;
  for (const repository of gitApi.repositories) {
    await rememberManagedRepositoryRootPath(repositoryRootPath(repository));
    subscribeToRepositoryState(repository);
    evaluateNativeRepositoryState(repository);
  }

  const openRepositoryRootPaths = gitApi.repositories.map(repositoryRootPath);
  const closedManagedRepositoryRootPaths = findClosedManagedRepositoryRootPaths(
    Array.from(managedRepositoryRootPaths),
    openRepositoryRootPaths,
  );
  for (const rootPath of closedManagedRepositoryRootPaths) {
    await openClosedRepositoryForNativeEvaluation(rootPath, "startup");
  }

  requireOutputChannel().info(
    `Native repository visibility tracking ${managedRepositoryRootPaths.size} repositories.`,
  );
}

function handleGitApiStateChange(state) {
  if (state === "initialized") {
    runControllerOperation(
      "Initialize native repository visibility",
      initializeNativeRepositoryVisibilityAfterGitApiReady(),
    );
    return;
  }
  if (state !== "uninitialized") {
    reportControllerFailure("Git API state change", new Error(`Unexpected Git API state: ${state}`));
  }
}

async function closeRepositoryIfStillClean(rootPath) {
  repositoryCloseTimeoutsByRootPath.delete(rootPath);
  const gitApi = requireGitApi();
  const repositoryUri = vscode.Uri.file(rootPath);
  const repository = gitApi.getRepository(repositoryUri);
  if (!repository) {
    return;
  }
  if (!repositoryNativeStateIsReady(repository)) {
    throw new Error(`Native Git state is not ready before close: ${rootPath}`);
  }
  if (repositoryShouldRemainVisible(repository)) {
    return;
  }

  await vscode.commands.executeCommand("git.close", repository);
  if (gitApi.getRepository(repositoryUri) !== null) {
    throw new Error(`Native Git repository did not close: ${rootPath}`);
  }
  requireOutputChannel().info(`Hidden clean repository: ${rootPath}`);
}

function scheduleClosedRepositoryOpen(rootPath) {
  if (repositoryOpenTimeoutsByRootPath.has(rootPath)) {
    return;
  }
  const openTimeout = setTimeout(
    openClosedRepositoryAfterFileEvent.bind(null, rootPath),
    REPOSITORY_OPEN_DELAY_MILLISECONDS,
  );
  repositoryOpenTimeoutsByRootPath.set(rootPath, openTimeout);
}

async function openClosedRepositoryAfterFileEvent(rootPath) {
  repositoryOpenTimeoutsByRootPath.delete(rootPath);
  await openClosedRepositoryForNativeEvaluation(rootPath, "file event");
}

async function openClosedRepositoryForNativeEvaluation(rootPath, triggerName) {
  if (triggerName !== "startup" && triggerName !== "file event") {
    throw new Error(`Unsupported repository open trigger: ${triggerName}`);
  }
  const gitApi = requireGitApi();
  const repositoryUri = vscode.Uri.file(rootPath);
  if (gitApi.getRepository(repositoryUri)) {
    return;
  }

  repositoryRootPathsAwaitingNativeState.add(rootPath);
  const repository = await gitApi.openRepository(repositoryUri);
  if (!repository) {
    repositoryRootPathsAwaitingNativeState.delete(rootPath);
    throw new Error(`Native Git API did not reopen repository: ${rootPath}`);
  }
  requireOutputChannel().info(
    `Reopened repository for native evaluation after ${triggerName}: ${rootPath}`,
  );
}

function handleWorkspaceFileEvent(fileUri) {
  if (!fileUri || typeof fileUri.fsPath !== "string") {
    throw new Error("Workspace file event URI is invalid.");
  }
  const rootPath = findManagedRepositoryRootPath(
    Array.from(managedRepositoryRootPaths),
    fileUri.fsPath,
  );
  if (!rootPath) {
    return;
  }
  const repositoryIsOpen = Boolean(requireGitApi().getRepository(vscode.Uri.file(rootPath)));
  const fileEventAction = repositoryFileEventAction(
    rootPath,
    fileUri.fsPath,
    repositoryIsOpen,
  );
  if (fileEventAction === REPOSITORY_FILE_EVENT_ACTION.IGNORE) {
    return;
  }
  if (fileEventAction === REPOSITORY_FILE_EVENT_ACTION.CANCEL_PENDING_CLOSE) {
    cancelRepositoryClose(rootPath);
    return;
  }
  if (fileEventAction === REPOSITORY_FILE_EVENT_ACTION.OPEN_CLOSED_REPOSITORY) {
    scheduleClosedRepositoryOpen(rootPath);
    return;
  }
  throw new Error(`Unsupported repository file event action: ${fileEventAction}`);
}

function disposeNativeRepositoryVisibilityController() {
  for (const rootPath of repositoryCloseTimeoutsByRootPath.keys()) {
    cancelRepositoryClose(rootPath);
  }
  for (const rootPath of repositoryOpenTimeoutsByRootPath.keys()) {
    cancelRepositoryOpen(rootPath);
  }
  for (const rootPath of repositoryStateSubscriptionsByRootPath.keys()) {
    disposeRepositoryStateSubscription(rootPath);
  }

  managedRepositoryRootPaths.clear();
  repositoryRootPathsAwaitingNativeState.clear();
  workspaceFileSystemWatcher = undefined;
  nativeRepositoryVisibilityGitApi = undefined;
  nativeRepositoryVisibilityOutputChannel = undefined;
  nativeRepositoryVisibilityContext = undefined;
  controllerFailureReported = false;
  nativeRepositoryVisibilityInitialized = false;
  managedRepositoryRootPathPersistencePromise = Promise.resolve();
}

async function registerNativeRepositoryVisibilityController(context) {
  if (nativeRepositoryVisibilityContext || nativeRepositoryVisibilityGitApi) {
    throw new Error("Native repository visibility controller is already registered.");
  }

  nativeRepositoryVisibilityContext = context;
  nativeRepositoryVisibilityOutputChannel = vscode.window.createOutputChannel(
    "Agents RTL Personal SCM",
    { log: true },
  );
  context.subscriptions.push(nativeRepositoryVisibilityOutputChannel);
  loadManagedRepositoryRootPaths();

  const gitExtension = vscode.extensions.getExtension(GIT_EXTENSION_ID);
  if (!gitExtension) {
    throw new Error(`Required extension is unavailable: ${GIT_EXTENSION_ID}`);
  }
  const gitExtensionExports = await gitExtension.activate();
  if (!gitExtensionExports || typeof gitExtensionExports.getAPI !== "function") {
    throw new Error(`${GIT_EXTENSION_ID} does not expose getAPI().`);
  }

  nativeRepositoryVisibilityGitApi = gitExtensionExports.getAPI(GIT_API_VERSION);

  context.subscriptions.push(
    nativeRepositoryVisibilityGitApi.onDidChangeState(handleGitApiStateChange),
    nativeRepositoryVisibilityGitApi.onDidOpenRepository(handleRepositoryOpened),
    nativeRepositoryVisibilityGitApi.onDidCloseRepository(handleRepositoryClosed),
  );

  workspaceFileSystemWatcher = vscode.workspace.createFileSystemWatcher("**/*");
  context.subscriptions.push(
    workspaceFileSystemWatcher,
    workspaceFileSystemWatcher.onDidChange(handleWorkspaceFileEvent),
    workspaceFileSystemWatcher.onDidCreate(handleWorkspaceFileEvent),
    workspaceFileSystemWatcher.onDidDelete(handleWorkspaceFileEvent),
    { dispose: disposeNativeRepositoryVisibilityController },
  );

  if (nativeRepositoryVisibilityGitApi.state === "initialized") {
    await initializeNativeRepositoryVisibilityAfterGitApiReady();
  } else if (nativeRepositoryVisibilityGitApi.state === "uninitialized") {
    requireOutputChannel().info("Waiting for native Git API initialization.");
  } else {
    throw new Error(`Unexpected initial Git API state: ${nativeRepositoryVisibilityGitApi.state}`);
  }
}

module.exports = {
  registerNativeRepositoryVisibilityController,
};
