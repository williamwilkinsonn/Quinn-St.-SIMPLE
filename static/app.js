const state = {
  leads: [],
  loading: false,
};

const elements = {
  apiStatus: document.getElementById("apiStatus"),
  locationInput: document.getElementById("locationInput"),
  maxResultsInput: document.getElementById("maxResultsInput"),
  termsInput: document.getElementById("termsInput"),
  searchButton: document.getElementById("searchButton"),
  exportButton: document.getElementById("exportButton"),
  resultsBody: document.getElementById("resultsBody"),
  summaryText: document.getElementById("summaryText"),
  messageBox: document.getElementById("messageBox"),
};

function setMessage(message, tone = "neutral") {
  elements.messageBox.textContent = message;
  elements.messageBox.style.color = tone === "error" ? "#a1432a" : "#617184";
}

function setBusyState() {
  elements.searchButton.disabled = state.loading;
  elements.exportButton.disabled = state.loading || !state.leads.length;
}

function parseTerms() {
  return elements.termsInput.value
    .split("\n")
    .map((term) => term.trim())
    .filter(Boolean);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderRows() {
  if (!state.leads.length) {
    elements.resultsBody.innerHTML = `
        <tr class="empty-row">
        <td colspan="6">
          <div class="empty-state">
            <strong>No leads yet</strong>
            <p>Start with a market like Denver, Austin, or Scottsdale, then click <span>Find Stores</span>.</p>
          </div>
        </td>
        </tr>
    `;
    elements.summaryText.textContent = "No leads loaded yet.";
    setBusyState();
    return;
  }

  elements.resultsBody.innerHTML = state.leads
    .map((lead) => {
      const queryChips = (lead.matched_queries || [])
        .map((term) => `<span class="chip">${escapeHtml(term)}</span>`)
        .join("");
      const extraEmails = (lead.extra_emails || []).length
        ? `<div class="helper-text">${escapeHtml(lead.extra_emails.join(", "))}</div>`
        : "";
      const websiteBlock = lead.website
        ? `<a href="${escapeHtml(lead.website)}" target="_blank" rel="noreferrer">Website</a>`
        : "No website";
      const phoneBlock = lead.phone ? `<div>${escapeHtml(lead.phone)}</div>` : "";
      const contactPage = lead.contact_page
        ? `<div><a href="${escapeHtml(lead.contact_page)}" target="_blank" rel="noreferrer">Contact page</a></div>`
        : "";
      const mapsLink = lead.maps_url
        ? `<a href="${escapeHtml(lead.maps_url)}" target="_blank" rel="noreferrer">Open map</a>`
        : "No map link";
      const rating = lead.rating ? `Rating ${escapeHtml(lead.rating)} (${escapeHtml(lead.review_count || "0")})` : "No rating";
      return `
        <tr>
          <td>
            <strong>${escapeHtml(lead.name || "Unnamed business")}</strong>
            <div>${escapeHtml(lead.address || "")}</div>
            <div class="helper-text">${escapeHtml(lead.primary_type || lead.business_status || "")}</div>
          </td>
          <td><div class="chip-row">${queryChips}</div></td>
          <td>
            ${phoneBlock}
            <div>${websiteBlock}</div>
            ${contactPage}
          </td>
          <td>
            <div>${escapeHtml(lead.email || "No email found")}</div>
            ${extraEmails}
          </td>
          <td>
            <div class="status-badge ${escapeHtml(lead.enrichment_status || "not_run")}">
              ${escapeHtml((lead.enrichment_status || "not_run").replaceAll("_", " "))}
            </div>
            <div class="helper-text">${rating}</div>
          </td>
          <td>${mapsLink}</td>
        </tr>
      `;
    })
    .join("");

  const emailCount = state.leads.filter((lead) => lead.email).length;
  const contactPageCount = state.leads.filter((lead) => lead.contact_page).length;
  elements.summaryText.textContent = `${state.leads.length} leads loaded. ${emailCount} direct email${emailCount === 1 ? "" : "s"} found, plus ${contactPageCount} contact page${contactPageCount === 1 ? "" : "s"}.`;
  setBusyState();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const json = await response.json();
    if (!response.ok) {
      throw new Error(json.error || "Request failed.");
    }
    return json;
  }
  if (!response.ok) {
    throw new Error("Request failed.");
  }
  return response;
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    elements.apiStatus.textContent = config.hasApiKey ? "Google Places key detected" : "Google Places key missing";
    elements.apiStatus.style.background = config.hasApiKey ? "rgba(93, 162, 116, 0.18)" : "rgba(216, 132, 102, 0.16)";
    if (!elements.termsInput.value.trim() && Array.isArray(config.defaultTerms)) {
      elements.termsInput.value = config.defaultTerms.join("\n");
    }
  } catch (error) {
    elements.apiStatus.textContent = "Unable to load config";
  }
}

async function searchLeads() {
  const location = elements.locationInput.value.trim();
  if (!location) {
    setMessage("Add a city, region, or market first.", "error");
    return;
  }

  state.loading = true;
  setBusyState();
  setMessage("Looking for Quinn St.-friendly stores in that market...");
  try {
    const payload = {
      location,
      maxResults: Number(elements.maxResultsInput.value || 10),
      searchTerms: parseTerms(),
    };
    const result = await postJson("/api/search", payload);
    state.leads = result.leads || [];
    renderRows();
    setMessage(`Found ${state.leads.length} potential stores. Now checking websites for contact info...`);

    const enriched = await postJson("/api/enrich", { leads: state.leads });
    state.leads = enriched.leads || [];
    renderRows();
    const count = result.count || state.leads.length;
    const emailCount = state.leads.filter((lead) => lead.email).length;
    const contactPageCount = state.leads.filter((lead) => lead.contact_page).length;
    setMessage(`Finished ${location}: ${count} stores found, ${emailCount} direct email${emailCount === 1 ? "" : "s"}, ${contactPageCount} contact page${contactPageCount === 1 ? "" : "s"}.`);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    state.loading = false;
    setBusyState();
  }
}

async function exportLeads() {
  if (!state.leads.length) {
    setMessage("Nothing to export yet.", "error");
    return;
  }
  try {
    const response = await postJson("/api/export", { leads: state.leads });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "quinn_street_leads.csv";
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage("Your Quinn St. lead list is ready to download.");
  } catch (error) {
    setMessage(error.message, "error");
  }
}

elements.searchButton.addEventListener("click", searchLeads);
elements.exportButton.addEventListener("click", exportLeads);

setBusyState();
renderRows();
loadConfig();
