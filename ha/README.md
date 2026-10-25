# Home Assistant pieces

What Household Tasks needs inside Home Assistant, as templates. Replace each `<PLACEHOLDER>` with your own value; nothing here is specific to one house.

| File | What it is | Placeholders |
|---|---|---|
| `configuration-tasks.yaml` | `rest_command.tasks_action`, `tasks_dog_alarm`, `tasks_complete` and `sensor.household_tasks` for `configuration.yaml`; `secrets.yaml` needs `tasks_api_token: "Bearer <TASKS_API_TOKEN>"` | `<TASKS_HOST>` |
| `automations/tasks_notification_actions.json` | Forwards Done / Snooze taps on phone notifications to the service | none |
| `automations/switch_marks_task_done.json` | Optional: an existing on/off helper doubles as a "done" switch for one alarm task (pair with `HA_SWITCH_TASKS`) | `<SWITCH_ENTITY>`, `<TASKS_HA_USER_ID>`, `<TASK_ID>` |
| `automations/reminder_append_steps.json` | Optional: steps to append to an existing evening reminder so it also reads out what's due | `<TTS_ENGINE>` |
| `scripts/tasks_announce.json` | `script.tasks_announce`, the spoken fallback | `<NIGHT_MODE_SWITCH>`, `<HOUSE_EMPTY_SWITCH>`, `<VACATION_SWITCH>`, `<SPEAKERS>`, `<TTS_ENGINE>` |
| `dashboard-card.yaml` | Calendar Card Pro example for `calendar.household_tasks` | `<your-tailnet>` |
| `www/tasks.html` | The Tasks dashboard's switcher: copy it to HA's `config/www/` and make a **Webpage** dashboard on `/local/tasks.html`. Opened on HA's LAN address it shows Tasks on the LAN, otherwise over Tailscale; the service's `FRAME_ANCESTORS` must list HA's addresses | `<TASKS_LAN_URL>`, `<TASKS_TAILNET_URL>` |

Automations and scripts go in through Home Assistant's config API, for example `POST /api/config/automation/config/<id>` with the JSON as the body, or by pasting them into the YAML editor.

The calendar is a Remote Calendar integration pointed at `http://<TASKS_HOST>:8040/calendar.ics`, labelled for whatever your summaries read.

`local/` (not in git) holds the exact versions installed in this house, plus the originals they replaced, for rollback.
