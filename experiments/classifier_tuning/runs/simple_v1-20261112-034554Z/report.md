# Tuning run simple_v1-20261112-034554Z

| Setting | Value |
|---|---|
| harness | simple_v1 |
| harness_sha | eeb29c5d56a7 |
| model | gemini-3.8-flash |
| location | global |
| thinking_budget | 128 |
| max_earlier_messages | 10 |
| max_body_chars | 4000 |
| rules_path | None |
| rules_version | none |
| rules_file_sha256 |  |
| rules_sent_sha256 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| excluded_sections | [] |
| system_prompt_sha256 | fdfdb91908efe1ec32cdf686f7a2d0ce986e11519bfdfd586bb8c1ab9b6d4ab1 |
| messages_md5 | 439a64f82467849dda83023b10ba7227 |
| annotations_md5 | 04f54bc599a732e2598fee55052ab297 |
| users_md5 | 6927c9f02491245646e8f394c2a63ae1 |
| splits_md5 | 8947c6b7a962e6aa6583fa11abf9756b |
| states_md5 | 5b927957d782cc9c381eb5478f8d161d |
| split | eval |
| limit | None |
| messages | 150 |
| git_commit | 6c4ed984b34f9e4783ce89d22c4123cd16a67be1-dirty |

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
| by_act/cold_sales/needs_response_accuracy | 0.333 |
| by_act/confirm_choice/n | 18 |
| by_act/confirm_choice/needs_response_accuracy | 0.889 |
| by_act/decline_all/n | 1 |
| by_act/decline_all/needs_response_accuracy | 1.000 |
| by_act/handoff_ask/n | 1 |
| by_act/handoff_ask/needs_response_accuracy | 1.000 |
| by_act/handoff_wait/n | 2 |
| by_act/handoff_wait/needs_response_accuracy | 1.000 |
| by_act/info/n | 1 |
| by_act/info/needs_response_accuracy | 1.000 |
| by_act/intro_other/n | 2 |
| by_act/intro_other/needs_response_accuracy | 0.000 |
| by_act/intro_user/n | 2 |
| by_act/intro_user/needs_response_accuracy | 0.500 |
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
| by_source/generated/needs_response_accuracy | 0.940 |
| failures | 0 |
| label/accuracy | 0.940 |
| needs_response/accuracy | 0.940 |
| needs_response/f1 | 0.917 |
| needs_response/false_alarms | 8 |
| needs_response/missed | 1 |
| needs_response/n | 150 |
| needs_response/precision | 0.862 |
| needs_response/recall | 0.980 |
| needs_response/tn | 91 |
| needs_response/tp | 50 |
| tokens/input | 93913 |
| tokens/output_and_thinking | 10366 |
| wall_time_s | 157.000 |

## needs_response mistakes (9)

| message | act | true | predicted | reason |
|---|---|---|---|---|
| user_11/g006/0 | cold_sales | False | True | The sender proposes a specific date (Tuesday, October 27) for a short call and asks for the recipient's availability. |
| user_11/g010/0 | cold_sales | False | True | The sender proposes meeting next Tuesday afternoon for a demo and asks for a convenient time. |
| user_11/g027/0 | cold_sales | False | True | The sender is proposing a specific time for a product demo meeting. |
| user_12/g013/0 | cold_sales | False | True | The sender proposes a specific time for a product demo meeting. |
| user_12/g017/0 | intro_user | True | False | This is an introduction email connecting two parties and asking Priyanka to reach out to schedule an informational interview. |
| user_12/g018/2 | confirm_choice | False | True | Marco confirms Friday at 11:30am and leaves selecting the location to the user. |
| user_12/g019/0 | intro_other | False | True | The email introduces two parties and requests that they connect to find a time to meet without proposing specific times. |
| user_12/g026/0 | intro_other | False | True | The email introduces two parties and asks them to connect to find a time to chat. |
| user_12/g027/2 | confirm_choice | False | True | The sender confirms Wednesday at 11am and requests the user's phone number. |
