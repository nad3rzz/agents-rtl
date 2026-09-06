"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  REPOSITORY_FILE_EVENT_ACTION,
  countRepositoryChanges,
  findClosedManagedRepositoryRootPaths,
  findManagedRepositoryRootPath,
  repositoryFileEventAction,
  repositoryFileEventShouldWake,
  repositoryHasPendingSynchronization,
  repositoryNativeStateIsReady,
  repositoryShouldRemainVisible,
} = require("./native_repository_visibility_model");

function createRepository(repositoryFileSystemPath, changeCounts, headOverrides = {}) {
  return {
    rootUri: {
      fsPath: repositoryFileSystemPath,
    },
    state: {
      HEAD: {
        commit: "0123456789abcdef",
        name: "main",
        ...headOverrides,
      },
      mergeChanges: Array(changeCounts.mergeChanges).fill({}),
      indexChanges: Array(changeCounts.indexChanges).fill({}),
      workingTreeChanges: Array(changeCounts.workingTreeChanges).fill({}),
      untrackedChanges: Array(changeCounts.untrackedChanges).fill({}),
    },
  };
}

function createCleanRepository(repositoryFileSystemPath, headOverrides = {}) {
  return createRepository(
    repositoryFileSystemPath,
    {
      mergeChanges: 0,
      indexChanges: 0,
      workingTreeChanges: 0,
      untrackedChanges: 0,
    },
    headOverrides,
  );
}

test("countRepositoryChanges includes every native Git change collection", () => {
  const repository = createRepository("/workspace/thndr", {
    mergeChanges: 1,
    indexChanges: 2,
    workingTreeChanges: 3,
    untrackedChanges: 4,
  });

  assert.equal(countRepositoryChanges(repository), 10);
});

test("repositoryShouldRemainVisible keeps changed repositories visible", () => {
  const repository = createRepository("/workspace/thndr", {
    mergeChanges: 0,
    indexChanges: 0,
    workingTreeChanges: 1,
    untrackedChanges: 0,
  });

  assert.equal(repositoryShouldRemainVisible(repository), true);
});

test("repositoryShouldRemainVisible keeps ahead and behind repositories visible", () => {
  const aheadRepository = createCleanRepository("/workspace/ahead", { ahead: 2, behind: 0 });
  const behindRepository = createCleanRepository("/workspace/behind", { ahead: 0, behind: 3 });

  assert.equal(repositoryHasPendingSynchronization(aheadRepository), true);
  assert.equal(repositoryHasPendingSynchronization(behindRepository), true);
  assert.equal(repositoryShouldRemainVisible(aheadRepository), true);
  assert.equal(repositoryShouldRemainVisible(behindRepository), true);
});

test("repositoryShouldRemainVisible hides a clean synchronized repository", () => {
  const repository = createCleanRepository("/workspace/clean");

  assert.equal(repositoryNativeStateIsReady(repository), true);
  assert.equal(repositoryHasPendingSynchronization(repository), false);
  assert.equal(repositoryShouldRemainVisible(repository), false);
});

test("repositoryNativeStateIsReady waits for native HEAD state", () => {
  const repository = createCleanRepository("/workspace/loading");
  repository.state.HEAD = undefined;

  assert.equal(repositoryNativeStateIsReady(repository), false);
  assert.throws(
    () => repositoryShouldRemainVisible(repository),
    /Git repository native state is not ready\./,
  );
});

test("countRepositoryChanges rejects an incomplete native Git state", () => {
  const repository = createCleanRepository("/workspace/broken");
  delete repository.state.untrackedChanges;

  assert.throws(
    () => countRepositoryChanges(repository),
    /Git repository state is missing untrackedChanges\./,
  );
});

test("findManagedRepositoryRootPath selects the deepest matching repository", () => {
  const repositoryRootPaths = [
    "/workspace/projects/parent",
    "/workspace/projects/parent/nested",
    "/workspace/projects/other",
  ];

  assert.equal(
    findManagedRepositoryRootPath(
      repositoryRootPaths,
      "/workspace/projects/parent/nested/src/index.js",
    ),
    "/workspace/projects/parent/nested",
  );
  assert.equal(
    findManagedRepositoryRootPath(repositoryRootPaths, "/workspace/unmanaged/file.js"),
    null,
  );
});

test("findClosedManagedRepositoryRootPaths finds repositories missing from native Git API", () => {
  const managedRepositoryRootPaths = [
    "/workspace/projects/vazoka",
    "/workspace/projects/browser",
    "/workspace/projects/thndr",
  ];
  const openRepositoryRootPaths = [
    "/workspace/projects/vazoka",
    "/workspace/projects/thndr",
  ];

  assert.deepEqual(
    findClosedManagedRepositoryRootPaths(
      managedRepositoryRootPaths,
      openRepositoryRootPaths,
    ),
    ["/workspace/projects/browser"],
  );
});

test("repositoryFileEventShouldWake ignores Git metadata and local temporary data", () => {
  const repositoryRootPath = "/workspace/projects/reloadmax";

  assert.equal(
    repositoryFileEventShouldWake(repositoryRootPath, `${repositoryRootPath}/.git/FETCH_HEAD`),
    false,
  );
  assert.equal(
    repositoryFileEventShouldWake(repositoryRootPath, `${repositoryRootPath}/nosync/data.sqlite3`),
    false,
  );
  assert.equal(
    repositoryFileEventShouldWake(repositoryRootPath, `${repositoryRootPath}/src/tmp/result.json`),
    false,
  );
  assert.equal(
    repositoryFileEventShouldWake(repositoryRootPath, `${repositoryRootPath}/src/index.js`),
    true,
  );
});

test("repositoryFileEventAction cancels a stale close when a tracked file changes", () => {
  const repositoryRootPath = "/workspace/projects/vazoka";
  const changedFilePath = `${repositoryRootPath}/.gitignore`;

  assert.equal(
    repositoryFileEventAction(repositoryRootPath, changedFilePath, true),
    REPOSITORY_FILE_EVENT_ACTION.CANCEL_PENDING_CLOSE,
  );
  assert.equal(
    repositoryFileEventAction(repositoryRootPath, changedFilePath, false),
    REPOSITORY_FILE_EVENT_ACTION.OPEN_CLOSED_REPOSITORY,
  );
});

test("repositoryFileEventAction ignores excluded file events regardless of open state", () => {
  const repositoryRootPath = "/workspace/projects/vazoka";
  const ignoredFilePath = `${repositoryRootPath}/.git/FETCH_HEAD`;

  assert.equal(
    repositoryFileEventAction(repositoryRootPath, ignoredFilePath, true),
    REPOSITORY_FILE_EVENT_ACTION.IGNORE,
  );
  assert.equal(
    repositoryFileEventAction(repositoryRootPath, ignoredFilePath, false),
    REPOSITORY_FILE_EVENT_ACTION.IGNORE,
  );
});
