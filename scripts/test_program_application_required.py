"""Synthetic readiness only; no network, credentials, DB or provider calls."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from ingest.content_filters import empty_filters,field,missing_filters,validate_filters,validate_claim_filter,SCHEMA

def ready():
    d=empty_filters('program')
    d.update(topic=field('language_learning'),delivery=field('online'),audience=field('other'),location=field(status='not_applicable'),application=field({'deadlineKind':'fixed','start':{'value':'2026-10-01','precision':'day'},'end':{'value':'2026-10-31','precision':'day'},'sourceStatus':'unknown'}))
    return d

class ApplicationDates(unittest.TestCase):
    def test_date_only_and_optional_time(self):
        d=ready();self.assertEqual(validate_filters(d),d);self.assertEqual(missing_filters(d),[])
        d['application']['value']['end']={'value':'2026-10-31T18:00:00+09:00','precision':'minute'}
        self.assertEqual(validate_filters(d),d);self.assertEqual(missing_filters(d),[])

    def test_legacy_readable_but_claim_blocked(self):
        now=datetime.now(timezone.utc)
        for kind in ['start_missing','no_deadline']:
            d=ready()
            d['application']['value']['start']=None
            if kind=='no_deadline':d['application']['value'].update(deadlineKind='none',end=None)
            self.assertEqual(validate_filters(d),d);self.assertIn('application',missing_filters(d))
            context={'schema':SCHEMA,'filterVersion':1,'data':d,'claimedAt':now.isoformat(),'leaseUntil':(now+timedelta(minutes=10)).isoformat(),'workerId':'synthetic-worker'}
            with self.assertRaises(ValueError):validate_claim_filter(context,worker='synthetic-worker')

    def test_dates_invalid(self):
        for change in [{'end':None},{'start':{'value':'2026-11-01','precision':'day'}},{'start':{'value':'2026-02-30','precision':'day'}}]:
            d=ready();d['application']['value'].update(copy.deepcopy(change))
            with self.assertRaises(ValueError):validate_filters(d)

    def test_other_categories_unchanged(self):
        d=empty_filters('youth_space');d.update(spaceKind=field('news'),location=field(status='not_applicable'))
        self.assertEqual(missing_filters(validate_filters(d)),[])
        d=empty_filters('event');self.assertNotIn('application',missing_filters(validate_filters(d)))

if __name__=='__main__':unittest.main()
