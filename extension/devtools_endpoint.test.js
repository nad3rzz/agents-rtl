"use strict";

const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");

const {
  devtoolsActivePortFilePathFromGlobalStoragePath,
  readDevtoolsActivePortFile,
  requireConfiguredDevtoolsPort,
  resolveConfiguredFilePath,
} = require("./devtools_endpoint");

function createTemporaryDirectory() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "agents-rtl-devtools-endpoint-test-"));
}

function removeTemporaryDirectory(temporaryDirectoryPath) {
  fs.rmSync(temporaryDirectoryPath, { recursive: true, force: true });
}

test("reads Chromium DevToolsActivePort files", () => {
  const temporaryDirectoryPath = createTemporaryDirectory();
  const activePortFilePath = path.join(temporaryDirectoryPath, "DevToolsActivePort");

  try {
    fs.writeFileSync(activePortFilePath, "41603\n/devtools/browser/example\n");
    assert.deepEqual(
      readDevtoolsActivePortFile(activePortFilePath, "agentsRtl.devtoolsActivePortFilePath"),
      { activePortFilePath, port: 41603 }
    );
  } finally {
    removeTemporaryDirectory(temporaryDirectoryPath);
  }
});

test("rejects malformed Chromium DevToolsActivePort files", () => {
  const temporaryDirectoryPath = createTemporaryDirectory();
  const activePortFilePath = path.join(temporaryDirectoryPath, "DevToolsActivePort");

  try {
    fs.writeFileSync(activePortFilePath, "not-a-port\n");
    assert.throws(
      () => readDevtoolsActivePortFile(activePortFilePath, "agentsRtl.devtoolsActivePortFilePath"),
      /first line must be a port number/
    );
  } finally {
    removeTemporaryDirectory(temporaryDirectoryPath);
  }
});

test("rejects relative active-port file paths", () => {
  assert.throws(
    () => resolveConfiguredFilePath("relative/DevToolsActivePort", "agentsRtl.devtoolsActivePortFilePath"),
    /must be an absolute path/
  );
});

test("derives the active-port file from standard VS Code global storage", () => {
  assert.equal(
    devtoolsActivePortFilePathFromGlobalStoragePath(
      "/home/example/.config/Code/User/globalStorage/nad3r.agents-rtl"
    ),
    "/home/example/.config/Code/DevToolsActivePort"
  );
});

test("derives the active-port file from a VS Code profile", () => {
  assert.equal(
    devtoolsActivePortFilePathFromGlobalStoragePath(
      "/home/example/custom-data/User/profiles/profile-id/globalStorage/nad3r.agents-rtl"
    ),
    "/home/example/custom-data/DevToolsActivePort"
  );
});

test("derives the active-port file on Windows", () => {
  assert.equal(
    devtoolsActivePortFilePathFromGlobalStoragePath(
      "C:\\Users\\example\\AppData\\Roaming\\Code\\User\\globalStorage\\nad3r.agents-rtl",
      path.win32
    ),
    "C:\\Users\\example\\AppData\\Roaming\\Code\\DevToolsActivePort"
  );
});

test("rejects unrelated global storage paths", () => {
  assert.throws(
    () => devtoolsActivePortFilePathFromGlobalStoragePath("/home/example/random/nad3r.agents-rtl"),
    /Unexpected VS Code global storage path/
  );
});

test("accepts an explicitly configured fixed DevTools port", () => {
  assert.equal(requireConfiguredDevtoolsPort(43127, "agentsRtl.devtoolsPort"), 43127);
});

test("rejects a missing fixed DevTools port", () => {
  assert.throws(
    () => requireConfiguredDevtoolsPort(null, "agentsRtl.devtoolsPort"),
    /agentsRtl\.devtoolsPort is required when using a fixed DevTools endpoint/
  );
});
