// "Draft reply" on the dashboard.
//
// Clicking the button asks the web app (POST /api/draft-reply) to gather the thread, your
// free/busy times and past emails with the sender, and to ask the drafter service for a
// reply. The answer is shown under the email: the draft with Copy and Regenerate, the times
// it offers, the checks it passed and the past emails it used.
//
// Everything is built with textContent, never innerHTML, so email text can't add markup.
// Nothing is stored: reloading the page drops the draft.
(() => {
  // Plain-English names for the drafter's checks (src/drafter/checker.py).
  const CHECK_NAMES = {
    answer_well_formed: "The answer is complete",
    offered_times_allowed: "Offered times are free and follow your rules",
    accepted_time_allowed: "An accepted time is free and follows your rules",
    confirmed_time_on_calendar: "A confirmed meeting is on your calendar",
    no_other_times_in_text: "No other dates or times in the text",
    times_written_in_text: "The text names exactly the chosen times",
    no_outside_contact_details: "No contact details from other emails",
  };
  const LABEL_NAMES = {
    new_request: "new request", proposed_times: "proposed times", acceptance: "acceptance",
    reschedule: "reschedule", assistant_handoff: "assistant handoff", none: "not scheduling",
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(label, className, onClick) {
    const node = el("button", className, label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function list(items, className) {
    const ul = el("ul", className);
    items.forEach((item) => ul.append(typeof item === "string" ? el("li", "", item) : item));
    return ul;
  }

  function section(title, ...children) {
    const box = el("div", "draft-section");
    box.append(el("h4", "", title), ...children);
    return box;
  }

  function loading() {
    const box = el("div", "draft-loading");
    box.setAttribute("role", "status");
    box.append(el("span", "spinner"),
      el("span", "", "Drafting… reading the thread, your calendar and past emails with this sender. This takes a few seconds."));
    return box;
  }

  function checksList(checks, onlyFailed) {
    const shown = onlyFailed ? checks.filter((c) => !c.passed) : checks;
    return list(shown.map((c) => {
      const li = el("li", c.passed ? "check-ok" : "check-fail");
      li.append(el("span", "check-mark", c.passed ? "✓" : "✗"), el("span", "", CHECK_NAMES[c.name] || c.name));
      li.title = c.detail;  // the exact detail on hover
      if (!c.passed) li.append(el("span", "check-detail", c.detail));
      return li;
    }), "check-list");
  }

  async function copyDraft(textarea, status) {
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("no clipboard");
      await navigator.clipboard.writeText(textarea.value);
      status.textContent = "Copied.";
    } catch {
      // Fallback: select the text so the user can copy it themselves.
      textarea.focus();
      textarea.select();
      status.textContent = "Selected: press Ctrl+C (⌘C on a Mac) to copy.";
    }
  }

  function renderDrafted(data, retry) {
    const box = el("div", "draft-result");
    const passed = data.checks.filter((c) => c.passed).length;
    const head = el("div", "draft-head");
    head.append(el("strong", "", "Suggested reply"),
      el("span", "tag tag-ok", `All ${passed} checks passed`));
    box.append(head);
    if (data.warnings.length) box.append(list(data.warnings, "draft-warnings"));

    const textarea = el("textarea", "draft-text");
    textarea.value = data.draft_text;
    textarea.rows = Math.min(16, data.draft_text.split("\n").length + 1);
    textarea.setAttribute("aria-label", "Draft reply text (you can edit it before copying)");
    const status = el("span", "copy-status");
    status.setAttribute("aria-live", "polite");
    const actions = el("div", "draft-actions");
    actions.append(button("Copy", "btn-primary btn-small", () => copyDraft(textarea, status)),
      button("Regenerate", "btn-ghost", () => retry(true)), status);
    box.append(textarea, actions);

    const times = [];
    data.offered_times.forEach((t) => times.push(`Offers ${t.label}`));
    if (data.accepted_time) times.push(`Accepts ${data.accepted_time.label}`);
    if (data.confirmed_time) times.push(`Confirms ${data.confirmed_time.label} (on your calendar)`);
    const grid = el("div", "draft-grid");
    grid.append(section("Times", times.length ? list(times, "plain-list") : el("p", "muted", "No times in this reply.")));
    grid.append(section("Checks", checksList(data.checks, false)));
    const cited = data.context_used.filter((c) => c.cited);
    grid.append(section("Past emails used", cited.length
      ? list(cited.map((c) => {
          const li = el("li", "", `${c.subject}${c.date ? " · " + c.date : ""}`);
          li.title = c.why;
          return li;
        }), "plain-list")
      : el("p", "muted", data.context_used.length
          ? `${data.context_used.length} past email${data.context_used.length === 1 ? "" : "s"} considered, none needed.`
          : "No past emails with this sender.")));
    box.append(grid);
    box.append(el("p", "draft-note",
      `Nothing was sent. Review it, then paste it into your reply in Gmail. Times are in ${data.timezone || "your calendar's time zone"}; ` +
      `${data.model}, rules v${data.rules_version}.`));
    return box;
  }

  function renderMessage(title, text, extra, retry) {
    const box = el("div", "draft-result draft-message");
    box.append(el("strong", "", title), el("p", "", text), ...extra);
    if (retry) {
      const actions = el("div", "draft-actions");
      actions.append(button("Try again", "btn-ghost", () => retry(false)));
      box.append(actions);
    }
    return box;
  }

  function render(data, retry) {
    const warnings = data.warnings && data.warnings.length ? [list(data.warnings, "draft-warnings")] : [];
    switch (data.status) {
      case "drafted":
        return renderDrafted(data, retry);
      case "no_reply_needed":
        return renderMessage("No reply needed",
          `Fixture doesn't think this email needs a reply from you (label: ${LABEL_NAMES[data.label] || data.label}), so it didn't draft one.`,
          warnings, null);
      case "no_free_time":
        return renderMessage("No free time",
          "None of your free time in the next two weeks fits your rules, so Fixture didn't draft a reply.", warnings, null);
      case "error": {
        const failed = (data.checks || []).filter((c) => !c.passed);
        const extra = [...warnings];
        if (failed.length) extra.push(el("p", "muted", "These checks failed on both tries:"), checksList(data.checks, true));
        return renderMessage("Couldn't write a reply Fixture could verify",
          `${data.error || "Something went wrong."} Fixture never shows a draft that failed a check.`, extra, retry);
      }
      default:
        return renderMessage("Couldn't draft a reply", data.error || "Something went wrong.", [], retry);
    }
  }

  async function requestDraft(box, regenerate) {
    const panel = box.querySelector(".draft-panel");
    const trigger = box.querySelector(".btn-draft");
    trigger.disabled = true;
    panel.hidden = false;
    panel.replaceChildren(loading());
    let data;
    try {
      const response = await fetch("/api/draft-reply", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message_id: box.dataset.messageId, thread_id: box.dataset.threadId, regenerate}),
      });
      data = await response.json().catch(() => ({}));
      if (!response.ok) data = {status: "failed", error: data.error || `Request failed (${response.status}).`};
    } catch {
      data = {status: "failed", error: "Couldn't reach Fixture. Check that the web app is running, then try again."};
    }
    trigger.disabled = false;
    trigger.textContent = "Draft again";
    panel.replaceChildren(render(data, (again) => requestDraft(box, again)));
  }

  document.querySelectorAll(".draft").forEach((box) => {
    box.querySelector(".btn-draft").addEventListener("click", () => requestDraft(box, false));
  });
})();
