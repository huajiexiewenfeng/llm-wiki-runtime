function isSafeScopeRelativePath(value) {
  if (typeof value !== "string" || !value || value.startsWith("/") || value.includes("\\")) {
    return false;
  }
  return value.split("/").every((segment) => segment && segment !== "." && segment !== "..");
}

function encodedRelativePath(relativePath) {
  return relativePath.split("/").map((segment) => encodeURIComponent(segment)).join("/");
}

function localPathFromFileUrl(fileUrl) {
  const pathname = decodeURIComponent(fileUrl.pathname);
  if (/^\/[A-Za-z]:\//.test(pathname)) {
    return pathname.slice(1).replace(/\//g, "\\");
  }
  return pathname;
}

function wikiRootUrl(locationHref) {
  let graphUrl;
  try {
    graphUrl = new URL(locationHref);
  } catch {
    return null;
  }
  if (graphUrl.protocol !== "file:") {
    return null;
  }

  const segments = graphUrl.pathname.split("/").filter(Boolean);
  if (
    segments.length < 5 ||
    segments.at(-1) !== "graph.html" ||
    segments.at(-3) !== "graph" ||
    segments.at(-4) !== ".meta" ||
    segments.at(-5) !== ".llm-wiki"
  ) {
    return null;
  }
  return new URL("../../../", graphUrl);
}

export function resolveLocalFileAction(locationHref, relativePath) {
  if (!isSafeScopeRelativePath(relativePath)) {
    return null;
  }
  const rootUrl = wikiRootUrl(locationHref);
  if (!rootUrl) {
    return null;
  }

  const absoluteUrl = new URL(encodedRelativePath(relativePath), rootUrl);
  return {
    absolutePath: localPathFromFileUrl(absoluteUrl),
    absoluteUrl: absoluteUrl.href,
  };
}
