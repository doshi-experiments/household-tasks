"""Pure schedule rules. Run in the image: python -m unittest discover tests"""
import unittest
from datetime import date, timedelta

from app import schedule as s

MON = date(2026, 10, 19)  # a Monday


class Flex(unittest.TestCase):
    def test_weekend_flex_every_weekday(self):
        want = {0: 4, 1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: 0}   # Mon-Thu -> Friday; Fri-Sun stay
        for wd, shift in want.items():
            d = MON + timedelta(days=wd)
            self.assertEqual(s.apply_flex(d, "weekend"), d + timedelta(days=shift), d)
            self.assertEqual(s.apply_flex(d, "exact"), d)

    def test_weekend_task_due_all_weekend_overdue_monday(self):
        fri = date(2026, 10, 23)
        self.assertEqual(s.state(fri, "weekend", fri - timedelta(days=1)), "upcoming")
        for d in (fri, fri + timedelta(days=1), fri + timedelta(days=2)):
            self.assertEqual(s.state(fri, "weekend", d), "due")
        self.assertEqual(s.state(fri, "weekend", fri + timedelta(days=3)), "overdue")
        self.assertEqual(s.days_overdue(fri, "weekend", fri + timedelta(days=3)), 1)

    def test_exact_overdue_next_day(self):
        self.assertEqual(s.state(MON, "exact", MON), "due")
        self.assertEqual(s.state(MON, "exact", MON + timedelta(days=1)), "overdue")
        self.assertEqual(s.days_overdue(MON, "exact", MON + timedelta(days=3)), 3)

    def test_snooze_defaults(self):
        self.assertEqual(s.default_snooze("exact", MON), MON + timedelta(days=1))
        self.assertEqual(s.default_snooze("weekend", MON), date(2026, 10, 23))
        self.assertEqual(s.default_snooze("weekend", date(2026, 10, 23)), date(2026, 10, 30))
        self.assertEqual(s.effective_due(MON, MON + timedelta(days=2)), MON + timedelta(days=2))
        self.assertEqual(s.effective_due(MON, MON - timedelta(days=2)), MON)


class Occurrences(unittest.TestCase):
    def test_interval_from_done(self):
        anchor = date(2026, 11, 6)
        self.assertEqual(s.next_nominal("interval", anchor=anchor, cursor=None, interval_n=30, interval_unit="days"), anchor)
        late = date(2026, 11, 9)   # given three days late: schedule follows reality
        cur = s.cursor_after("interval", "done", nominal_due=anchor, done_on=late, today=late)
        self.assertEqual(s.next_nominal("interval", anchor=anchor, cursor=cur, interval_n=30, interval_unit="days"),
                         date(2026, 12, 9))

    def test_rrule_does_not_drift(self):
        rule, anchor = "FREQ=WEEKLY;BYDAY=SA", date(2026, 10, 18)
        first = s.next_nominal("rrule", anchor=anchor, cursor=None, rrule=rule)
        self.assertEqual(first, date(2026, 10, 24))
        late = date(2026, 10, 27)  # done Tuesday after: next is the coming Saturday
        cur = s.cursor_after("rrule", "done", nominal_due=first, done_on=late, today=late)
        self.assertEqual(s.next_nominal("rrule", anchor=anchor, cursor=cur, rrule=rule), date(2026, 10, 31))

    def test_early_yearly_completion_moves_to_next_year(self):
        rule, anchor = "FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=15", date(2026, 1, 1)
        first = s.next_nominal("rrule", anchor=anchor, cursor=None, rrule=rule)
        self.assertEqual(first, date(2026, 4, 15))
        early = date(2026, 4, 10)
        cur = s.cursor_after("rrule", "done", nominal_due=first, done_on=early, today=early)
        self.assertEqual(s.next_nominal("rrule", anchor=anchor, cursor=cur, rrule=rule), date(2027, 4, 15))

    def test_skip_then_recompute_keeps_cursor(self):
        rule, anchor = "FREQ=WEEKLY;BYDAY=SA", date(2026, 10, 1)
        first = s.next_nominal("rrule", anchor=anchor, cursor=None, rrule=rule)
        cur = s.cursor_after("rrule", "skip", nominal_due=first, done_on=first, today=first)
        second = s.next_nominal("rrule", anchor=anchor, cursor=cur, rrule=rule)
        self.assertEqual(second, first + timedelta(days=7))
        # an edit re-derives from the same cursor, never back to the anchor
        self.assertEqual(s.next_nominal("rrule", anchor=anchor, cursor=cur, rrule="FREQ=WEEKLY;BYDAY=SU"),
                         first + timedelta(days=1))

    def test_month_end_and_occurrence_window(self):
        rule = s.normalize_rrule("rrule:freq=monthly;bymonthday=-1", date(2026, 1, 1))
        got = s.occurrences("rrule", anchor=date(2026, 1, 1), cursor=None, rrule=rule,
                            start=date(2026, 1, 1), end=date(2026, 3, 31))
        self.assertEqual(got, [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])

    def test_invalid_rule(self):
        with self.assertRaises(s.ScheduleError):
            s.normalize_rrule("FREQ=SOMETIMES", MON)
        with self.assertRaises(s.ScheduleError):
            s.normalize_rrule("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", MON)


class Phrases(unittest.TestCase):
    def check(self, text, **want):
        got = s.parse_phrase(text)
        for k, v in want.items():
            self.assertEqual(got[k], v, f"{text!r}: {k}")
        return got

    def test_no_anchor_means_from_last_done(self):
        self.check("every 30 days", kind="interval", interval_n=30, interval_unit="days")
        self.check("monthly", kind="interval", interval_n=1, interval_unit="months")
        self.check("weekly", kind="interval", interval_n=1, interval_unit="weeks")
        self.check("quarterly", kind="interval", interval_n=3, interval_unit="months")
        self.check("Every two weeks", kind="interval", interval_n=2, interval_unit="weeks")
        self.check("every 30 days from when given at 5:30pm", kind="interval", interval_n=30, due_time="17:30")

    def test_anchor_means_fixed(self):
        self.check("every Saturday", kind="rrule", rrule="FREQ=WEEKLY;BYDAY=SA")
        self.check("every other sunday", kind="rrule", rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=SU")
        self.check("every sat and sun", kind="rrule", rrule="FREQ=WEEKLY;BYDAY=SA,SU")
        self.check("every 2 weeks on friday", kind="rrule", rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=FR")
        self.check("monthly on the 1st", kind="rrule", rrule="FREQ=MONTHLY;BYMONTHDAY=1")
        self.check("monthly on the last day", kind="rrule", rrule="FREQ=MONTHLY;BYMONTHDAY=-1")
        self.check("quarterly on the 7th", kind="rrule", rrule="FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=7")
        self.check("on the 13th of every month", kind="rrule", rrule="FREQ=MONTHLY;BYMONTHDAY=13")
        self.check("yearly on Apr 15", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=15")
        self.check("every year on 15 april", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=15")
        self.check("yearly on 04-15", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=15")
        self.check("every april", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=1")
        self.check("every 10 days fixed", kind="rrule", rrule="FREQ=DAILY;INTERVAL=10")

    def test_seasons_and_weekend(self):
        self.check("seasonally", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=3,6,9,12;BYMONTHDAY=21")
        self.check("every spring and fall", kind="rrule", rrule="FREQ=YEARLY;BYMONTH=3,9;BYMONTHDAY=21")
        self.check("every 2 weeks on the weekend", kind="interval", interval_n=2, flex="weekend")
        self.check("every weekend", kind="interval", interval_n=1, interval_unit="weeks", flex="weekend")

    def test_unknown_and_conflicting(self):
        for bad in ("whenever", "every blue moon", "every saturday from when done"):
            with self.assertRaises(s.ScheduleError, msg=bad):
                s.parse_phrase(bad)

    def test_every_parsed_rule_is_valid(self):
        for text in ("every saturday", "monthly on the 31st", "seasonally", "yearly on mar 1", "every other tuesday"):
            got = s.parse_phrase(text)
            s.normalize_rrule(got["rrule"], MON)
        with self.assertRaises(s.ScheduleError):   # next Feb 29 is more than 400 days away
            s.normalize_rrule(s.parse_phrase("yearly on feb 29")["rrule"], MON)

    def test_describe(self):
        self.assertEqual(s.describe_rule("interval", None, 30, "days", "exact"), "every 30 days after it's done")
        self.assertEqual(s.describe_rule("rrule", "FREQ=WEEKLY;BYDAY=SA", None, None, "exact"), "every Saturday")
        self.assertEqual(s.describe_rule("rrule", "FREQ=YEARLY;BYMONTH=3,9;BYMONTHDAY=21", None, None, "weekend"),
                         "every spring and fall, on a weekend")
        self.assertEqual(s.describe_rule("rrule", "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=7", None, None, "exact"),
                         "quarterly on the 7th")


if __name__ == "__main__":
    unittest.main()
