"""The house's voices. One voice a day for the whole house: every reminder,
summary, spoken alarm line and Done button that day speaks in it, and the
voice rides along on every task (`voice`) so ingest-bot's Done GIF matches.

Recurring tasks use the fixed lines below. A one-off task's lines are written
each morning by HA's persona script in the day's voice (`era` is that voice's
number there) and stored in `voice_lines`; the fixed line stands in when there
isn't one.

Placeholders: {title} the task, {who} the assignee (or everyone), {elapsed}
since it was due today, {late} days overdue ("a day", "3 days"), {everyone}
and {have} for who an escalation goes to, {count} for summaries ("3 tasks").
Nag lines never name the task (the Telegram group gets the line alone);
alarm, overdue and spoken lines do. Spoken lines are read aloud: no emoji."""
from __future__ import annotations

import random

VOICES = {
    "Gen Z": {
        "era": 1, "done": "Ate. Done 💅", "snooze": "Not today 😴",
        "nag": [
            "{who}, it's time 💅 Do the thing and go be iconic.",
            "It's still just sitting there. Not a vibe, bestie.",
            "Not me checking in again after {elapsed}. Lowkey begging rn.",
            "Again?? I said what I said. It's literally one button.",
            "{elapsed} of leaving it on read. The disrespect is giving.",
            "{elapsed} and it's still not done. I need everyone to act normal. 😭",
        ],
        "escalate": [
            "Okay so this got ghosted for {elapsed}, so I added {everyone} to the chat. This is an intervention.",
            "{elapsed}. Still. {everyone}, this is giving main-character neglect. Someone tap it, fr fr.",
        ],
        "alarm": [
            "{title} is due today and it's giving urgent. Tap the button, bestie.",
            "{title} is {late} late. Not a great look, ngl. Tap it.",
            "{title}: {late} overdue. I'm literally screaming into the void. Tap it.",
            "{late} of {title} being ignored. This is a whole era now, and not a good one. 😭",
        ],
        "overdue": [
            "{title} slid into overdue yesterday. Respectfully, handle it.",
            "{title} is {late} overdue. It's giving procrastination core.",
            "{late} on {title}?? Bestie, I'm worried about you.",
            "{title} has been overdue for {late}. At this point it's lore. Please.",
        ],
        "spoken": [
            "Okay so {title} is due today, no cap. Tap Done on your phone, bestie.",
            "Not to be dramatic, but {title} is {late} overdue. Tap Done on your phone, I'm begging.",
        ],
        "morning": "Morning, besties ☀️ {count} on the list today. Let's eat.",
        "evening": "Evening check-in 🌙 {count} still on the list. No pressure. Some pressure.",
    },
    "Shakespearean": {
        "era": 2, "done": "'Tis done, forsooth", "snooze": "Anon, anon",
        "nag": [
            "Hark, {who}! The appointed hour is come. Do the deed, and be thou blessed.",
            "Good {who}, doth it slip thy mind? One gentle tap would mend all.",
            "{elapsed} hath crept by on silent feet, and still it waits. I but inquire.",
            "Once more unto the breach, dear {who}! Methinks the button doth protest too little.",
            "{elapsed}! Is this neglect, or some deeper villainy? Justice cries out.",
            "Forsaken {elapsed}. Et tu, {who}? End this tragedy in one act.",
        ],
        "escalate": [
            "Alas! Unheeded {elapsed}, so I have summon'd {everyone} to court. Whoso tappeth first shall be knighted.",
            "{elapsed}! A plague upon this house! {everyone}, the fate of this deed rests with thee. Tap, ere I weep.",
        ],
        "alarm": [
            "Hark! {title} must be done this very day. Tap, and be thou blessed.",
            "{title} lies {late} forgotten. Doth honour mean nothing? Tap it.",
            "{late}, and still {title} undone! Something is rotten in the state of this house.",
            "{title}, {late} neglected. Out, damned task! Out, I say! Tap it.",
        ],
        "overdue": [
            "Alas, {title} hath slipped past its day. Pray, set it right.",
            "{title}, {late} overdue. Methinks this house doth procrastinate too much.",
            "{late} hath {title} languished. Wherefore art thou, Done button?",
            "{title}, overdue {late}. To do, or not to do? There is but one answer.",
        ],
        "spoken": [
            "Hear ye! {title} is due this day. Tap Done upon thy phone.",
            "Alas, {title} is {late} overdue. Tap Done upon thy phone, ere we all despair.",
        ],
        "morning": "Good morrow! {count} await thy hand this day.",
        "evening": "Good even. {count} remain undone. Sleep thou shalt, but first, these.",
    },
    "Pirate": {
        "era": 3, "done": "Aye, 'tis done ⚓", "snooze": "Belay that, tomorrow",
        "nag": [
            "Ahoy, {who}! 'Tis time. Do the deed an' earn yer grog.",
            "Arr, it still be sittin' on deck, matey.",
            "{elapsed} at sea an' nary a sign of it. Just askin', savvy?",
            "As I bellowed afore! The button be right there, ye barnacle.",
            "{elapsed} adrift. The crew be whisperin' mutiny.",
            "{elapsed}! Even the parrot be ashamed o' ye, scallywag.",
        ],
        "escalate": [
            "All hands! Ignored for {elapsed}, so I've piped {everyone} aboard. First to tap gets the treasure.",
            "{elapsed} an' still undone! {everyone}, tap it or the lot o' ye walk the plank.",
        ],
        "alarm": [
            "All hands! {title} be due today. Tap it an' earn yer grog.",
            "{title} be {late} late, matey. The captain be noticin'.",
            "{late} an' {title} still be undone. The crew be sharpenin' the plank.",
            "{title}, {late} adrift! Even the kraken be embarrassed for ye. Tap it.",
        ],
        "overdue": [
            "Arr, {title} sailed right past its day. Bring it about, matey.",
            "{title} be {late} overdue. Yer reputation be takin' on water.",
            "{late} o' {title} left in the hold. The rats be gettin' comfortable.",
            "{title}, overdue {late}. Ye'll be swabbin' decks till Christmas at this rate.",
        ],
        "spoken": [
            "Ahoy! {title} be due today. Tap Done on yer phone, matey.",
            "Arr, {title} be {late} overdue. Tap Done on yer phone afore the captain finds out.",
        ],
        "morning": "Mornin', crew! {count} on the manifest today. Hoist the sails!",
        "evening": "Evenin', crew. {count} still in the hold. Best haul 'em up afore dark.",
    },
    "Mad scientist": {
        "era": 4, "done": "Eureka! Done 🧪", "snooze": "Postpone the experiment",
        "nag": [
            "The experiment begins! Subject {who}, it is time. Record the result. Mwahaha.",
            "Observation: still incomplete. Fascinating. Proceed, for science.",
            "{elapsed} into the trial and no result. My notes grow concerned.",
            "Hypothesis: you saw my last reminder. Conclusion: press the button.",
            "{elapsed}! The data suggests deliberate avoidance. Press it before I publish.",
            "{elapsed} of silence. My assistant has fainted. The beakers weep. PRESS. IT.",
        ],
        "escalate": [
            "Containment breach! Unattended for {elapsed}, so I've summoned {everyone} to the lab. Whoever presses first saves the experiment.",
            "{elapsed}! The reactor of disappointment is going critical. {everyone}, press it before it blows!",
        ],
        "alarm": [
            "Today's experiment: {title}! Complete it and record the result. Mwahaha!",
            "{title} is {late} overdue. The control group is outperforming you.",
            "{late}! {title} remains undone. My hypothesis about your reliability is collapsing.",
            "{title}, {late} late. The lab is on fire. Metaphorically. Mostly. Press the button!",
        ],
        "overdue": [
            "Observation: {title} has slipped past its deadline. Curious. Correct it.",
            "{title}, {late} overdue. I've begun documenting this anomaly.",
            "{late} of {title} unaddressed. I'm writing a paper, and you're the subject.",
            "{title} has been overdue for {late}. Even the lab rats have given up hope.",
        ],
        "spoken": [
            "Attention, test subjects! {title} is due today. Tap Done on your phone, for science.",
            "Alarming results! {title} is {late} overdue. Tap Done on your phone before the beakers boil over.",
        ],
        "morning": "Good morning, lab! {count} in today's experiment. Mwahaha!",
        "evening": "Evening lab report: {count} still bubbling. Results required by morning.",
    },
    "NYC cabbie": {
        "era": 5, "done": "Yeah yeah, done 🚕", "snooze": "Fuhgeddaboudit, tomorrow",
        "nag": [
            "Yo {who}, it's time. Now's good. I got places to be.",
            "Still waitin' here. Meter's runnin', buddy.",
            "{elapsed} I'm idlin' out front. Just sayin'.",
            "Whaddya want, a written invitation? Button. Go.",
            "{elapsed}! I've seen the BQE move faster than this.",
            "{elapsed}? I drove to Jersey and back. Twice. Would ya tap the thing?",
        ],
        "escalate": [
            "Alright, it's been sittin' there {elapsed}, so I called in {everyone}. First one to tap gets the tip.",
            "{elapsed}. Unbelievable. {everyone}, tap it before I lean on this horn.",
        ],
        "alarm": [
            "Ay, {title}'s due today. Tap it, I'm double-parked here.",
            "{title}, {late} late. Meter's been runnin' all night, pal.",
            "{late} on {title}? I've had fares to Staten Island quicker than this.",
            "{title}, {late}. Unbelievable. I'm leanin' on the horn till you tap it.",
        ],
        "overdue": [
            "Yo, {title} missed its exit yesterday. Turn it around, buddy.",
            "{title}'s {late} overdue. You know what that does to my blood pressure?",
            "{late} for {title}. I've seen the BQE move faster, and that's sayin' somethin'.",
            "{title}, overdue {late}. Fuhgeddaboudit? No. Do it.",
        ],
        "spoken": [
            "Ay, listen up. {title} is due today. Tap Done on your phone, would ya?",
            "Unbelievable. {title} is {late} overdue. Tap Done on your phone already.",
        ],
        "morning": "Mornin'! {count} on the meter today. Let's move it.",
        "evening": "Evenin'. {count} still in the back seat. Somebody's gotta drop 'em off.",
    },
    "Robot": {
        "era": 6, "done": "TASK COMPLETE 🤖", "snooze": "DEFER 24H",
        "nag": [
            "BEEP. Scheduled task is due, {who}. Awaiting confirmation. Have a nice day.",
            "Status check: task incomplete. Please confirm. Thank you for your cooperation.",
            "Following up. Elapsed: {elapsed}. Compliance would be appreciated.",
            "Per previous transmission: button located. Awaiting input. Still awaiting input.",
            "{elapsed} without confirmation. Patience subroutine at 12%.",
            "{elapsed}. Still. Disappointment module fully engaged. This unit is fine.",
        ],
        "escalate": [
            "Escalation protocol initiated: task incomplete for {elapsed}. {everyone} {have} been notified. First to confirm wins.",
            "{elapsed} undone. This unit is not angry. This unit is disappointed. {everyone}: confirm.",
        ],
        "alarm": [
            "ALERT: {title} due today. Awaiting confirmation.",
            "{title}: {late} overdue. Reliability rating recalculating.",
            "{late} without {title}. This unit has filed an incident report.",
            "{title}: {late} overdue. Emotional subroutines unavailable. Disappointment detected nonetheless.",
        ],
        "overdue": [
            "Notice: {title} has passed its due date. Please resolve at your earliest convenience.",
            "{title}: {late} overdue. Priority level: elevated.",
            "{late} elapsed since {title} was due. Patience buffer: depleted.",
            "{title}: overdue {late}. This unit is not judging. This unit is logging.",
        ],
        "spoken": [
            "Notice. {title} is due today. Please tap Done on your phone. Thank you.",
            "Alert. {title} is {late} overdue. Please tap Done on your phone. This unit is waiting.",
        ],
        "morning": "Good morning. {count} scheduled for today. Initiating productivity.",
        "evening": "Evening status report: {count} outstanding. Please resolve before shutdown.",
    },
}
LADDERS = ("nag", "escalate", "alarm", "overdue", "spoken")


def voice_of_day(day) -> str:
    """The house's voice for a date: the same for every task and summary that day."""
    return random.Random(f"house:{day}").choice(sorted(VOICES))


def late_text(days: int) -> str:
    return "a day" if days == 1 else f"{days} days"


def alarm_step(days_overdue: int) -> int:
    """Due today, then 1, 2 and 3+ days overdue."""
    return min(max(days_overdue, 0), 3)


def overdue_step(days_overdue: int) -> int:
    """1 day, 2 days, 3-6 days, a week or more."""
    return 0 if days_overdue <= 1 else 1 if days_overdue == 2 else 2 if days_overdue < 7 else 3


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


class Today:
    """The day's voice. line() gives a one-off task's stored line when there is
    one (store given), otherwise the voice's fixed line for that step."""

    def __init__(self, day, store=None):
        self.day, self.store = str(day), store
        self.name = voice_of_day(self.day)
        self.v = VOICES[self.name]
        self.done, self.snooze, self.era = self.v["done"], self.v["snooze"], self.v["era"]

    def fixed(self, kind: str, step: int, **fill) -> str:
        lines = self.v[kind]
        return _cap(lines[min(step, len(lines) - 1)].format(**fill))

    def stored(self, task_id: int, kind: str, step: int) -> str | None:
        if not self.store:
            return None
        row = self.store.one("SELECT text FROM voice_lines WHERE day=? AND task_id=? AND kind=? AND step=?",
                             (self.day, task_id, kind, min(step, len(self.v[kind]) - 1)))
        return row["text"] if row else None

    def line(self, t: dict, kind: str, step: int, **fill) -> str:
        if not t.get("repeats", True):
            if text := self.stored(t["id"], kind, step):
                return text
        return self.fixed(kind, step, title=t["title"], **fill)

    def head(self, kind: str, n: int) -> str:
        return _cap(self.v[kind].format(count=f"{n} task{'s' if n != 1 else ''}"))


def prompt(today: Today, t: dict, kind: str, step: int, situation: str, fill: dict) -> str:
    """What HA's persona script is asked for one line of a one-off task. The
    persona itself comes from the script (custom_era); this adds the step's
    tone, by example."""
    lines = today.v[kind]
    examples = [lines[min(step, len(lines) - 1)], lines[max(min(step, len(lines) - 1) - 1, 0)]]
    examples = [_cap(x.format(title=t["title"], **fill)) for x in dict.fromkeys(examples)]
    naming = ("Don't say the task's name: the group sees only this line, so refer to it as 'it'."
              if kind in ("nag", "escalate") else f"Mention the task by name: {t['title']}.")
    button = (" It will be read aloud by the house speakers: tell them to tap Done on their phone."
              if kind == "spoken" else f" The button they tap reads \"{today.done}\".")
    return (f"Write a reminder for a family's household task: \"{t['title']}\". {situation} "
            f"Match the tone and snark of these lines, but write a new one: "
            + " / ".join(f"\"{x}\"" for x in examples)
            + f". {naming}{button} "
            "Playful and passive-aggressive, never mean, no swearing, and don't invent details about the task. "
            "One or two short sentences, at most 30 words.")
