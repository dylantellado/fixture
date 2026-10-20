# Shared contacts

These six people appear in more than one user's inbox. They are the **same person**
with the **same email address** in every inbox (this tests that anonymization gives
them the same placeholder everywhere), but each user has **different meeting
details** with them. That way, if search for one user ever returns another user's
email, the wrong answer is obvious.

Writers: keep each person's voice and signature identical across users, and never
let one user's details leak into another user's threads.

## Dana Whitfield: career advisor (user_01, user_02, user_04)

- Address: `dana.whitfield@careers.college.example`
- Signature:
  ```
  Dana Whitfield
  Senior Career Advisor | Career Center, Wexley Hall
  (617) 555-0142
  ```
- Voice: warm, organized, always confirms the time zone and format in the same message.
- Sends the same "Fall recruiting kickoff" newsletter to all three (user_01 t001,
  user_02 t001, user_04 t001). The newsletter text is identical in all three inboxes.

| User | Format | Day and time | Where |
|---|---|---|---|
| user_01 Priya | in person, 30 min | **Tuesdays, 3:00 or 3:30 pm ET** | Wexley Hall, Room 214 |
| user_02 Marcus | video, 30 min | **Fridays, 11:00 am ET** | Zoom |
| user_04 Lena | video, 30 min | **Mondays, 8:00 am ET** (1 pm London; noon London the week of Oct 26) | Zoom |

## Nadia Brooks: career center peer coach (user_01, user_02)

- Address: `nadia.brooks@careers.college.example`
- Dana hands mock-interview requests to her (`assistant_handoff`). Upbeat, short emails,
  signs "Nadia (Peer Career Coach)".

| User | Format | Day and time |
|---|---|---|
| user_01 Priya | in person, Wexley Hall Room 214 | **Tue Oct 6, 3:30 pm ET** (Tuesdays, like Dana) |
| user_02 Marcus | Zoom | **Fri Oct 9, 11:00 am ET** (Fridays, like Dana) |

## Jordan Lee and Tess Navarro: Larkmoor Capital (user_01, user_02)

- Larkmoor Capital is a fictional investment firm in New York.
- Jordan Lee, Campus Recruiter: `jordan.lee@larkmoor.example`
- Tess Navarro, Recruiting Coordinator: `tess.navarro@larkmoor.example`
- Jordan's emails end with a confidentiality footer (`FOOT`). Tess's signature:
  ```
  Tess Navarro
  Recruiting Coordinator, Larkmoor Capital
  212.555.0117
  ```
- Habit (both users): Jordan sends the invite, then **hands scheduling to Tess**
  (`assistant_handoff`). Tess always offers **exactly three slots** and asks for a reply
  within 24 hours.

| User | Role | Rounds |
|---|---|---|
| user_01 Priya | Summer Analyst, investment banking | First round **video, 30 min**, held **Thu Oct 8, 11:00 am ET** (moved from Wed Oct 7, 2:00 pm). Superday **Fri Oct 16, in person, New York** |
| user_02 Marcus | Software Engineer, new grad | First round **video technical, 60 min, CoderPad**, held **Fri Oct 9, 1:00 pm ET** (moved from Tue Oct 6, 10:00 am). Final round **Thu Oct 22, in person, New York** |

## Prof. Elena Vasquez: statistics professor (user_01, user_03)

- Address: `elena.vasquez@stats.college.example`
- Teaches **STAT 142: Data Methods**. Priya is a student in it; Sofia is one of its TAs.
- Signs off "EV" in short emails, full signature in course announcements:
  ```
  Elena Vasquez
  Associate Professor of Statistics
  ```
- Course announcements are sent to the whole class, so the same announcement text
  appears in both inboxes (user_01 t004 = user_03 t010).

| User | Relationship | Habit |
|---|---|---|
| user_01 Priya | student | **Office hours Tue/Thu 4:00 to 5:00 pm ET, booked in 20-minute slots**, by email the day before. Room: Science Annex 309 |
| user_03 Sofia | TA | **Weekly TA meeting Mondays 9:00 am ET**. When she travels she moves it to **Thursday 9:00 am**, never another day |

## Rohan Mehta: alum in private equity, London (user_01, user_04)

- Calder Bay Partners, a fictional private equity firm in London.
- Address: `rohan.mehta@calderbay.example`. Phone: `+44 20 7946 0123`.
- Signature:
  ```
  Rohan Mehta
  Associate, Calder Bay Partners
  +44 20 7946 0123
  ```
- Voice: friendly, brief, uses British spelling.

| User | Format | Habit |
|---|---|---|
| user_01 Priya | **phone calls only**, 30 min | **Mornings ET only (8 to 10 am ET)**, because he is in London. He always sends his number. One exception: an in-person coffee when he visits Boston on Nov 9 |
| user_04 Lena | **in person, coffee** | **Saturday mornings, 10:00 am London**, at "the Linden café near his office" |
