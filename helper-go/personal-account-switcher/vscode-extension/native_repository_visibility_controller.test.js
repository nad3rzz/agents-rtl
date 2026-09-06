"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("native repository visibility never starts a second Git status scan", () => {
  const controllerSource = fs.readFileSync(
    path.join(__dirname, "native_repository_visibility_controller.js"),
    "utf8",
  );

  assert.doesNotMatch(controllerSource, /\.status\s*\(/);
  assert.doesNotMatch(controllerSource, /child_process/);
  assert.doesNotMatch(controllerSource, /waitForGitApiInitialization/);
  assert.match(controllerSource, /repository\.state\.onDidChange/);
  assert.match(controllerSource, /nativeRepositoryVisibilityGitApi\.onDidChangeState/);
  assert.match(controllerSource, /gitApi\.openRepository/);
  assert.match(controllerSource, /openClosedRepositoryForNativeEvaluation\(rootPath, "startup"\)/);
  assert.match(controllerSource, /executeCommand\("git\.close"/);
});
