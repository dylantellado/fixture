# Tuning run prod_v1-20261112-034140Z

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
| split | eval |
| limit | None |
| messages | 150 |
| git_commit | e040fd8f02192ae188366b78ecd66019e9c66cd5 |

| Metric | Value |
|---|---|
| by_act/accept/n | 31 |
| by_act/accept/needs_response_accuracy | 1.000 |
| by_act/announcement/n | 4 |
| by_act/announcement/needs_response_accuracy | 1.000 |
| by_act/automated/n | 4 |
| by_act/automated/needs_response_accuracy | 1.000 |
| by_act/cancel_followup/n | 2 |
| by_act/cancel_followup/needs_response_accuracy | 1.000 |
| by_act/cancel_invite/n | 2 |
| by_act/cancel_invite/needs_response_accuracy | 1.000 |
| by_act/catchup/n | 4 |
| by_act/catchup/needs_response_accuracy | 1.000 |
| by_act/cold_sales/n | 6 |
| by_act/cold_sales/needs_response_accuracy | 1.000 |
| by_act/confirm_choice/n | 18 |
| by_act/confirm_choice/needs_response_accuracy | 0.944 |
| by_act/decline_all/n | 1 |
| by_act/decline_all/needs_response_accuracy | 1.000 |
| by_act/handoff_ask/n | 1 |
| by_act/handoff_ask/needs_response_accuracy | 1.000 |
| by_act/handoff_wait/n | 2 |
| by_act/handoff_wait/needs_response_accuracy | 1.000 |
| by_act/info/n | 1 |
| by_act/info/needs_response_accuracy | 1.000 |
| by_act/intro_other/n | 2 |
| by_act/intro_other/needs_response_accuracy | 1.000 |
| by_act/intro_user/n | 2 |
| by_act/intro_user/needs_response_accuracy | 0.000 |
| by_act/propose/n | 42 |
| by_act/propose/needs_response_accuracy | 1.000 |
| by_act/request/n | 16 |
| by_act/request/needs_response_accuracy | 1.000 |
| by_act/reschedule_directive/n | 6 |
| by_act/reschedule_directive/needs_response_accuracy | 1.000 |
| by_act/sched_link/n | 2 |
| by_act/sched_link/needs_response_accuracy | 1.000 |
| by_act/still_on/n | 4 |
| by_act/still_on/needs_response_accuracy | 1.000 |
| by_source/generated/n | 150 |
| by_source/generated/needs_response_accuracy | 0.980 |
| failures | 0 |
| label/accuracy | 1.000 |
| needs_response/accuracy | 0.980 |
| needs_response/f1 | 0.970 |
| needs_response/false_alarms | 1 |
| needs_response/missed | 2 |
| needs_response/n | 150 |
| needs_response/precision | 0.980 |
| needs_response/recall | 0.961 |
| needs_response/tn | 98 |
| needs_response/tp | 49 |
| tokens/input | 570463 |
| tokens/output_and_thinking | 11202 |
| wall_time_s | 246.100 |

## needs_response mistakes (3)

| message | act | true | predicted | reason |
|---|---|---|---|---|
| user_12/g003/0 | intro_user | True | False | E17, D1: introduction suggesting two people meet; NR10: asks Priyanka specifically to reach out, so Priya (or non-Priyanka user) is false. |
| user_12/g017/0 | intro_user | True | False | E17, D1: introduction suggesting two people meet; NR10: the other person is directed to reach out to the user. |
| user_12/g027/2 | confirm_choice | False | True | D3, E20: confirms one of user's proposed times; NR3 applies because it asks user for their phone number. |
