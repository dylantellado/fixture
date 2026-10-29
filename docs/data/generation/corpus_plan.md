# Fake email corpus: master plan

This folder is the "bible" for the fake email corpus. Every thread is planned here
before it is written, so the data stays consistent and anyone (a person or an AI
session) can pick up where the last one stopped.

Files:
- `corpus_plan.md` (this file): goals, format, label rules, writing rules
- `shared_contacts.md`: people who appear in more than one user's inbox
- `shared_messages.md`: mailing-list emails that appear word for word in several inboxes
- `user_01.md` to `user_04.md`: one student each: who they are, their contacts
  and habits, and a numbered outline of every thread to write

Output (git-ignored, versioned with DVC later):
- `data/source/users.json`
- `data/source/batches/user_XX_bN.jsonl` (written in batches of about 10 threads)
- `data/source/generated_threads.jsonl` (all batches merged)

## Goals

1. **Retrieval has real answers.** Each user has 5 to 7 recurring contacts with
   consistent habits (days, times, format) that show up in 3+ threads.
2. **User isolation is testable.** Six contacts appear in more than one inbox
   with *different* details per user, so a cross-user leak in search is obvious.
3. **Useful for a classifier later.** Every user has all six labels, and about a
   quarter of messages are `none`, half of those "hard negatives" that mention dates
   or times but are not scheduling.
4. **Preprocess has real cleaning to do.** Quoted replies, signatures, forwards,
   footers, messy whitespace, varied length and tone, five time zones.
5. **Entirely fictional.** No real people, firms, addresses or phone numbers.

## Size and targets

4 users x 40 threads = **160 threads, about 375 messages** (2 to 7 messages per
scheduling thread, 1 to 2 per non-scheduling thread). A few threads end open (a
reschedule nobody has answered yet), like a real inbox mid-negotiation.

Planned label mix, by message, counted from the outlines (each user is similar, and
every user has all six labels):

| Label | Planned | Notes |
|---|---|---|
| `acceptance` | 101 (27%) | High because nearly every negotiation ends with one |
| `none` | 96 (25%) | About half are hard negatives (deadlines, events, auto-confirmations, newsletters with dates) |
| `proposed_times` | 79 (21%) | |
| `new_request` | 51 (14%) | Lower than you might expect: first emails that already include times count as `proposed_times` (see priority rule) |
| `reschedule` | 41 (11%) | |
| `assistant_handoff` | 9 (2%) | |

If an outline changes, recount (a small script reads the Labels column) and update this table.

A real inbox is ~90% non-scheduling. This corpus is deliberately more balanced so a
classifier sees enough of each label; scores measured on it will look better than
they would on a real inbox. Say so wherever we report numbers.

## Users

| user_id | Name | Who | Home time zone | Writing style |
|---|---|---|---|---|
| user_01 | Priya Shah | Economics junior, finance recruiting (banking, private equity) | ET | polished, short |
| user_02 | Marcus Bell | CS senior, software new-grad jobs and startups, lots of coffee chats | ET (many contacts in PT) | casual, lowercase-ish, quick |
| user_03 | Sofia Okafor | First-year data science master's, consulting recruiting, TA for a stats course | ET | long, careful, thorough |
| user_04 | Lena Fischer | International sophomore (from Germany), fall study-abroad term in London, cold-emails labs and alumni | London | eager, formal, slightly over-polite |

The students are all at one unnamed university ("the College", domain
`college.example`). Never name a real university.

## Source record format

`generated_threads.jsonl`: one thread per line. Matches the README "Data contract".

```json
{
  "user_id": "user_01",
  "thread_id": "t001",
  "subject": "Advising appointment",
  "participants": ["Priya Shah <priya.shah@example.com>", "Dana Whitfield <dana.whitfield@careers.college.example>"],
  "messages": [
    {
      "sender": "Priya Shah <priya.shah@example.com>",
      "recipients": ["Dana Whitfield <dana.whitfield@careers.college.example>"],
      "timestamp": "Thu, 03 Sep 2026 10:02:00 -0400",
      "body": "Hi Dana,\n\nCould I book an advising appointment ...\n\nBest,\nPriya",
      "label": "new_request"
    }
  ]
}
```

Rules:
- `thread_id` is `t001` to `t040`, matching the outline number. Unique within a user only.
- `participants` lists everyone who appears in the thread, in `Name <address>` form.
- `recipients` includes To and Cc. Always a list.
- `timestamp` is the email "Date" header format: `Ddd, DD Mon YYYY HH:MM:SS +HHMM`,
  in the **sender's** local time zone (table below). Preprocess converts it to ISO 8601.
- Messages are in time order, and each reply is later than the message before it.
- `subject` is the thread subject; replies don't change it (the "Re:" lives in the body quote headers only).
- `body` is the raw email text, with quotes, signatures and footers left in. Preprocess cleans it.

## Time zones (fall 2026)

| Zone | Offset in this corpus | Used by |
|---|---|---|
| US Eastern (ET) | `-0400` (DST ends Nov 1, after that `-0500`) | most students and contacts |
| US Central (CT) | `-0500` | Brightwater Strategy Group (Chicago) |
| US Pacific (PT) | `-0700` | Marcus's startup and tech contacts |
| London | `+0100` (clocks go back Oct 25, after that `+0000`) | Lena, Rohan Mehta, Lena's study-abroad office |
| Berlin | `+0200` (after Oct 25, `+0100`) | Jonas Weber, Lena's family |
| India (IST) | `+0530` | Arjun Nair |
| Lagos (WAT) | `+0100` | Sofia's sister |

All emails are dated **Sep 1 to Oct 18, 2026**, so sent timestamps never cross a
DST change. Meetings *discussed* in the emails can fall later (into November).
When a meeting is after Oct 25 / Nov 1, the London-to-ET gap changes. A few
threads use this on purpose (marked `TZ` in the outlines).

## Labels

One label per message, describing **that message's** main purpose:

| Label | Use when the message... | Example |
|---|---|---|
| `new_request` | asks to set up a meeting but gives no specific times | "Could we find 20 minutes to talk about my project?" |
| `proposed_times` | offers or counter-offers specific times | "I'm free Tue 2-4 or Wed after 1." |
| `acceptance` | confirms a specific time (including picking one of the offered times) | "Tuesday at 2:30 works, see you then." |
| `reschedule` | moves or cancels a meeting that was **already confirmed** | "Something came up, can we move Thursday to Friday?" |
| `assistant_handoff` | hands scheduling to someone else (an assistant, coordinator, lab manager, co-TA) | "Copying Tess, who will find a time with you." |
| `none` | anything else | newsletters, deadlines, thank-yous, logistics for a meeting already set |

**Priority rule for mixed messages** (pick the first that applies):
1. `reschedule`: it moves an already-confirmed meeting, even if it also proposes new times.
2. `acceptance`: it confirms a time, even if it also mentions a backup.
3. `assistant_handoff`: it hands scheduling to someone else, even if it also asks to meet.
4. `proposed_times`: it contains specific times, even if it is also the first request.
5. `new_request`
6. `none`

**Edge cases (decided, so every writer labels the same way):**
- Logistics after a time is confirmed (video link, phone number, agenda, address) → `none`.
- Automated confirmations, calendar invite text, registrations, reminders → `none`.
- Announcements of events, deadlines or office hours sent to a group → `none`.
- A group announcement that moves an already-set recurring meeting (e.g. "lab meeting
  moves to Wednesdays") → `reschedule`.
- Out-of-office auto-replies → `none`.
- A thank-you after a meeting → `none`, unless it also asks for or offers another meeting.
- Turning down all offered times *without* offering new ones → `new_request` ("none of
  those work, could you send a few more?").

## Cleanup features (the `Clean` column in the outlines)

Each outline row lists which of these the thread must contain. Spread them so
every user has every feature several times.

| Tag | What to include |
|---|---|
| `Q` | Gmail-style quoted reply: `On Tue, Sep 8, 2026 at 3:12 PM Dana Whitfield <dana...> wrote:` then the earlier message with `> ` at the start of each line |
| `QO` | Outlook-style quote: a line of underscores or `-----Original Message-----`, then `From:` / `Sent:` / `To:` / `Subject:` lines, then the earlier message |
| `SIG` | A multi-line signature with title, organization and a phone number |
| `MOB` | `Sent from my iPhone` or similar mobile footer |
| `FWD` | A forwarded email: `---------- Forwarded message ---------` with From / Date / Subject / To lines, then the forwarded text |
| `FOOT` | A legal or confidentiality footer, or an unsubscribe footer on newsletters |
| `WS` | Messy whitespace: extra blank lines, trailing spaces, a line wrapped mid-sentence |
| `LONG` | A long message (150+ words) |
| `TZ` | Times given in two time zones, or a meeting after a DST change |

Not every reply needs a quote: about half of replies should quote, so preprocess
also sees replies that don't.

## Fictional-data rules

- Email addresses use `.example` domains only: students `@example.com`, the university
  `@college.example` (and subdomains), firms `@<firmname>.example`.
- US phone numbers use `555-0100` to `555-0199` (e.g. `(617) 555-0142`). UK numbers use
  `020 7946 0000` to `020 7946 0999`, Germany `+49 30 23125 000`-style made-up numbers
  marked fictional in the contact table.
- Firms, products, cafés and buildings are made up (listed in the user files). Don't
  add new named organizations without adding them to the user file first.
- Write phone numbers and email addresses in a few different styles (`(617) 555-0142`,
  `617.555.0142`, `+1 617 555 0142`; addresses inside `<...>` and bare in body text),
  so anonymization has to handle them all.

## Writing process

1. Read this file, `shared_contacts.md`, `shared_messages.md`, and your user's file.
2. Write threads in outline order, about 10 per batch, to
   `data/source/batches/user_XX_bN.jsonl`.
3. Run the validator on each batch and fix every error (and every warning that is a
   real problem) before moving on. From `src/ingest`:
   `uv run python validate.py ../../data/source/batches/user_XX_bN.jsonl --users ../../data/source/users.json --generated`
4. Mark each written thread `☑` in the outline's Status column.
5. Follow the outline. If a thread needs to change, edit the outline row first and note why.
6. Contacts must behave according to their habits, except where the outline says a
   thread deliberately breaks a habit.
