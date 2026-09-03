"use strict";

const path = require("path");

const REPOSITORY_CHANGE_COLLECTION_NAMES = Object.freeze([
  "mergeChanges",
  "indexChanges",
  "workingTreeChanges",
  "untrackedChanges",
]);
const REPOSITORY_EVENT_IGNORED_DIRECTORY_NAMES = Object.freeze([
  ".git",
  "nosync",
  "tmp",
]);
const REPOSITORY_FILE_EVENT_ACTION = Object.freeze({
  IGNORE: "ignore",
  CANCEL_PENDING_CLOSE: "cancel-pending-close",
  OPEN_CLOSED_REPOSITORY: "open-closed-repository",
});

function requireRepositoryState(repository) {
  if (!repository || typeof repository !== "object") {
    throw new Error("Git repository is missing.");
  }
  if (!repository.state || typeof repository.state !== "object") {
    throw new Error("Git repository state is missing.");
  }
  return repository.state;
}

function requireRepositoryChangeCollection(repositoryState, collectionName) {
  const changeCollection = repositoryState[collectionName];
  if (!Array.isArray(changeCollection)) {
    throw new Error(`Git repository state is missing ${collectionName}.`);
  }
  return changeCollection;
}

function countRepositoryChanges(repository) {
  const repositoryState = requireRepositoryState(repository);
  return REPOSITORY_CHANGE_COLLECTION_NAMES.reduce(
    (changeCount, collectionName) =>
      changeCount + requireRepositoryChangeCollection(repositoryState, collectionName).length,
    0,
  );
}

function repositoryNativeStateIsReady(repository) {
  const repositoryState = requireRepositoryState(repository);
  const head = repositoryState.HEAD;
  return Boolean(head && (head.commit || head.name));
}

function optionalNonNegativeInteger(value, fieldName) {
  if (value === undefined) {
    return 0;
  }
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`Git repository HEAD ${fieldName} must be a non-negative integer.`);
  }
  return value;
}

function repositoryHasPendingSynchronization(repository) {
  const repositoryState = requireRepositoryState(repository);
  if (!repositoryState.HEAD || typeof repositoryState.HEAD !== "object") {
    throw new Error("Git repository HEAD is missing.");
  }

  const ahead = optionalNonNegativeInteger(repositoryState.HEAD.ahead, "ahead");
  const behind = optionalNonNegativeInteger(repositoryState.HEAD.behind, "behind");
  return ahead > 0 || behind > 0;
}

function repositoryShouldRemainVisible(repository) {
  if (!repositoryNativeStateIsReady(repository)) {
    throw new Error("Git repository native state is not ready.");
  }
  return countRepositoryChanges(repository) > 0 || repositoryHasPendingSynchronization(repository);
}

function requireAbsoluteRepositoryRootPath(repositoryRootPath) {
  if (typeof repositoryRootPath !== "string" || !path.isAbsolute(repositoryRootPath)) {
    throw new Error("Managed Git repository root must be an absolute path.");
  }
  return path.normalize(repositoryRootPath);
}

function findManagedRepositoryRootPath(managedRepositoryRootPaths, fileSystemPath) {
  if (!Array.isArray(managedRepositoryRootPaths)) {
    throw new Error("Managed Git repository roots must be an array.");
  }
  if (typeof fileSystemPath !== "string" || !path.isAbsolute(fileSystemPath)) {
    throw new Error("Workspace file event path must be absolute.");
  }

  const normalizedFileSystemPath = path.normalize(fileSystemPath);
  const matchingRepositoryRootPaths = managedRepositoryRootPaths
    .map(requireAbsoluteRepositoryRootPath)
    .filter((repositoryRootPath) => {
      const relativePath = path.relative(repositoryRootPath, normalizedFileSystemPath);
      return (
        relativePath === "" ||
        (!relativePath.startsWith(`..${path.sep}`) && relativePath !== ".." && !path.isAbsolute(relativePath))
      );
    })
    .sort((leftPath, rightPath) => rightPath.length - leftPath.length);

  return matchingRepositoryRootPaths[0] || null;
}

function repositoryFileEventShouldWake(repositoryRootPath, fileSystemPath) {
  const normalizedRepositoryRootPath = requireAbsoluteRepositoryRootPath(repositoryRootPath);
  if (typeof fileSystemPath !== "string" || !path.isAbsolute(fileSystemPath)) {
    throw new Error("Workspace file event path must be absolute.");
  }

  const relativePath = path.relative(normalizedRepositoryRootPath, path.normalize(fileSystemPath));
  if (
    relativePath.startsWith(`..${path.sep}`) ||
    relativePath === ".." ||
    path.isAbsolute(relativePath)
  ) {
    throw new Error("Workspace file event is outside the managed Git repository.");
  }

  const relativePathSegments = relativePath.split(path.sep).filter(Boolean);
  return !relativePathSegments.some((segment) =>
    REPOSITORY_EVENT_IGNORED_DIRECTORY_NAMES.includes(segment),
  );
}

function repositoryFileEventAction(repositoryRootPath, fileSystemPath, repositoryIsOpen) {
  if (typeof repositoryIsOpen !== "boolean") {
    throw new Error("Repository open state must be boolean.");
  }
  if (!repositoryFileEventShouldWake(repositoryRootPath, fileSystemPath)) {
    return REPOSITORY_FILE_EVENT_ACTION.IGNORE;
  }
  return repositoryIsOpen
    ? REPOSITORY_FILE_EVENT_ACTION.CANCEL_PENDING_CLOSE
    : REPOSITORY_FILE_EVENT_ACTION.OPEN_CLOSED_REPOSITORY;
}

module.exports = {
  REPOSITORY_FILE_EVENT_ACTION,
  countRepositoryChanges,
  findManagedRepositoryRootPath,
  repositoryFileEventAction,
  repositoryFileEventShouldWake,
  repositoryHasPendingSynchronization,
  repositoryNativeStateIsReady,
  repositoryShouldRemainVisible,
};
