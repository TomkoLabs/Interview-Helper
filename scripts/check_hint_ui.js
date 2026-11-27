/* Optional browser regression harness. Load only in an isolated development page
 * after app.js; it never ships in the application page or makes provider calls. */
"use strict";
const checkButton = node("button", "", "Run synthetic hint UI checks");
const checkResult = node("pre");
checkButton.id = "runHintChecks";
checkResult.id = "hintCheckResults";
document.body.prepend(checkButton, checkResult);
const pasteCheck = node("textarea");
pasteCheck.placeholder = "Paste copied code here to verify plain text";
pasteCheck.setAttribute("aria-label", "Code copy check");
const pasteResult = node("div");
pasteResult.id = "pasteCheckResult";
pasteCheck.oninput = () => {
  const expected = document.querySelector("#cards pre")?.dataset.code;
  pasteResult.textContent = pasteCheck.value === expected ? "PASS: copied code exactly matches source" : "Copy check: paste does not match";
};
document.body.prepend(pasteCheck, pasteResult);
checkButton.onclick = () => {
  const original = state, theme = document.documentElement.dataset.theme;
  const checks = [];
  function check(condition, label) {
    if (!condition) throw new Error(label);
    checks.push(label);
  }
  const code = "class Queue {\n  // Keep <script> literal and preserve indentation.\n" +
    Array.from({length: 35}, (_, i) => "  // Context line " + i).join("\n") +
    '\n  String label = "ready";\n  int remaining = 20;\n  Request next() {\n    return pending.peek();\n  }\n}';
  const reference = {code: "```java complete\n" + code + "\n```", status: "current", revision: 1};
  const card = {id:"check", question:"Choose the next request", guidance:"Solution in brief: Keep priority and arrival order.", answer:"Keep priority and arrival order.", reference, state:"complete", request_id:"fixture", requirements:[], review_status:"reviewed"};
  const data = {...original, session_id:"hint-ui-checks", state:"ended", drafts:[], cards:[card]};
  try {
    render(data);
    const answer = cards.get("check").answer;
    check(answer.querySelector('[data-part="followup"]').hidden, "Initial cue absent");
    check(answer.querySelector(".solution-label").textContent === "Solution in brief", "Approach labelled");
    const pre = answer.querySelector("pre"), codeNode = pre.querySelector("code");
    check(pre.textContent === code, "Highlighted text exactly equals source");
    check(!pre.querySelector("script"), "Code markup stays literal");
    check(answer.querySelectorAll("pre").length === 1, "One expanded implementation");
    // Select an unchanged expression and pause on a line in the middle of code.
    const selected = [...codeNode.querySelectorAll(".syntax-method")].find(n => n.textContent === "peek").firstChild;
    window.getSelection().setBaseAndExtent(selected, 0, selected, 4);
    following = false;
    const readLine = [...pre.querySelectorAll(".code-line")][25];
    history.scrollTop += readLine.getBoundingClientRect().top - history.getBoundingClientRect().top - 8;
    automaticScrollTop = history.scrollTop;
    const top = readLine.getBoundingClientRect().top;
    pre.scrollLeft = 10;
    const x = pre.scrollLeft;
    card.latest_followup = {text:"The next request is read with `pending.peek()`; it stays queued until capacity is available."};
    render(data);
    check(answer.querySelector("pre") === pre, "Unchanged code DOM retained");
    check(window.getSelection().toString() === "peek", "Unchanged selection retained");
    check(Math.abs(readLine.getBoundingClientRect().top - top) < 1, "Reading line retained after cue insertion");
    check(pre.scrollLeft === x, "Horizontal code position retained");
    data.drafts = [{id:card.id, question:card.question, answer:"New validated sentence, while the replacement is still arriving.", request_id:"draft-fixture"}];
    render(data);
    const previewNode = cards.get("check").preview.querySelector("p");
    render(data);
    check(cards.get("check").preview.querySelector("p") === previewNode, "Identical streaming preview DOM retained");
    check(answer.querySelector("pre") === pre, "Streaming replacement keeps complete old reference");
    data.drafts = []; render(data);

    check(answer.querySelector('[data-part="followup"]').getBoundingClientRect().top < answer.querySelector('[data-part="guidance"]').getBoundingClientRect().top, "Follow-up precedes overall solution");
    check(answer.querySelectorAll(".followup-line").length === 1, "Unique code expression marked");
    check(!answer.querySelector(".show-in-code").hidden, "Unique match exposes jump");
    answer.querySelector(".show-in-code").click();
    const target = answer.querySelector(".followup-line").getBoundingClientRect();
    const bounds = history.getBoundingClientRect();
    check(target.top >= bounds.top && target.top < bounds.bottom, "Jump reveals matching line");
    // A requirement change replaces code, while a uniquely retained selection survives.
    card.reference = {...reference, code:reference.code.replace("int remaining = 20;", "int remaining = 40;")};
    render(data);
    check(answer.querySelector("pre") !== pre && answer.querySelector("pre").textContent.includes("remaining = 40"), "Changed code is replaced");
    check(window.getSelection().toString() === "peek", "Unique unchanged selection survives replacement");
    card.latest_followup = {text:"See `Request`, then `missing()` and `return`."};
    card.reference = {...card.reference, code:card.reference.code.replace("  String label", "  // Request return\n  String label")};
    render(data);
    check(answer.querySelector(".show-in-code").hidden && !answer.querySelector(".followup-line"), "Ambiguous and absent matches omitted");
    for (const mode of ["dark", "light"]) {
      document.documentElement.dataset.theme = mode;
      check(getComputedStyle(answer.querySelector(".syntax-keyword")).color !== getComputedStyle(answer.querySelector(".syntax-string")).color, mode + " syntax categories distinct");
    }
    const saved = node("div", "answer"); document.body.append(saved);
    renderGuidance(saved, card);
    check(saved.querySelector("pre").textContent === answer.querySelector("pre").textContent, "Archive uses identical code renderer");
    saved.remove();
    render({...data, cards:[{id:"concept", question:"Explain visibility", state:"complete", answer:"Visibility does not make a compound operation atomic."}]});
    check(!cards.get("concept").answer.querySelector("pre"), "Conceptual answer has no empty code section");
    checkResult.textContent = "PASS: " + checks.length + " browser checks\n" + checks.join("\n");
  } catch (error) { checkResult.textContent = "FAIL: " + error.message + "\nPassed: " + checks.join(", "); }
  finally { window.getSelection().removeAllRanges(); document.documentElement.dataset.theme = theme; render(original); }
};
