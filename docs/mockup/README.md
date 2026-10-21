# Fixture app mockup

The screens in the Milestone 2 web app (`src/frontend`), and what changed from our Milestone 1 wireframe once we built the skeleton.

## Milestone 1 wireframe

![Milestone 1 wireframe](ms1_wireframe.png)

## Screens today

The web app runs at http://localhost:8501. It has four screens. Every screen except sign-in shares one top bar: the Fixture logo, page links (**Dashboard** when signed in, **Search**, **How it works**) with the current page highlighted, and the account (Google photo, email, **Sign out**) or a **Sign in** button.

### 1. Sign in (`/`, signed out)

- Fixture logo, the tagline "Scheduling that runs itself.", and a **Sign in with Google** button.
- A short list of what Fixture can access: read-only Calendar and Gmail, nothing changed from the page, and only approved test accounts can sign in (the Google project is in Testing mode).
- Links to **Search past threads in the demo data** and **how Fixture works**, for anyone without a test account.
- Sign-in problems (cancelled, expired, a permission left unticked) appear as a red note above the button.

### 2. Dashboard (`/`, signed in)

- A welcome line and two status pills, "Google Calendar · Connected" and "Gmail · Connected" (red if either fails).
- Two cards side by side, stacked on phones:
  - **Upcoming events:** the next 10 events across the user's checked calendars, color-coded by calendar, with a legend.
  - **Recent emails:** the 20 most recent inbox emails. An **All / Scheduling** toggle shows only emails our keyword rules tag as scheduling. Clicking an email expands Gmail's preview and says which keyword triggered the tag.
- Everything is read-only.

### 3. Search past threads (`/search`, new in Milestone 2)

![Search past threads page](search_page.png)

- A **Demo data** badge: this page searches fake, generated mailboxes, never the signed-in Google account. That's why it works without signing in.
- A search panel:
  - **Question:** free text, e.g. "When does Professor Osei meet?". Matching is by meaning, not exact words.
  - **Mailbox:** a picker filled from the API's `GET /users`, with when that mailbox was last indexed.
  - **Label:** optional filter (New request, Proposed times, Acceptance, Reschedule, Assistant handoff, Not scheduling).
  - **Results:** top 5, 10, or 20.
  - Changing the mailbox, label, or count reruns the search right away.
  - **Try:** clickable example questions for the chosen mailbox.
- Before the first search, a short "How to search" guide.
- **Results**, best match first, each on its own card: sender (or an anonymized placeholder like `EMAIL_003`), date, a color-coded label, subject, snippet, and a match bar with the similarity score. **Show full text** expands the whole message, plus the message and thread ids it came from, so every answer can be traced to one email.
- Friendly messages instead of errors: API unreachable, no users indexed yet, unknown user (the picker asks you to choose a mailbox), and no results.

### 4. How it works (`/about`, new in Milestone 2)

![How it works page](how_it_works.png)

- **From inbox to answer:** the pipeline in five steps (ingest, preprocess, index, API, app), each a separate Docker container.
- **Private by design:** one collection per person, the mailbox is always chosen by the app (never by an AI model or by email text), and data is anonymized and read-only.
- **System status:** live checks of the API and its database, and a table of indexed mailboxes with when each was indexed. Each mailbox links to its search page.

## What changed from the Milestone 1 wireframe

The Milestone 1 wireframe shows the whole product in four steps: **connect Gmail & Calendar → set rules & priorities → Fixture schedules on its own → review the log or text it anytime**. It has four screens: Rules setup (P1–P3 priorities and preferences), Today (a calendar marking fixed, flexible, and changed-by-Fixture events), Activity log (actions, rule violations, blocked requests, Undo), and Text (a chat with Fixture).

- **Step 1 is built.** Sign in with Google, then a read-only dashboard of upcoming events and recent emails. It's a simpler version of the Today screen: a list of events, without the fixed/flexible markers yet.
- **A new screen came first: search.** The wireframe goes straight to Fixture scheduling on its own (step 3). Building the skeleton showed that the agent first needs a memory of past threads, for the right person only, before it can draft a reply or check a rule. So Milestone 2 adds "Search past threads" over an indexed, per-person store of emails.
- **Rules setup, Activity log, and Text are not built yet.** They need the rule checker and the scheduling agent, which come in later milestones.
- **A trust rule from the wireframe is already in place.** The Activity log's "Ignored: instruction inside email from unknown sender, email content can't trigger actions" is now a design rule: which mailbox to search always comes from the app, never from email text or an AI model, and each search opens only that one person's collection.
- **Demo data instead of a real inbox for search.** Our Google project is in Testing mode, so logins expire after about 7 days, and we don't want real email in the pipeline yet. Search uses generated, anonymized mailboxes and says so on screen. The dashboard still shows the real, read-only Google connection.
- **Scheduling labels became visible.** Each email has one of six labels (new request, proposed times, acceptance, reschedule, assistant handoff, not scheduling), shown as a tag on each result and usable as a filter.
- **Error states were designed in.** Building it surfaced states the wireframe didn't have: expired sign-in, a permission left unticked, a calendar that only shares free/busy, the API being down, and nothing indexed yet. Each now has a plain-language message.

## Images

All images live in this folder:

- `ms1_wireframe.png`: our Milestone 1 wireframe.
- `search_page.png` and `how_it_works.png`: screenshots of the new pages, from the running app.
