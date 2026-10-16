"use strict";
let connectionInitialized = false;
const $ = (id) => document.getElementById(id);
let csrf = "",
  following = true,
  automaticScrollTop = null,
  unseen = 0,
  lastSession = null,
  state;
const visibleHints = new Set();
const cards = new Map(),
  manual = new Map();
const history = $("history");
function node(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function textWithCode(parent, text) {
  text
    .split(/(`[^`]+`)/g)
    .forEach((part) =>
      parent.append(
        part.startsWith("`") && part.endsWith("`")
          ? node("code", "", part.slice(1, -1))
          : document.createTextNode(part),
      ),
    );
}
function renderAnswer(element, text) {
  element.replaceChildren();
  let list = null;
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = /^```([a-z][a-z0-9+#-]{0,19}) (snippet|complete)$/.exec(line);
    const end = fence ? lines.indexOf("```", i + 1) : -1;
    if (fence && end > i + 1) {
      list = null;
      element.append(node("div", "code-label", fence[1] + (fence[2] === "snippet" ? " · core snippet" : " · implementation")));
      const pre = node("pre");
      pre.append(node("code", "", lines.slice(i + 1, end).join("\n")));
      element.append(pre);
      i = end;
      continue;
    }
    if (line.startsWith("- ")) {
      if (!list) {
        list = node("ul");
        element.append(list);
      }
      const li = node("li");
      textWithCode(li, line.slice(2));
      list.append(li);
    } else {
      list = null;
      const p = node("p");
      textWithCode(p, line);
      element.append(p);
    }
  }
}
async function api(path, method = "GET") {
  const response = await fetch("/api/" + path, {
    method,
    headers: method === "GET" ? {} : { "X-Interview-CSRF": csrf },
  });
  if (!response.ok) {
    let message = "Request failed (" + response.status + ")";
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
function setStatus(key, value) {
  $(key + "Status").textContent = value;
  $(key + "Dot").className =
    "status-dot " +
    (/failed|unavailable|limit|unconfigured/i.test(value)
      ? "bad"
      : /idle|stopped/i.test(value)
        ? ""
        : "good");
}
function cardElement(card, index, expanded) {
  let entry = cards.get(card.id);
  if (!entry) {
    const el = node("article", "card");
    el.dataset.id = card.id;
    const head = node("div", "card-head"),
      number = node("span", "card-number"),
      toggle = node("button", "card-toggle"),
      chevron = node("span", "card-chevron");
    head.append(number, toggle, chevron);
    const status = node("div", "card-status"),
      answer = node("div", "answer");
    const preview = node("div", "revision-preview");
    preview.hidden = true;
    el.append(head, status, preview, answer);
    entry = { el, number, toggle, chevron, status, preview, answer, lastAnswer: null };
    cards.set(card.id, entry);
    $("cards").append(el);
    toggle.addEventListener("click", () => {
      manual.set(card.id, !entry.answer.hidden);
      entry.answer.hidden = !entry.answer.hidden;
      entry.preview.hidden = entry.answer.hidden || !entry.preview.textContent;
      entry.toggle.setAttribute("aria-expanded", String(!entry.answer.hidden));
      entry.chevron.textContent = entry.answer.hidden ? "+" : "−";
    });
  }
  entry.number.textContent = String(index + 1).padStart(2, "0");
  entry.toggle.textContent = card.question;
  entry.status.textContent =
    (card.developing ? "Developing question · " : "") +
    (card.state === "complete" ? "" : card.state + " · ") +
    (card.host || "") + (card.diagnostics?.response_service_tier ? " · effective " + card.diagnostics.response_service_tier : "");
  entry.preview.replaceChildren();
  entry.preview.hidden = !card.preview;
  if (card.preview) {
    entry.preview.append(node("b", "", "New guidance · validating replacement"));
    const content = node("div");
    renderAnswer(content, card.preview);
    entry.preview.append(content, node("small", "", "Previous answer below; replaced together after validation."));
  }
  entry.el.classList.toggle("drafting", card.state !== "complete");
  if (entry.lastAnswer !== card.answer) {
    renderAnswer(entry.answer, card.answer);
    entry.lastAnswer = card.answer;
  }
  const open = manual.has(card.id) ? !manual.get(card.id) : expanded;
  entry.answer.hidden = !open;
  entry.preview.hidden = !card.preview || !open;
  entry.toggle.setAttribute("aria-expanded", String(open));
  entry.chevron.textContent = open ? "−" : "+";
  if (open && card.answer && (card.state !== "updating" || card.preview) && !visibleHints.has(card.request_id)) {
    visibleHints.add(card.request_id);
    if (visibleHints.size > 256) visibleHints.delete(visibleHints.values().next().value);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!document.hidden && entry.el.isConnected && !entry.answer.hidden && entry.answer.getBoundingClientRect().bottom > 0 && entry.answer.getBoundingClientRect().top < window.innerHeight) {
        fetch("/api/hint-visible", {method: "POST", headers: {"Content-Type": "application/json", "X-Interview-CSRF": csrf}, body: JSON.stringify({request_id: card.request_id})}).catch(() => {});
      } else visibleHints.delete(card.request_id);
    }));
  }
  return entry.el;
}
function render(data) {
  state = data;
  csrf = data.csrf;
  $("connection").textContent = "Connected locally";
  $("version").textContent = "v" + data.version;
  if (lastSession !== data.session_id) {
    cards.clear();
    manual.clear();
    $("cards").replaceChildren();
    unseen = 0;
    following = true;
    lastSession = data.session_id;
  }
  const active = ["starting", "recording", "stopping", "save_failed"].includes(
    data.state,
  );
  $("startButton").hidden = active;
  $("endButton").hidden = !active;
  $("endButton").disabled = data.state === "stopping";
  $("modeBadge").textContent = data.state.toUpperCase().replace("_", " ");
  $("liveDot").classList.toggle("active", data.state === "recording");
  $("sessionLabel").textContent = active
    ? "SESSION IN PROGRESS"
    : data.state === "ended"
      ? "SESSION SAVED"
      : "Ready";
  $("savedLocation").hidden = !data.transcript_path;
  $("transcriptPath").textContent = data.transcript_path ? "Transcript: " + data.transcript_path : "";
  $("downloadTranscript").href = "/api/sessions/" + encodeURIComponent(data.session_id || "") + "/transcript";
  $("downloadTranscript").hidden = data.state !== "ended" && data.state !== "failed";
  $("readableError").textContent = data.readable_error || "";
  const cloud = (data.backend || []).some((e) => e.kind !== "chat_completions");
  if (!connectionInitialized) {
    connectionInitialized = true;
    const selected = (data.backend || []).find(e => e.kind !== "chat_completions");
    if (selected) {
      $("cloudProvider").value = selected.kind;
      if (selected.account) $("cloudAccount").value = selected.account;
      $("cloudModel").replaceChildren(new Option(selected.model + " · selected", selected.model));
      $("cloudReasoning").value = selected.reasoning;
      $("cloudTier").value = selected.tier;
      $("cloudTransport").value = selected.transport;
      tierAvailability();
    }
  }
  $("cloudDisclosure").hidden = !cloud;
  $("backendLabel").textContent =
    (cloud ? "Cloud · " : "Local · ") +
    (data.backend || []).map((e) => e.name + " / " + e.model + (e.kind !== "chat_completions" ? " · " + e.reasoning + " reasoning · requested " + e.tier + " · " + e.transport + (e.max_output_tokens ? " · " + e.max_output_tokens + " output tokens max" : "") : "")).join(", ");
  if (!(data.backend || []).length) $("backendLabel").textContent = "Local · no hint model configured; transcription only";
  const seconds = data.elapsed;
  $("timer").textContent =
    String(Math.floor(seconds / 60)).padStart(2, "0") +
    ":" +
    String(seconds % 60).padStart(2, "0");
  Object.entries(data.status).forEach(([key, value]) => setStatus(key, value));
  $("hosts").replaceChildren(
    ...Object.entries(data.hosts).map(([name, status]) =>
      node("div", "", name + " · " + status),
    ),
  );
  $("hosts").hidden = !Object.keys(data.hosts).length;
  $("retrySave").hidden = !data.unsaved_count;
  $("devices").replaceChildren(
    ...data.devices.map((d) => {
      const e = node("div", "device");
      e.append(
        node("strong", "", d.label),
        node(
          "small",
          "",
          d.state + (d.lag_seconds ? " · " + d.lag_seconds + "s lag" : ""),
        ),
      );
      const meter = node("progress", "meter");
      meter.max = 1;
      meter.value = d.level || 0;
      meter.setAttribute("aria-label", d.label + " activity");
      e.append(meter);
      return e;
    }),
  );
  if (!data.devices.length)
    $("devices").append(
      node(
        "p",
        "muted",
        active
          ? "Waiting for playback devices…"
          : "Playback devices appear when your session starts.",
      ),
    );
  const merged = data.cards.map((c) => ({ ...c }));
  data.drafts.forEach((d) => {
    const i = merged.findIndex((c) => c.id === d.id);
    if (i >= 0) {
      // Keep useful previous text while an update is being generated.
      merged[i].state = "updating";
      merged[i].preview = d.answer;
      merged[i].request_id = d.request_id;
    } else merged.push(d);
  });
  const beforeTop = history.scrollTop;
  const previousIds = new Set(cards.keys());
  const historyTop = history.getBoundingClientRect().top;
  const anchor = [...cards.values()].find(
    ({ el }) => el.getBoundingClientRect().bottom > historyTop,
  )?.el;
  const anchorTop = anchor?.getBoundingClientRect().top;
  const ids = new Set(merged.map((c) => c.id));
  for (const [id, entry] of cards)
    if (!ids.has(id)) {
      entry.el.remove();
      cards.delete(id);
      manual.delete(id);
    }
  merged.forEach((card, i) => cardElement(card, i, i >= merged.length - 2));
  $("empty").hidden = !!merged.length;
  $("questionCount").textContent = merged.length
    ? merged.length +
      " question" +
      (merged.length === 1 ? "" : "s") +
      " · latest two expanded"
    : "Ready when you are";
  if (!following) unseen += merged.filter((c) => !previousIds.has(c.id)).length;
  if (following) {
    history.scrollTop = history.scrollHeight;
    const latest = cards.get(merged.at(-1)?.id)?.el;
    const useful = latest?.querySelector(".revision-preview:not([hidden])") || latest;
    if (useful) {
      // Long code/previous revisions must not scroll the newest TL;DR out of view.
      history.scrollTop += Math.min(0, useful.getBoundingClientRect().top - historyTop);
    }
    automaticScrollTop = history.scrollTop;
  } else if (anchor?.isConnected)
    history.scrollTop =
      beforeTop + anchor.getBoundingClientRect().top - anchorTop;
  else history.scrollTop = beforeTop;
  $("latestButton").hidden = following;
  $("latestButton").textContent =
    (unseen ? unseen + " new · " : "") + "Return to latest ↓";
  $("reviewButton").disabled = data.state !== "recording" || !data.transcript.length;
  if ($("transcriptPanel").open) {
    const t = $("transcript"),
      atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
    const pos = t.scrollTop;
    t.replaceChildren(
      ...data.transcript.map((e) => {
        const p = node("p");
        p.append(
          node(
            "b",
            "",
            Math.floor(e.start / 60) +
              ":" +
              String(Math.floor(e.start % 60)).padStart(2, "0") +
              " · " +
              e.source_name,
          ),
          document.createTextNode(e.text),
        );
        return p;
      }),
    );
    t.scrollTop = atBottom ? t.scrollHeight : pos;
  }
  $("provisional").textContent = Object.values(data.provisional)
    .filter(Boolean)
    .join("\n");
  $("notice").textContent = data.notices.length
    ? data.notices[data.notices.length - 1].message
    : "";
}
history.addEventListener("scroll", () => {
  if (automaticScrollTop !== null && Math.abs(history.scrollTop - automaticScrollTop) < 1) return;
  automaticScrollTop = null;
  following =
    history.scrollHeight - history.scrollTop - history.clientHeight < 55;
  if (following) {
    unseen = 0;
    $("latestButton").hidden = true;
  } else $("latestButton").hidden = false;
});
$("latestButton").onclick = () => {
  following = true;
  unseen = 0;
  history.scrollTop = history.scrollHeight;
  $("latestButton").hidden = true;
};
async function action(path) {
  try {
    await api(path, "POST");
    await poll();
  } catch (error) {
    $("notice").textContent = error.message;
  }
}
$("startButton").onclick = () => action("start");
$("endButton").onclick = () => action("end");
$("reviewButton").onclick = () => action("review-now");
$("retrySave").onclick = () => action("retry-save");
$("resetContext").onclick = () => action("reset-context");
function size(value) {
  $("textSize").value = value;
  document.documentElement.style.setProperty(
    "--answer-size",
    $("textSize").value + "px",
  );
}
$("textSize").oninput = () => size($("textSize").value);
$("smaller").onclick = () => size(Number($("textSize").value) - 1);
$("larger").onclick = () => size(Number($("textSize").value) + 1);
$("closeSaved").onclick = () => $("savedDialog").close();
$("sessionsButton").onclick = async () => {
  try {
    const sessions = await api("sessions");
    $("savedList").replaceChildren();
    $("savedDetail").replaceChildren();
    for (const s of sessions) {
      const row = node("div", "saved-row"),
        label = node("div", "", new Date(s.started || 0).toLocaleString());
      label.append(
        node(
          "small",
          "",
          s.active
            ? "Active session"
            : s.status === "recording"
              ? "Interrupted · recoverable"
              : s.status,
        ),
      );
      const button = node("button", "", "Open session");
      button.onclick = () => openSaved(s.id);
      row.append(label, button);
      $("savedList").append(row);
    }
    if (!sessions.length)
      $("savedList").append(
        node("p", "muted", "Your first saved session will appear here."),
      );
    $("savedDialog").showModal();
  } catch (error) {
    $("notice").textContent = error.message;
  }
};
async function openSaved(id) {
  try {
    const data = await api("sessions/" + encodeURIComponent(id));
    const detail = $("savedDetail");
    detail.replaceChildren();
    const link = node("a", "", "Download playback transcript");
    link.href = "/api/sessions/" + encodeURIComponent(id) + "/transcript";
    detail.append(
      node("h3", "", "Captured playback / remote conversation"),
      link,
    );
    if (data.partial_tail)
      detail.append(
        node(
          "p",
          "",
          "Recovered complete records; final partial record excluded.",
        ),
      );
    detail.append(node("p", "", "Transcript: " + data.transcript_path));
    if (data.metadata.readable_error) detail.append(node("p", "", data.metadata.readable_error));
    detail.append(node("p", "", data.readable));
    detail.append(node("h3", "", "Generated hints — not spoken conversation"));
    const latest = new Map();
    data.hints
      .filter((h) => h.type === "hint")
      .forEach((h) => latest.set(h.id, h));
    latest.forEach((h) => {
      detail.append(node("b", "", h.question));
      const answer = node("div", "answer");
      renderAnswer(answer, h.answer);
      detail.append(answer);
    });
  } catch (error) {
    $("savedDetail").textContent = error.message;
  }
}
let polling = false, pollAgain = false;
async function poll() {
  if (polling) { pollAgain = true; return; }
  polling = true;
  try {
    render(await api("state"));
  } catch (error) {
    $("connection").textContent = "Reconnecting…";
    $("notice").textContent =
      "Connection lost. The backend continues capture and saving while running.";
  } finally {
    polling = false;
    if (pollAgain) { pollAgain = false; queueMicrotask(poll); }
  }
}
poll();
setInterval(poll, 700);
async function watchHints() {
  let revision = -1;
  while (true) {
    try {
      const update = await api("updates?after=" + revision);
      revision = update.hint_revision;
      await poll();
    } catch { await new Promise(resolve => setTimeout(resolve, 2000)); }
  }
}
watchHints();

const themeToggle = $("themeToggle");
function reflectTheme() {
  const dark = document.documentElement.dataset.theme !== "light";
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.textContent = dark ? "Dark" : "Light";
}
reflectTheme();
themeToggle.addEventListener("click", () => {
  const theme =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("ih-theme", theme);
  } catch {}
  reflectTheme();
});

async function cloudRequest(path, body = {}) {
  const response = await fetch("/api/cloud/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Interview-CSRF": csrf },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.detail || "Connection request failed");
  return result;
}
function cloudChoice() {
  return {
    provider: $("cloudProvider").value,
    account: $("cloudAccount").value,
  };
}
async function refreshAccounts() {
  const response = await api("cloud/accounts");
  const selected = $("cloudAccount").value || (state?.backend || []).find(e => e.kind === "chatgpt")?.account || "";
  $("cloudAccount").replaceChildren(
    new Option("New account / workspace", ""),
    ...response.map(
      (a) =>
        new Option(
          a.label +
            (a.connected
              ? a.plan_enabled
                ? " · plan enabled"
                : " · plan disabled"
              : " · signed out"),
          a.id,
        ),
    ),
  );
  if (response.some((a) => a.id === selected))
    $("cloudAccount").value = selected;
  $("cloudStatus").textContent = response.some((a) => a.connected)
    ? "Saved sign-in available. Select an account, load its models, then choose cloud."
    : "No ChatGPT sign-in saved. API keys are configured separately on the backend.";
}
function connectionAction(id, action) {
  $(id).addEventListener("click", async () => {
    $(id).disabled = true;
    try {
      const result = await action();
      if (result?.message) $("cloudStatus").textContent = result.message;
      await poll();
    } catch (error) {
      $("cloudStatus").textContent = error.message;
    } finally {
      $(id).disabled = false;
    }
  });
}
connectionAction("cloudLogin", async () => {
  const result = await cloudRequest("sign-in", {
    account: $("cloudAccount").value,
  });
  window.location.assign(result.url);
});
connectionAction("cloudLogout", async () => {
  const result = await cloudRequest("sign-out", {
    account: $("cloudAccount").value,
  });
  await refreshAccounts();
  return result;
});
connectionAction("cloudModels", async () => {
  const models = await cloudRequest("models", cloudChoice());
  $("cloudModel").replaceChildren(
    ...models.map((m) => new Option(m.name, m.id)),
  );
  const preferred = $("cloudProvider").value === "chatgpt" ? "gpt-6-luna" : "gpt-6.1-sol";
  if (models.some(m => m.id === preferred)) $("cloudModel").value = preferred;
  return {
    message:
      models.length +
      " account models returned. Reasoning support is checked on inference.",
  };
});
connectionAction("cloudSelect", () =>
  cloudRequest("select", {
    ...cloudChoice(),
    model: $("cloudModel").value,
    reasoning: $("cloudReasoning").value,
    tier: $("cloudTier").value,
    transport: $("cloudTransport").value,
    send_transcript_to_openai: true,
  }),
);
connectionAction("localSelect", () => cloudRequest("local"));
for (const id of ["cloudAccount", "cloudProvider"])
  $(id).addEventListener("change", () => $("cloudModel").replaceChildren());
refreshAccounts().catch(() => {});

function tierAvailability() {
  $("cloudTier").disabled = $("cloudProvider").value !== "openai_api";
  if ($("cloudTier").disabled) $("cloudTier").value = "default";
}
$("cloudProvider").addEventListener("change", () => {
  $("cloudTier").value = $("cloudProvider").value === "chatgpt" ? "default" : "ultrafast";
  tierAvailability();
  $("cloudTransport").value = $("cloudProvider").value === "chatgpt" ? "websocket" : "http";
});
tierAvailability();
