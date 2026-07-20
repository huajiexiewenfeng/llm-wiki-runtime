function readPayload() {
  const element = document.getElementById("graph-index-data");
  if (element?.textContent) return JSON.parse(element.textContent);
  if (window.__LLM_WIKI_GRAPH_INDEX__) return window.__LLM_WIKI_GRAPH_INDEX__;
  throw new Error("graph index data is missing");
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function indexApp() {
  const payload = readPayload();
  const domains = [...(payload.domains ?? [])].sort((left, right) => compareText(left.id, right.id));
  const root = document.getElementById("graph-index-app") || document.body;
  root.id = "graph-index-app";
  root.replaceChildren();

  const main = document.createElement("main");
  main.style.cssText = "max-width:960px;margin:32px auto;padding:0 20px;color:#172033;font:14px/1.4 system-ui,sans-serif";
  const heading = document.createElement("h1");
  heading.textContent = payload.title || "Domain graphs";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Filter domains";
  search.setAttribute("aria-label", "Filter domains");
  search.style.cssText = "box-sizing:border-box;width:100%;height:36px;padding:0 10px;border:1px solid #94a3b8;border-radius:4px";
  const list = document.createElement("section");
  list.style.cssText = "display:grid;gap:10px;margin-top:18px";
  main.append(heading, search, list);
  root.append(main);

  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    list.replaceChildren();
    for (const domain of domains.filter((item) => `${item.id} ${item.display_name || ""}`.toLocaleLowerCase().includes(query))) {
      const row = document.createElement("article");
      row.style.cssText = "border:1px solid #cbd5e1;border-radius:6px;padding:14px;background:#fff";
      const link = document.createElement("a");
      link.href = `${domain.id}/graph.html`;
      link.textContent = domain.display_name || domain.id;
      link.style.cssText = "color:#0f766e;font-weight:700;text-decoration:none";
      const summary = document.createElement("p");
      const counts = domain.counts || domain.stats || {};
      summary.textContent = `${counts.nodes ?? 0} nodes, ${counts.edges ?? 0} edges | ${domain.status || "unknown"} | ${domain.last_success_at || "No successful export"}`;
      const messages = document.createElement("p");
      messages.textContent = [...(domain.warnings || []), ...(domain.errors || [])].join(" | ") || "No warnings or errors";
      row.append(link, summary, messages);
      list.append(row);
    }
  }

  search.addEventListener("input", render);
  render();
}

indexApp();
