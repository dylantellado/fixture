# Tuning run prod_v1-20261110-053821Z

| Setting | Value |
|---|---|
| harness | prod_v1 |
| harness_sha | b092723ec77d |
| model | gemini-3.8-flash |
| location | global |
| thinking_budget | 128 |
| max_earlier_messages | 10 |
| max_body_chars | 4000 |
| rules_path | docs/data/labeling_rules.md |
| rules_version | 1.5 |
| rules_file_sha256 | 4473a8690a847203f49ca46c9e5087ed3dcf7ac605c13d72631fb086bd124f01 |
| rules_sent_sha256 | ba009467a9ecd38bf0442622fd94f7d24bd550a49b40cbc82c256831585163bb |
| excluded_sections | ['not adopted', 'change log'] |
| system_prompt_sha256 | 9d6e62a620e9fd75e2af0ce36e9762cc6d09957f4ffed2a325afdbf5dd4bcaf4 |
| messages_md5 | 439a64f82467849dda83023b10ba7227 |
| annotations_md5 | 04f54bc599a732e2598fee55052ab297 |
| users_md5 | 6927c9f02491245646e8f394c2a63ae1 |
| splits_md5 | 8947c6b7a962e6aa6583fa11abf9756b |
| states_md5 | 5b927957d782cc9c381eb5478f8d161d |
| split | train |
| limit | None |
| messages | 802 |
| git_commit | 69bb8f57ba701f49208f84cb4fdea9dd5604dcf9-dirty |

| Metric | Value |
|---|---|
| by_act/accept/n | 97 |
| by_act/accept/needs_response_accuracy | 0.990 |
| by_act/accept_question/n | 4 |
| by_act/accept_question/needs_response_accuracy | 1.000 |
| by_act/announcement/n | 16 |
| by_act/announcement/needs_response_accuracy | 1.000 |
| by_act/automated/n | 19 |
| by_act/automated/needs_response_accuracy | 1.000 |
| by_act/cancel_followup/n | 5 |
| by_act/cancel_followup/needs_response_accuracy | 1.000 |
| by_act/cancel_invite/n | 6 |
| by_act/cancel_invite/needs_response_accuracy | 1.000 |
| by_act/catchup/n | 1 |
| by_act/catchup/needs_response_accuracy | 1.000 |
| by_act/cold_sales/n | 10 |
| by_act/cold_sales/needs_response_accuracy | 1.000 |
| by_act/confirm_choice/n | 48 |
| by_act/confirm_choice/needs_response_accuracy | 1.000 |
| by_act/decline_all/n | 3 |
| by_act/decline_all/needs_response_accuracy | 1.000 |
| by_act/handoff_ask/n | 2 |
| by_act/handoff_ask/needs_response_accuracy | 1.000 |
| by_act/handoff_wait/n | 3 |
| by_act/handoff_wait/needs_response_accuracy | 1.000 |
| by_act/info/n | 7 |
| by_act/info/needs_response_accuracy | 1.000 |
| by_act/intro_other/n | 2 |
| by_act/intro_other/needs_response_accuracy | 1.000 |
| by_act/out_of_office/n | 4 |
| by_act/out_of_office/needs_response_accuracy | 1.000 |
| by_act/propose/n | 112 |
| by_act/propose/needs_response_accuracy | 1.000 |
| by_act/propose_one/n | 1 |
| by_act/propose_one/needs_response_accuracy | 1.000 |
| by_act/request/n | 38 |
| by_act/request/needs_response_accuracy | 1.000 |
| by_act/reschedule_directive/n | 3 |
| by_act/reschedule_directive/needs_response_accuracy | 1.000 |
| by_act/reschedule_offer/n | 7 |
| by_act/reschedule_offer/needs_response_accuracy | 1.000 |
| by_act/restate/n | 1 |
| by_act/restate/needs_response_accuracy | 0.000 |
| by_act/sched_link/n | 9 |
| by_act/sched_link/needs_response_accuracy | 1.000 |
| by_act/still_on/n | 14 |
| by_act/still_on/needs_response_accuracy | 1.000 |
| by_act/task_split/n | 3 |
| by_act/task_split/needs_response_accuracy | 1.000 |
| by_act/thanks/n | 2 |
| by_act/thanks/needs_response_accuracy | 1.000 |
| by_source/generated/n | 417 |
| by_source/generated/needs_response_accuracy | 0.995 |
| by_source/v1/n | 375 |
| by_source/v1/needs_response_accuracy | 0.997 |
| failures | 10 |
| label/accuracy | 0.990 |
| needs_response/accuracy | 0.996 |
| needs_response/f1 | 0.994 |
| needs_response/false_alarms | 3 |
| needs_response/missed | 0 |
| needs_response/n | 792 |
| needs_response/precision | 0.988 |
| needs_response/recall | 1.000 |
| needs_response/tn | 548 |
| needs_response/tp | 241 |
| tokens/input | 3020184 |
| tokens/output_and_thinking | 49514 |
| wall_time_s | 2379.800 |

## needs_response mistakes (3)

| message | act | true | predicted | reason |
|---|---|---|---|---|
| user_02/t034/1 | - | False | True | E17, D1, NR10: hands off negotiation advice by introducing a specialist to meet with the user; NR10 leaves response open. |
| user_05/g011/3 | accept | False | True | D2, PR: sender specifies a concrete time (Tuesday at 10am) within the suggested morning window; NR1. |
| user_06/g008/3 | restate | False | True | E14, NR1: restates agreed time after user accepted single offered time, but asks for phone number so response needed. |
