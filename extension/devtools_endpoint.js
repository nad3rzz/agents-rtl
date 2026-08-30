"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

const DEVTOOLS_ENDPOINT_SOURCE_FIXED_PORT = "fixedPort";
const DEVTOOLS_ENDPOINT_SOURCE_ACTIVE_PORT_FILE = "activePortFile";
const DEVTOOLS_ACTIVE_PORT_FILE_NAME = "DevToolsActivePort";
const USER_CONFIGURATION_DIRECTORY_NAME = "User";
const GLOBAL_STORAGE_DIRECTORY_NAME = "globalStorage";
const MIN_DEVTOOLS_PORT = 1;
const MAX_DEVTOOLS_PORT = 65535;

function validateDevtoolsPort(port, sourceName) {
  if (!Number.isInteger(port) || port < MIN_DEVTOOLS_PORT || port > MAX_DEVTOOLS_PORT) {
    throw new Error(`Invalid DevTools port from ${sourceName}: ${port}`);
  }
}

function requireConfiguredDevtoolsPort(port, sourceName) {
  if (port === undefined || port === null) {
    throw new Error(`${sourceName} is required when using a fixed DevTools endpoint.`);
  }

  validateDevtoolsPort(port, sourceName);
  return port;
}

function resolveConfiguredFilePath(configuredFilePath, settingName) {
  if (typeof configuredFilePath !== "string" || !configuredFilePath.trim()) {
    throw new Error(`${settingName} must be a non-empty absolute path.`);
  }

  const trimmedFilePath = configuredFilePath.trim();
  const expandedFilePath = trimmedFilePath === "~"
    ? os.homedir()
    : trimmedFilePath.startsWith("~/")
      ? path.join(os.homedir(), trimmedFilePath.slice(2))
      : trimmedFilePath;

  if (!path.isAbsolute(expandedFilePath)) {
    throw new Error(`${settingName} must be an absolute path: ${configuredFilePath}`);
  }

  return expandedFilePath;
}

function devtoolsActivePortFilePathFromGlobalStoragePath(globalStoragePath, pathImplementation = path) {
  if (typeof globalStoragePath !== "string" || !globalStoragePath.trim()) {
    throw new Error("VS Code global storage path must be a non-empty absolute path.");
  }

  const normalizedGlobalStoragePath = pathImplementation.normalize(globalStoragePath.trim());
  if (!pathImplementation.isAbsolute(normalizedGlobalStoragePath)) {
    throw new Error(`VS Code global storage path must be absolute: ${globalStoragePath}`);
  }

  let currentDirectoryPath = pathImplementation.dirname(normalizedGlobalStoragePath);
  if (pathImplementation.basename(currentDirectoryPath) !== GLOBAL_STORAGE_DIRECTORY_NAME) {
    throw new Error(`Unexpected VS Code global storage path: ${globalStoragePath}`);
  }

  while (pathImplementation.basename(currentDirectoryPath) !== USER_CONFIGURATION_DIRECTORY_NAME) {
    const parentDirectoryPath = pathImplementation.dirname(currentDirectoryPath);
    if (parentDirectoryPath === currentDirectoryPath) {
      throw new Error(`Cannot derive VS Code user-data directory from: ${globalStoragePath}`);
    }
    currentDirectoryPath = parentDirectoryPath;
  }

  const userDataDirectoryPath = pathImplementation.dirname(currentDirectoryPath);
  return pathImplementation.join(userDataDirectoryPath, DEVTOOLS_ACTIVE_PORT_FILE_NAME);
}

function readDevtoolsActivePortFile(configuredFilePath, settingName) {
  const activePortFilePath = resolveConfiguredFilePath(configuredFilePath, settingName);
  if (!fs.existsSync(activePortFilePath)) {
    throw new Error(`DevTools active-port file does not exist: ${activePortFilePath}`);
  }

  const fileContent = fs.readFileSync(activePortFilePath, "utf8");
  const firstLine = fileContent.split(/\r?\n/, 1)[0].trim();
  if (!/^\d+$/.test(firstLine)) {
    throw new Error(`Invalid DevTools active-port file ${activePortFilePath}: first line must be a port number.`);
  }

  const port = Number(firstLine);
  validateDevtoolsPort(port, activePortFilePath);
  return { activePortFilePath, port };
}

module.exports = {
  DEVTOOLS_ENDPOINT_SOURCE_ACTIVE_PORT_FILE,
  DEVTOOLS_ENDPOINT_SOURCE_FIXED_PORT,
  devtoolsActivePortFilePathFromGlobalStoragePath,
  readDevtoolsActivePortFile,
  requireConfiguredDevtoolsPort,
  resolveConfiguredFilePath,
  validateDevtoolsPort,
};
