"use strict";
let connectionInitialized = false;
let microphonePreferenceError = "";
const $ = (id) => document.getElementById(id);
let csrf = "",
  following = true,
  followFromStart = true,
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
// Small lexical highlighter: only text nodes/spans, never generated HTML.
// Unknown languages retain literal text. Coloring is independent of follow-up marks.
const codeKeywords = {
  java: "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public record return sealed short static strictfp super switch synchronized this throw throws transient try var void volatile while yield true false null",
  javascript: "async await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while with yield true false null undefined",
  python: "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield True False None",
  cpp: "auto bool break case catch char class const constexpr continue default delete do double else enum explicit extern false float for friend if inline int long namespace new nullptr private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while",
  sql: "select from where join inner outer left right on group by order asc desc having limit offset insert into values update set delete create table index distinct null not and or as in exists case when then else end count sum",
};
function codeTokens(text, language) {
  const aliases = {js: "javascript", typescript: "javascript", ts: "javascript", py: "python", c: "cpp", "c++": "cpp"};
  language = aliases[language] || language;
  if (!codeKeywords[language]) return [{text, kind: ""}];
  const words = new Set(codeKeywords[language].split(" "));
  const comments = language === "python" ? /#[^\n]*/ : language === "sql"
    ? /--[^\n]*|\/\*[\s\S]*?(?:\*\/|$)/ : /\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$)/;
  const values = /"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`|\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?[fFdDlL]?\b|\b[A-Za-z_$][\w$]*\b/;
  const pattern = new RegExp(comments.source + "|" + values.source, "g");
  const tokens = [];
  let position = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > position) tokens.push({text: text.slice(position, match.index), kind: ""});
    const value = match[0];
    let kind = "";
    if (/^(\/\/|\/\*)/.test(value) || (language === "python" && value[0] === "#") || (language === "sql" && value.startsWith("--"))) kind = "comment";
    else if (/^["'`]/.test(value)) kind = "string";
    else if (/^\d/.test(value)) kind = "number";
    else if (words.has(language === "sql" ? value.toLowerCase() : value)) kind = "keyword";
    else if (/^[A-Z][A-Za-z0-9_$]*$/.test(value)) kind = "type";
    else if (/^\s*\(/.test(text.slice(match.index + value.length))) kind = "method";
    tokens.push({text: value, kind});
    position = match.index + value.length;
  }
  if (position < text.length) tokens.push({text: text.slice(position), kind: ""});
  return tokens;
}
function renderCode(text, language) {
  const pre = node("pre"), code = node("code");
  pre.dataset.code = text;
  pre.append(code);
  let line = node("span", "code-line");
  code.append(line);
  for (const token of codeTokens(text, language)) {
    token.text.split("\n").forEach((part, index) => {
      if (index) {
        code.append(document.createTextNode("\n"));
        line = node("span", "code-line"); code.append(line);
      }
      if (part) line.append(token.kind ? node("span", "syntax-" + token.kind, part) : document.createTextNode(part));
    });
  }
  return pre;
}
function codeMatches(text, followup) {
  const lines = new Set();
  for (const match of followup.matchAll(/`([^`\n]{1,160})`/g)) {
    const quote = match[1], start = text.indexOf(quote);
    if (start < 0 || text.indexOf(quote, start + 1) !== -1) continue;
    // Never match a short identifier inside another identifier.
    if ((/^[\w$]/.test(quote) && /[\w$]/.test(text[start - 1] || "")) ||
        (/[\w$]$/.test(quote) && /[\w$]/.test(text[start + quote.length] || ""))) continue;
    lines.add(text.slice(0, start).split("\n").length - 1);
  }
  return [...lines].sort((a, b) => a - b);
}
function updatePart(element, name, key, draw) {
  let part = element.querySelector(':scope > [data-part="' + name + '"]');
  if (!part) { part = node("div"); part.dataset.part = name; element.append(part); }
  if (part.renderKey !== key) {
    part.replaceChildren(); draw(part); part.renderKey = key;
  }
  part.hidden = !part.childNodes.length;
  return part;
}
function rememberSelection(element) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const parent = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
  const part = parent.closest("[data-part]");
  if (!part || !element.contains(part) || !part.contains(range.endContainer)) return null;
  const before = document.createRange(); before.selectNodeContents(part); before.setEnd(range.startContainer, range.startOffset);
  return {part: part.dataset.part, text: range.toString(), start: before.toString().length,
    source: part.textContent, anchor: selection.anchorNode, focus: selection.focusNode,
    backward: selection.anchorNode === range.endContainer && selection.anchorOffset === range.endOffset};
}
function restoreSelection(element, saved) {
  if (!saved || (saved.anchor.isConnected && saved.focus.isConnected)) return;
  const part = element.querySelector('[data-part="' + saved.part + '"]');
  if (!part) return;
  const text = part.textContent;
  const start = text === saved.source ? saved.start : text.indexOf(saved.text);
  if (start < 0 || (text !== saved.source && text.indexOf(saved.text, start + 1) !== -1)) return;
  const walker = document.createTreeWalker(part, NodeFilter.SHOW_TEXT);
  let current, offset = 0, a, b;
  while ((current = walker.nextNode())) {
    const end = offset + current.length;
    if (!a && start <= end) a = [current, start - offset];
    if (start + saved.text.length <= end) { b = [current, start + saved.text.length - offset]; break; }
    offset = end;
  }
  if (a && b) window.getSelection().setBaseAndExtent(...(saved.backward ? [...b, ...a] : [...a, ...b]));
}
function renderAnswer(element, text) {
  element.replaceChildren();
  let list = null;
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || /^[-*]\s*$/.test(line.trim())) continue;
    const fence = /^```([a-z][a-z0-9+#-]{0,19}) (snippet|complete)$/.exec(line);
    const end = fence ? lines.indexOf("```", i + 1) : -1;
    if (fence && end > i + 1) {
      list = null;
      if (fence[2] === "snippet") element.append(node("div", "code-label", "Core snippet"));
      const raw = lines.slice(i + 1, end).join("\n");
      const copy = node("button", "copy-code", "Copy code");
      copy.type = "button";
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(raw); copy.textContent = "Copied"; }
        catch { copy.textContent = "Select code to copy"; }
      };
      element.append(copy, renderCode(raw, fence[1]));
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
      textWithCode(p, line.replace(/^(?:TL;DR|Solution in brief):\s*/i, ""));
      element.append(p);
    }
  }
}
function renderGuidance(element, card) {
  const selection = rememberSelection(element);
  const followupText = card.latest_followup?.text?.trim() || "";
  // Stable regions keep unchanged reference text, selection and horizontal scroll.
  const followup = updatePart(element, "followup", followupText, part => {
    if (!followupText) return;
    part.className = "latest-followup";
    part.append(node("div", "guidance-label", "Latest follow-up"));
    const text = node("p"); textWithCode(text, followupText); part.append(text);
    const jump = node("button", "show-in-code", "Show in code");
    jump.hidden = true;
    jump.onclick = () => {
      const target = element.querySelector(".code-line.followup-line");
      if (!target) return;
      const container = element.closest("#savedDialog") || history;
      const top = container.getBoundingClientRect().top;
      container.scrollTop += target.getBoundingClientRect().top - top - 32;
      if (container === history) { following = false; automaticScrollTop = history.scrollTop; $("latestButton").hidden = false; }
    };
    part.append(jump);
  });
  updatePart(element, "focus", card.focus && !followupText ? card.focus : "", part => {
    if (card.focus && !followupText) part.append(node("div", "guidance-label", card.focus));
  });
  updatePart(element, "guidance", card.guidance || card.answer || "", part => {
    if (!card.guidance && !card.answer) return;
    part.append(node("div", "guidance-label solution-label", "Solution in brief"));
    const text = node("div"); renderAnswer(text, card.guidance || card.answer || ""); part.append(text);
  });
  const ref = card.reference;
  const warnings = [];
  if (ref?.status === "needs_revision") warnings.push("Update needed" + (ref.reason ? ": " + ref.reason : "."));
  if (ref && card.review_status === "failed") warnings.push("Latest update failed; retained code shown.");
  if (!ref && card.reference_action === "clear") warnings.push("Reference cleared: " + card.reference_reason);
  updatePart(element, "warnings", warnings.join(" "), part => {
    if (warnings.length) part.append(node("p", "reference-warning", warnings.join(" ")));
  });
  const reference = updatePart(element, "reference", ref?.code || "", part => {
    part.className = "reference-code";
    if (ref) renderAnswer(part, ref.code);
  });
  updatePart(element, "notes", ref?.notes || "", part => {
    if (ref?.notes) renderAnswer(part, ref.notes);
  });
  const facts = (card.requirements || []).filter(f => typeof f.text === "string" && f.text.trim() && !/^[-*]\s*$/.test(f.text.trim()));
  const requirementsOpen = element.querySelector(".task-requirements")?.open || false;
  updatePart(element, "requirements", JSON.stringify(facts), part => {
    if (!facts.length) return;
    const summary = node("details", "task-requirements");
    summary.open = requirementsOpen;
    summary.append(node("summary", "", "Problem requirements and assumptions"));
    const list = node("ul");
    facts.forEach(f => {
      const li = node("li", f.status === "active" ? "" : "muted", f.kind + ": " + f.text + (f.status === "active" ? "" : " · " + (f.status || "unreviewed").replaceAll("_", " ")));
      li.title = "Playback evidence: " + (f.segments || []).map(s => s + (f.evidence_revisions?.[s] ? " (revision " + f.evidence_revisions[s] + ")" : "")).join(", ") + (f.evidence_status === "source_changed" ? " · source changed" : "");
      list.append(li);
    });
    summary.append(list); part.append(summary);
  });
  const pre = reference.querySelector("pre");
  const matches = pre && ref.status !== "needs_revision" ? codeMatches(pre.dataset.code, followupText) : [];
  reference.querySelectorAll(".code-line").forEach((line, i) => line.classList.toggle("followup-line", matches.includes(i)));
  const jump = followup.querySelector(".show-in-code");
  if (jump) jump.hidden = !matches.length;
  restoreSelection(element, selection);
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api/" + path, {
    method,
    headers: method === "GET" ? {} : { "X-Interview-CSRF": csrf, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
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
  const compact = /failed|exhausted|unavailable|unconfigured|limit/i.test(value) ? "Needs attention" : value.length > 36 ? value.slice(0, 33) + "…" : value;
  $(key + "Status").textContent = compact;
  $(key + "Status").title = value;
  $(key + "Dot").className =
    "status-dot " +
    (/failed|unavailable|limit|unconfigured/i.test(value)
      ? "bad"
      : /idle|stopped/i.test(value)
        ? ""
        : "good");
}
function cardElement(card, index, expanded, activeTask) {
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
  if (entry.toggle.textContent !== card.question) entry.toggle.textContent = card.question;
  entry.status.textContent =
    (card.developing ? "Question incomplete · " : "") +
    (card.state === "complete" ? "" : card.state + " · ") +
    (card.host || "") + (card.diagnostics?.response_service_tier ? " · effective " + card.diagnostics.response_service_tier : "") +
    (activeTask && card.review_status === "pending" && card.state !== "updating" ? " · New speech awaiting review" : "");
  entry.preview.hidden = !card.preview;
  const previewSelection = rememberSelection(entry.preview);
  updatePart(entry.preview, "preview", card.preview || "", part => {
    if (!card.preview) return;
    part.append(node("b", "", "New guidance · validating replacement"));
    const content = node("div");
    renderAnswer(content, card.preview);
    part.append(content, node("small", "", "Previous reference remains below; changes apply only after validation."));
  });
  restoreSelection(entry.preview, previewSelection);
  entry.el.classList.toggle("drafting", card.state !== "complete");
  const contentKey = JSON.stringify([card.answer, card.guidance, card.reference, card.requirements, card.focus, card.review_status, card.latest_followup]);
  if (entry.lastAnswer !== contentKey) {
    renderGuidance(entry.answer, card);
    entry.lastAnswer = contentKey;
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
    followFromStart = true;
    lastSession = data.session_id;
  }
  const active = ["starting", "recording", "stopping", "save_failed"].includes(
    data.state,
  );
  $("includeMicrophone").disabled = active;
  $("includeMicrophone").checked = Boolean(data.microphone_enabled);
  const mic = data.microphone || {};
  $("useMicrophoneContext").disabled = active;
  $("useMicrophoneContext").checked = Boolean(data.microphone_context_enabled);
  $("microphoneStatus").textContent = data.microphone_enabled ? "Microphone · " + (mic.state || "idle") + (mic.outage ? " · outage unresolved" : "") : "Microphone · off";
  $("microphoneDetails").textContent = [mic.label, mic.state, mic.reason,
    mic.reference ? "Reference: " + mic.reference : "",
    mic.lag_seconds != null ? "Queue " + mic.lag_seconds + "s" : "",
    mic.buffer_seconds != null ? "Recognition buffer " + mic.buffer_seconds + "s" : "",
    mic.scheduling_seconds != null ? "Scheduling " + mic.scheduling_seconds + "s" : "",
    mic.inference_seconds != null ? "Recognition " + mic.inference_seconds + "s" : "",
    mic.attempts ? "Retry attempts " + mic.attempts : "",
    mic.last_segment_at != null ? "Last finalized speech at " + Math.floor(mic.last_segment_at) + "s" : "No finalized microphone speech yet"
  ].filter(Boolean).join(" · ");
  $("diagnostics").replaceChildren(...(mic.diagnostics || []).map(d => node("p", "", Math.floor(d.at) + "s · " + d.reason + " · attempts " + d.attempts)));
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
  $("downloadTranscript").hidden = !data.session_id;
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
  $("backendDetails").textContent =
    (cloud ? "Cloud · " : "Local · ") +
    (data.backend || []).map((e) => e.name + " / " + e.model + (e.kind !== "chat_completions" ? " · " + e.reasoning + " reasoning · requested " + e.tier + " · " + e.transport + (e.max_output_tokens ? " · " + e.max_output_tokens + " brief / " + (e.coding_output_tokens || e.max_output_tokens) + " coding tokens max" : "") : "")).join(", ");
  $("backendLabel").textContent = (data.backend || []).map(e => (e.kind === "chat_completions" ? "Local · " : e.kind === "chatgpt" ? "ChatGPT · " : "OpenAI API · ") + e.model).join(" / ") || "Transcription only";
  const shared = data.microphone_enabled && data.microphone_context_enabled ? "Playback + microphone" : "Playback only";
  $("sourceDisclosure").textContent = shared + (cloud ? " → cloud hints · audio local" : " → configured model · audio local");
  $("cloudDisclosure").textContent = "Cloud selected: " + shared.toLowerCase() + " transcript context leaves this computer for the selected provider. Audio remains local. This also applies to Review now; replay and explicit summaries use playback only.";
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
  // When reading unchanged code, guidance/preview height changes above it must
  // not move the line being read. A replacement falls back to the card anchor.
  const oldCode = anchor?.querySelector(".answer pre");
  const codeTop = oldCode?.getBoundingClientRect().top;
  const readingCode = oldCode && codeTop <= historyTop &&
    oldCode.getBoundingClientRect().bottom > historyTop;
  const codeText = readingCode ? oldCode.textContent : null;
  const readLine = readingCode ? [...oldCode.querySelectorAll(".code-line")].find(line => line.getBoundingClientRect().bottom > historyTop) : null;
  const readLineTop = readLine?.getBoundingClientRect().top;
  const ids = new Set(merged.map((c) => c.id));
  for (const [id, entry] of cards)
    if (!ids.has(id)) {
      entry.el.remove();
      cards.delete(id);
      manual.delete(id);
    }
  merged.forEach((card, i) => cardElement(card, i, i >= merged.length - 2, active && i === merged.length - 1));
  $("empty").hidden = !!merged.length;
  $("questionCount").textContent = merged.length
    ? merged.length +
      " question" +
      (merged.length === 1 ? "" : "s") +
      " · latest two expanded"
    : "Ready when you are";
  if (!following) unseen += merged.filter((c) => !previousIds.has(c.id)).length;
  if (following) {
    if (!previousIds.has(merged.at(-1)?.id)) followFromStart = true;
    history.scrollTop = history.scrollHeight;
    const latest = cards.get(merged.at(-1)?.id)?.el;
    const useful = latest?.querySelector(".revision-preview:not([hidden])") || latest;
    if (useful && followFromStart) {
      // Long code/previous revisions must not scroll the newest TL;DR out of view.
      history.scrollTop += Math.min(0, useful.getBoundingClientRect().top - historyTop);
    }
    automaticScrollTop = history.scrollTop;
  } else if (anchor?.isConnected) {
    const currentCode = anchor.querySelector(".answer pre");
    const sameLines = readLine ? [...(currentCode?.querySelectorAll(".code-line") || [])].filter(line => line.textContent === readLine.textContent) : [];
    history.scrollTop = beforeTop + (
      readingCode && currentCode?.textContent === codeText
        ? currentCode.getBoundingClientRect().top - codeTop
        : sameLines.length === 1 ? sameLines[0].getBoundingClientRect().top - readLineTop
        : anchor.getBoundingClientRect().top - anchorTop
    );
    automaticScrollTop = history.scrollTop;
  } else history.scrollTop = beforeTop;
  $("latestButton").hidden = following;
  $("latestButton").textContent =
    (unseen ? unseen + " new · " : "") + "Return to latest ↓";
  $("reviewButton").disabled = data.state !== "recording" || !data.playback_revision;
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
              (e.source_kind === "microphone" ? "Microphone" : "Playback"),
          ),
          document.createTextNode(e.text),
        );
        return p;
      }),
    );
    t.scrollTop = atBottom ? t.scrollHeight : pos;
  }
  $("provisional").textContent = [
    ...Object.values(data.provisional).filter(Boolean).map(text => "Playback: " + text),
    ...(mic.provisional ? ["Microphone: " + mic.provisional] : []),
  ].join("\n");
  const currentNotices = data.notices.filter((notice) => !notice.resolved);
  const failure = data.unsaved_count ? "Unsaved content retained. Retry saving before exit."
    : data.readable_error || microphonePreferenceError
    || Object.values(data.status).find(value => /failed|exhausted|unavailable|context limit/i.test(value))
    || (currentNotices.length ? currentNotices[currentNotices.length - 1].message : "")
    || (data.microphone_enabled && ["unavailable", "quarantined"].includes(mic.state) ? mic.reason : "");
  $("notice").textContent = failure || "";
  $("notice").hidden = !failure;
}
history.addEventListener("scroll", () => {
  if (automaticScrollTop !== null && Math.abs(history.scrollTop - automaticScrollTop) < 1) return;
  automaticScrollTop = null;
  following =
    history.scrollHeight - history.scrollTop - history.clientHeight < 55;
  if (following) {
    // A deliberate scroll to the tail must remain there across status polls.
    followFromStart = false;
    unseen = 0;
    $("latestButton").hidden = true;
  } else $("latestButton").hidden = false;
});
$("latestButton").onclick = () => {
  following = true;
  followFromStart = true;
  unseen = 0;
  history.scrollTop = history.scrollHeight;
  automaticScrollTop = history.scrollTop;
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
    const link = node("a", "", "Download readable transcript");
    link.href = "/api/sessions/" + encodeURIComponent(id) + "/transcript";
    detail.append(
      node("h3", "", data.metadata.microphone || data.events.some(e => e.source_kind === "microphone") ? "Captured Playback + Microphone" : "Captured playback / remote conversation"),
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
      renderGuidance(answer, h);
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

$("includeMicrophone").addEventListener("change", async () => {
  const enabled = $("includeMicrophone").checked;
  microphonePreferenceError = "";
  $("includeMicrophone").disabled = true;
  try {
    await api("microphone", "POST", {enabled});
  } catch (error) {
    microphonePreferenceError = error.message;
  }
  await poll();
});

$("useMicrophoneContext").addEventListener("change", async () => {
  microphonePreferenceError = "";
  $("useMicrophoneContext").disabled = true;
  try { await api("microphone-context", "POST", {enabled: $("useMicrophoneContext").checked}); }
  catch (error) { microphonePreferenceError = error.message; }
  await poll();
});
