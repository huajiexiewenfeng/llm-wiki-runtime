import assert from "node:assert/strict";
import test from "node:test";

import { validatePackageInventory } from "../build-validation.mjs";

function inventoryFixture() {
  return {
    notices: new Map([
      ["runtime-package", "1.2.3"],
      ["builder", "4.5.6"],
      ["browser-test", "7.8.9"],
    ]),
    packageJson: {
      dependencies: { "runtime-package": "1.2.3" },
      devDependencies: { builder: "4.5.6", "browser-test": "7.8.9" },
    },
    packageLock: {
      packages: {
        "": {
          dependencies: { "runtime-package": "1.2.3" },
          devDependencies: { builder: "4.5.6", "browser-test": "7.8.9" },
        },
        "node_modules/runtime-package": { version: "1.2.3" },
        "node_modules/builder": { version: "4.5.6" },
        "node_modules/browser-test": { version: "7.8.9" },
      },
    },
    runtimePackageNames: new Set(["runtime-package"]),
  };
}

test("validatePackageInventory requires matching lock and notice versions for runtime and direct maintainer packages", () => {
  assert.doesNotThrow(() => validatePackageInventory(inventoryFixture()));
});

test("validatePackageInventory rejects notice and direct lock drift", () => {
  const noticeDrift = inventoryFixture();
  noticeDrift.notices.set("runtime-package", "9.9.9");
  assert.throws(() => validatePackageInventory(noticeDrift), /notice version mismatch/);

  const lockDrift = inventoryFixture();
  lockDrift.packageLock.packages[""].devDependencies.builder = "^4.5.6";
  assert.throws(() => validatePackageInventory(lockDrift), /root lock spec mismatch/);
});
