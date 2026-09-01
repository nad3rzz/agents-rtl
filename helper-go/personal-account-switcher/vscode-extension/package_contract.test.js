const assert = require("node:assert/strict");
const test = require("node:test");

const extensionManifest = require("./package.json");

test("keeps the repository name visible when only one repository has changes", () => {
  assert.equal(
    extensionManifest.contributes.configurationDefaults["scm.alwaysShowRepositories"],
    true,
  );
});
