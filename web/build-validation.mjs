function exactVersion(value) {
  return typeof value === "string" && /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(value);
}

function directDependencySpecs(packageJson) {
  return ["dependencies", "devDependencies"].flatMap((section) =>
    Object.entries(packageJson[section] ?? {}).map(([name, version]) => ({ name, section, version })),
  );
}

export function packageNameFromInput(input) {
  const match = input.match(/[\\/]node_modules[\\/](@[^\\/]+[\\/])?([^\\/]+)/);
  return match ? `${match[1] || ""}${match[2]}`.replace(/\\/g, "/") : null;
}

export function listedNoticePackages(notices) {
  return new Map(
    [...notices.matchAll(/^\|\s*`([^`]+)`\s*\|\s*`?([^|`\s]+)`?\s*\|/gm)].map((match) => [match[1], match[2]]),
  );
}

export function runtimePackageNames(metafiles) {
  return new Set(
    metafiles.flatMap((metafile) => Object.keys(metafile.inputs).map(packageNameFromInput).filter(Boolean)),
  );
}

function validateLockedNotice(packageName, packages, notices) {
  const lockedVersion = packages[`node_modules/${packageName}`]?.version;
  if (!exactVersion(lockedVersion)) {
    throw new Error(`package is missing an exact locked version: ${packageName}`);
  }
  if (notices.get(packageName) !== lockedVersion) {
    throw new Error(`notice version mismatch for ${packageName}: expected ${lockedVersion}`);
  }
  return lockedVersion;
}

export function validatePackageInventory({ notices, packageJson, packageLock, runtimePackageNames: runtimePackages }) {
  const packages = packageLock.packages ?? {};
  const rootLock = packages[""] ?? {};
  const directPackages = directDependencySpecs(packageJson);

  for (const { name, section, version } of directPackages) {
    if (!exactVersion(version)) {
      throw new Error(`direct package must use an exact version: ${name}`);
    }
    if (rootLock[section]?.[name] !== version) {
      throw new Error(`root lock spec mismatch for ${name}`);
    }
    const lockedVersion = validateLockedNotice(name, packages, notices);
    if (lockedVersion !== version) {
      throw new Error(`direct package locked version mismatch for ${name}: expected ${version}`);
    }
  }

  for (const packageName of [...runtimePackages].sort()) {
    validateLockedNotice(packageName, packages, notices);
  }
}
