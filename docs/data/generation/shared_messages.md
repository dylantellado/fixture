# Shared messages (copy exactly)

These messages were sent to a mailing list, so the **same text** lands in more
than one inbox. Writers copy the thread JSON below **character for character**,
changing only `user_id`. This lets tests check that identical emails in two
inboxes stay separate (different `message_id`s, one per user) and that
anonymization gives the same placeholders in both.

## Fall recruiting kickoff (user_01 t001, user_02 t001, user_04 t001)

```json
{"user_id": "<USER>", "thread_id": "t001", "subject": "Fall recruiting kickoff: dates for your calendar", "participants": ["Dana Whitfield <dana.whitfield@careers.college.example>", "Career Center Students <career-students@lists.college.example>"], "messages": [{"sender": "Dana Whitfield <dana.whitfield@careers.college.example>", "recipients": ["Career Center Students <career-students@lists.college.example>"], "timestamp": "Tue, 01 Sep 2026 08:30:00 -0400", "body": "Hi everyone,\n\nWelcome back! Fall recruiting moves fast, so here are the dates to put in your calendar now:\n\n  * Resume workshop: Thu Sep 10, 4:00-5:00 pm, Wexley Hall 120\n  * Career Fair: Thu Sep 24, 1:00-4:00 pm, Wexley Hall (register online by Sep 21)\n  * Interview prep night: Tue Oct 6, 6:00 pm, virtual\n\nDrop-in advising runs Monday to Thursday, 1:00-3:00 pm, no appointment needed.\nFor a 1:1 appointment, just reply to me or call the front desk at (617) 555-0140.\n\n\nStudying abroad this term? All of our workshops are recorded, and advisors can\nmeet by video. Mention your time zone when you write.\n\nWishing you a great start to the semester,\n\nDana Whitfield\nSenior Career Advisor | Career Center, Wexley Hall\n(617) 555-0142\n\n--\nYou are receiving this because you are subscribed to Career Center Students.\nTo unsubscribe, email career-students-leave@lists.college.example.", "label": "none"}]}
```

## STAT 142 problem set 1 (user_01 t004, user_03 t010)

```json
{"user_id": "<USER>", "thread_id": "<t004 for user_01, t010 for user_03>", "subject": "STAT 142: Problem Set 1 and office hours", "participants": ["Elena Vasquez <elena.vasquez@stats.college.example>", "STAT 142 <stat142-all@lists.college.example>"], "messages": [{"sender": "Elena Vasquez <elena.vasquez@stats.college.example>", "recipients": ["STAT 142 <stat142-all@lists.college.example>"], "timestamp": "Mon, 07 Sep 2026 17:05:00 -0400", "body": "Dear all,\n\nProblem Set 1 is now posted and is due Thursday, September 17 at 11:59 pm.\nPlease submit a single PDF.\n\nMy office hours are Tuesdays and Thursdays, 4:00-5:00 pm, in Science Annex 309.\nThey are booked in 20-minute slots: email me the day before to reserve one.\nTA office hours are listed on the course page.\n\nBest,\n\nElena Vasquez\nAssociate Professor of Statistics", "label": "none"}]}
```
