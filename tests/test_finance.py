from contextlib import closing
import csv
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from finance import (Ledger, ReviewError, dump, epoch_us, match,
                     normalize, parse_instant, period, report, from_us, to_minor, from_minor)
import yaml
from helpers import write_settings, settings


class LedgerTest(unittest.TestCase):
    def setUp(self):
        class FixedTime(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls(2026,11,10,tzinfo=timezone.utc).astimezone(tz)
        self.clock = patch('finance.datetime',FixedTime)
        self.clock.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.l = Ledger(self.root/'data')
        write_settings(self.l.data)
        self.account = self.l.configure_account('wise','1','Account A','USD','UTC')
        self.rules([{'category':'Category A','keywords':['shop','long shop']},
                    {'category':'Category B','keywords':['coffee']}])
        self.budget = {'categories':{'Category A':{'2026-10':'310','2026-11':'300'},
                                     'Category B':{'2026-10':'31','2026-11':'30'}}}
        self.fx = {'base_currency':'USD','retrieved_at':'2026-11-05T12:00:00Z','rates':{'KRW':{'base_per_unit':'0.005','source_url':'https://wise.com/gb/currency-converter/krw-to-usd-rate'},
                     'GBP':{'base_per_unit':'0.025','source_url':'https://wise.com/gb/currency-converter/gbp-to-usd-rate'}}}
        self.asof = '2026-11-05T12:00:00Z'

    def tearDown(self):
        self.l.close()
        self.tmp.cleanup()
        self.clock.stop()

    def rules(self,rules):
        (self.l.data/'rules.yaml').write_text(yaml.safe_dump({'rules':rules},sort_keys=False))

    def row(self,tid='x',timestamp='2026-11-02T12:00:00Z',amount='-10',description='shop',kind='expense',cur='USD'):
        return {'bank_transaction_id':tid,'timestamp':timestamp,'amount':amount,'currency':cur,'description':description,'kind':kind}

    def ingest(self,rows,account=None,name='file.csv',start='2026-11-01T00:00:00Z',end='2026-11-06T00:00:00Z',cutoff=None):
        p = self.root/name
        with p.open('w') as f:
            w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))) if rows else list(self.row()))
            w.writeheader();w.writerows(rows)
        return self.l.ingest(p,account or self.account,'normalized')

    def classify(self,start='2026-11-01',end='2026-11-05',zone='UTC'):
        return self.l.classify(start,end,zone)

    def report(self,category=None,local='KRW',start='2026-11-02',end='2026-11-08',zone='UTC'):
        return report(self.l,start,end,zone,self.budget,self.fx,category,local,self.asof,self.asof)

    def test_idempotent_overlapping_imports_and_refund_ids(self):
        rows=[self.row(),self.row(timestamp='2026-11-03T12:00:00Z',amount='10',kind='refund')]
        self.assertEqual(self.ingest(rows)['added'],2)
        self.assertEqual(self.ingest(rows)['added'],0)
        self.assertEqual(self.ingest(rows[:1],name='overlap.csv')['added'],0)
        self.assertEqual(len(self.l.select('2026-11-01','2026-11-05','UTC')),2)

    def test_collision_rolls_back_whole_import(self):
        self.ingest([self.row()])
        with self.assertRaisesRegex(ReviewError,'Conflicting'):
            self.ingest([self.row('new',timestamp='2026-11-03T00:00:00Z'),self.row(amount='-20')],name='conflict.csv')
        self.assertEqual(self.l.db.execute('select count(*) from transactions').fetchone()[0],1)

    def test_identical_rows_in_file_need_user(self):
        with self.assertRaisesRegex(ReviewError,'Indistinguishable'):
            self.ingest([self.row(),self.row()])
        self.assertEqual(self.l.db.execute('select count(*) from transactions').fetchone()[0],0)

    def test_simultaneous_distinct_ids_and_multiple_accounts(self):
        self.ingest([self.row('a'),self.row('b')])
        acc=self.l.configure_account('other','1','Savings','USD','UTC')
        self.ingest([self.row('a')],account=acc,name='other.csv')
        self.assertEqual(len(self.l.select('2026-11-02','2026-11-02','UTC')),3)

    def test_precision_and_local_day_boundaries(self):
        self.ingest([self.row(timestamp='2026-11-02T23:59:59.123456Z')])
        self.assertFalse(self.l.select('2026-11-02','2026-11-02','Asia/Singapore'))
        row=self.l.select('2026-11-03','2026-11-03','Asia/Singapore')[0]
        self.assertEqual(row['local_time'],'07:59')
        self.assertTrue(row['timestamp_unix'].endswith('.123456'))
        with self.assertRaises(ReviewError): parse_instant('2026-11-02T23:59:59.1234567Z')
        with self.assertRaises(ReviewError): parse_instant('02-11-2026 12:00:00')
        with self.assertRaises(ReviewError): parse_instant('2026-11-01T01:30:00','America/New_York')
        with self.assertRaises(ReviewError): parse_instant('2026-03-08T02:30:00','America/New_York')

    def test_account_configuration_and_currency_checked(self):
        acc=self.l.configure_account('wise','2','Account B','USD','UTC')
        self.assertEqual(self.ingest([self.row()],account=acc)['added'],1)
        with self.assertRaisesRegex(ReviewError,'Unknown account'):
            self.ingest([self.row()],account='missing')
        with self.assertRaisesRegex(ReviewError,'currency'):
            self.ingest([self.row(cur='KRW')])

    def test_literal_longest_keyword_and_stable_tie(self):
        rules=[{'category':'A','keywords':['long shop','Uber * Eats']},{'category':'B','keywords':['long shop','shop']}]
        self.assertEqual(match({'description':'LONG SHOP'},rules),'A')
        self.assertEqual(match({'description':'Uber * Eats'},rules),'A')
        self.assertIsNone(match({'description':'Uber random Eats'},rules))
        self.assertEqual(match({'merchant':'long shop'},rules),'A')

    def test_rule_update_scoped_and_manual_preserved(self):
        self.ingest([self.row('a'),self.row('b',timestamp='2026-11-03T12:00:00Z'),self.row('c',timestamp='2026-11-04T12:00:00Z')])
        self.classify()
        self.l.assign([1],'Special')
        self.l.add_rule('shop','New','2026-11-02','2026-11-03','UTC')
        rows=self.l.select('2026-11-01','2026-11-05','UTC')
        self.assertEqual([r['category'] for r in rows],['Special','New','Category A'])
        self.classify()
        self.assertEqual(self.l.select('2026-11-04','2026-11-04','UTC')[0]['category'],'New')

    def test_classification_requests_only_remaining_unclassified(self):
        self.ingest([self.row('manual',description='unknown manual'),
                     self.row('rule',description='shop'),
                     self.row('pending',description='unknown pending')])
        self.l.assign([1],'Category B')
        result=self.classify()
        self.assertEqual([r['id'] for r in result['unclassified']],[3])
        self.assertEqual([r['category'] for r in self.l.select('2026-11-01','2026-11-05','UTC')],
                         ['Category B','Category A',None])
        self.l.assign([3],'Category A')
        self.assertEqual(self.classify()['unclassified'],[])
        self.assertEqual(self.classify()['unclassified'],[])

    def test_unknown_gates_category_report_and_credit_kind(self):
        self.ingest([self.row(),self.row('b',description='unknown merchant',timestamp='2026-11-03T12:00:00Z')])
        self.classify()
        self.assertEqual(self.report('Category A')['status'],'needs-classification')
        self.l.assign([2],'Category A')
        self.assertEqual(self.report('Category A')['status'],'ready')
        self.ingest([self.row('credit',timestamp='2026-11-04T00:00:00Z',amount='12',kind='credit-review')],name='credit.csv')
        self.classify()
        self.assertEqual(self.report()['status'],'needs-classification')
        self.l.assign([3],'Category A','refund')
        self.assertEqual(self.report()['status'],'ready')

    def test_refunds_nonexpenses_and_alternative_currency(self):
        self.ingest([self.row(amount='-100'),self.row('refund','2026-11-03T00:00:00Z','20',kind='refund'),
                     self.row('income','2026-11-04T00:00:00Z','1000','salary','income'),
                     self.row('internal','2026-11-04T01:00:00Z','-1000','Converted','internal')])
        self.classify();self.l.assign([3],'Nonexpense A');self.l.assign([4],'Nonexpense B')
        r=self.report('Category A','GBP')
        c=r['category_report']
        self.assertEqual(c['spent_base'],Decimal(80))
        self.assertEqual(c['spent_local'],Decimal(3200))
        self.assertEqual(sum(d['total_local'] or Decimal(0) for d in c['days']),Decimal(3200))
        self.assertIsNone(c['days'][-1]['total_local'])
        self.assertEqual(len(c['segments']),7)
        self.assertFalse(r['issues'])

    def test_zero_budget_and_thresholds(self):
        self.budget['categories']['Category A']['2026-11']='0'
        self.ingest([self.row(amount='-17')]);self.classify()
        c=self.report('Category A')['category_report']
        self.assertEqual(c['status'],'yellow');self.assertIsNone(c['percent_used'])
        self.assertEqual(c['remaining_base'],Decimal(-17))
        self.ingest([self.row('b',timestamp='2026-11-03T00:00:00Z',amount='-0.01')],name='more.csv');self.classify()
        self.assertEqual(self.report('Category A')['category_report']['status'],'red')

    def test_cross_month_budget_and_missing_month(self):
        self.ingest([self.row(timestamp='2026-10-31T12:00:00Z')],start='2026-10-01T00:00:00Z',end='2026-11-06T00:00:00Z')
        self.classify('2026-10-31','2026-11-02')
        self.budget['categories']['Category A']['2026-10']='620'
        c=self.report('Category A',start='2026-10-31',end='2026-11-02')['category_report']
        self.assertEqual(c['allowance_base'],Decimal(40))
        del self.budget['categories']['Category A']['2026-10']
        self.assertEqual(self.report(start='2026-10-31',end='2026-11-02')['status'],'budget-mapping-required')

    def test_report_cutoff_is_ephemeral(self):
        self.ingest([self.row()]);self.classify()
        cov=self.l.coverage('2026-11-02','2026-11-08','UTC',self.asof,self.asof)
        self.assertEqual([d['status'] for d in cov['days']],['complete']*3+['partial']+['missing']*3)
        self.assertTrue(self.report()['all_within_budget'])
        unknown=self.l.coverage('2026-11-02','2026-11-08','UTC',self.asof)
        self.assertFalse(unknown['complete'])
        self.assertEqual(unknown['days'][0]['status'],'partial')
        self.assertEqual(unknown['days'][1]['status'],'missing')
        tables={r[0] for r in self.l.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'accounts','transactions'})

    def test_unknown_category_flag_and_stale_rate_block(self):
        self.ingest([self.row()]);self.l.assign([1],'Retired')
        self.assertEqual(self.report()['status'],'budget-mapping-required')
        self.fx['retrieved_at']='2026-11-01T00:00:00Z'
        with self.assertRaisesRegex(ReviewError,'stale'):self.report()

    def test_wise_normalization_foreign_charge_and_precision(self):
        account=self.l.db.execute('select * from accounts where id=?',(self.account,)).fetchone()
        row={'TransferWise ID':'CARD-X','Date Time':'02-11-2026 12:00:00.123','Amount':'-1.20','Currency':'USD',
             'Description':'Card transaction of 200 KRW issued by Shop','Transaction Details Type':'CARD'}
        n=normalize(row,'wise',account)
        self.assertEqual(n['charged_currency'],'KRW');self.assertEqual(n['charged_amount_minor'],200)
        self.assertEqual(n['amount_minor'],-120);self.assertEqual(from_us(n['timestamp_us']).microsecond,123000)
        self.assertNotIn('matched_keyword',n)

    def test_empty_invalid_headers_cannot_claim_coverage(self):
        p=self.root/'invalid.csv';p.write_text('unrelated,columns\n')
        with self.assertRaisesRegex(ReviewError,'headers'):
            self.l.ingest(p,self.account,'wise')
        self.assertEqual(self.l.db.execute('select count(*) from transactions').fetchone()[0],0)

    def test_malformed_rules_fail_clearly(self):
        (self.l.data/'rules.yaml').write_text('rules: [null]')
        with self.assertRaisesRegex(ReviewError,'category string'):
            self.l.rules()

    def old_schema(self, amount='-10'):
        with self.l.db:
            self.l.db.execute('DROP TABLE transactions');self.l.db.execute('DROP TABLE accounts')
            self.l.db.execute("CREATE TABLE accounts(id TEXT PRIMARY KEY,name TEXT,currency TEXT,source_timezone TEXT,tracked INTEGER)")
            self.l.db.execute("""CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id TEXT,bank_transaction_id TEXT,
                timestamp_us INTEGER,description TEXT,merchant TEXT,payment_reference TEXT,details_type TEXT,
                amount TEXT,currency TEXT,charged_amount TEXT,charged_currency TEXT,kind TEXT,category TEXT,classification_origin TEXT)""")
            self.l.db.execute("INSERT INTO accounts VALUES ('wise:1','Account A','USD','UTC',1)")
            self.l.db.execute("""INSERT INTO transactions VALUES (1,'wise:1','x',1793620800000000,
                'shop','','','',?,'USD','200','KRW','expense','Category A','manual')""",(amount,))
            self.l.db.execute('PRAGMA user_version=3')

    def test_v3_upgrade_types_money_in_place_and_preserves_classifications(self):
        self.old_schema()
        data=self.l.data;self.l.close();self.l=Ledger(data)
        self.assertEqual(self.l.db.execute('PRAGMA user_version').fetchone()[0],4)
        tables={r[0] for r in self.l.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'accounts','transactions'})
        self.assertTrue(all(row['strict']==0 for row in self.l.db.execute('PRAGMA table_list') if row['name'] in tables))
        row=self.l.db.execute('SELECT * FROM transactions').fetchone()
        self.assertEqual(row['amount_minor'],-1000);self.assertEqual(row['charged_amount_minor'],200)
        self.assertEqual(row['category'],'Category A');self.assertEqual(row['classification_origin'],'manual')
        self.assertEqual(len(list((data/'backups').glob('*.sqlite3'))),1)
        self.assertFalse(self.l.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_invalid_money_migration_rolls_back_existing_file(self):
        self.old_schema('0.001')
        data=self.l.data;self.l.close()
        with self.assertRaisesRegex(ReviewError,'fractional minor'):
            Ledger(data)
        import sqlite3
        with closing(sqlite3.connect(data/'transactions.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT amount FROM transactions').fetchone()[0],'0.001')
        # Restore a valid fixture so tearDown can close a normal Ledger.
        with closing(sqlite3.connect(data/'transactions.sqlite3')) as db, db:
            db.execute("UPDATE transactions SET amount='1.00'")
        self.l=Ledger(data)

    def test_declared_types_and_lossless_money(self):
        import sqlite3
        self.ingest([self.row()])
        for statement in ("UPDATE accounts SET tracked=2", "UPDATE accounts SET currency='euro'",
                          "UPDATE transactions SET kind='other'", "UPDATE transactions SET charged_amount_minor=100"):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.l.db:self.l.db.execute(statement)
        types={row[1]:row[2] for row in self.l.db.execute('PRAGMA table_info(transactions)')}
        self.assertEqual(types['amount_minor'],'INTEGER');self.assertEqual(types['timestamp_us'],'INTEGER')
        self.assertEqual(self.l.db.execute('SELECT typeof(amount_minor),typeof(timestamp_us) FROM transactions').fetchone()[:],('integer','integer'))
        self.assertEqual(to_minor('12.34','USD'),1234)
        self.assertEqual(to_minor('123','KRW'),123)
        self.assertEqual(to_minor('1.234','BHD'),1234)
        self.assertEqual(from_minor(1234,'USD'),Decimal('12.34'))
        with self.assertRaises(ReviewError):to_minor('0.001','USD')
        with self.assertRaises(ReviewError):to_minor('1.5','KRW')
        with self.assertRaises(ReviewError):to_minor(str(2**63),'KRW')

    def test_daily_backups_are_created_before_first_write_only(self):
        data=self.root/'daily'
        ledger=Ledger(data)
        write_settings(data)
        self.assertFalse(list((data/'backups').glob('*.sqlite3')))
        ledger.configure_account('bank','1','Account A','USD','UTC')
        path=data/'backups/2026-11-10.sqlite3'
        self.assertTrue(path.exists())
        original=path.read_bytes()
        ledger.configure_account('bank','2','Savings','USD','UTC')
        self.assertEqual(original,path.read_bytes())
        with closing(__import__('sqlite3').connect(path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],0)
        ledger.close()
        ledger=Ledger(data)
        self.assertEqual(len(list((data/'backups').glob('*.sqlite3'))),1)
        ledger.configure_account('bank','3','Other','USD','UTC')
        self.assertEqual(original,path.read_bytes())
        ledger.close()

    def test_reads_do_not_create_daily_backup(self):
        for p in (self.l.data/'backups').glob('*.sqlite3'):p.unlink()
        self.l.select('2026-11-01','2026-11-05','UTC')
        self.l.coverage('2026-11-01','2026-11-05','UTC')
        self.assertFalse(list((self.l.data/'backups').glob('*.sqlite3')))

    def test_retention_keeps_at_most_seven_daily_snapshots(self):
        folder=self.l.data/'backups'
        for p in folder.glob('*.sqlite3'):p.unlink()
        for day in range(1,11):
            (folder/f'2026-11-{day:02}.sqlite3').write_bytes(b'daily')
        # Multiple older timestamp-style snapshots on one day are consolidated.
        (folder/'20261109T000000000000Z.sqlite3').write_bytes(b'legacy')
        (folder/'20261109T010000000000Z.sqlite3').write_bytes(b'legacy duplicate')
        (folder/'notes.txt').write_text('unrelated')
        self.l.prune_backups()
        self.assertEqual(sorted(p.name for p in folder.glob('*.sqlite3')),
                         [f'2026-11-{day:02}.sqlite3' for day in range(4,11)])
        self.assertTrue((folder/'notes.txt').exists())

    def test_new_day_creates_one_new_backup_and_prunes_oldest(self):
        folder=self.l.data/'backups'
        for p in folder.glob('*.sqlite3'):p.unlink()
        (folder/'2026-11-03.sqlite3').write_bytes(b'expired')
        self.l.configure_account('wise','2','Another','USD','UTC')
        self.assertFalse((folder/'2026-11-03.sqlite3').exists())
        class NextDay(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls(2026,11,11,tzinfo=timezone.utc).astimezone(tz)
        with patch('finance.datetime',NextDay):
            self.l.configure_account('wise','3','Next','USD','UTC')
            self.l.configure_account('wise','4','Again','USD','UTC')
        self.assertEqual(sorted(p.name for p in folder.glob('*.sqlite3')),
                         ['2026-11-10.sqlite3','2026-11-11.sqlite3'])
        with closing(__import__('sqlite3').connect(folder/'2026-11-11.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],2)

    def test_backup_date_uses_configured_timezone(self):
        settings=self.l.data/'settings.yaml'
        config=yaml.safe_load(settings.read_text());config['defaults']['timezone']='America/Los_Angeles'
        settings.write_text(yaml.safe_dump(config))
        self.l.before_write()
        self.assertTrue((self.l.data/'backups/2026-11-09.sqlite3').exists())


    def test_base_currency_local_currency_threshold_and_timezone_from_settings(self):
        config=settings();config['defaults'].update(base_currency='CHF',local_currency='GBP',yellow_excess_max='2',timezone='UTC')
        write_settings(self.l.data,config)
        self.ingest([self.row(amount='-75')]);self.classify()
        fx={'base_currency':'CHF','retrieved_at':self.asof,'rates':{
            'USD':{'base_per_unit':'1','source_url':'https://wise.com/gb/currency-converter/usd-to-chf-rate'},
            'GBP':{'base_per_unit':'2','source_url':'https://wise.com/gb/currency-converter/gbp-to-chf-rate'}}}
        result=report(self.l,'2026-11-02','2026-11-08',None,self.budget,fx,'sample',as_of=self.asof,cutoff=self.asof)
        self.assertEqual(result['base_currency'],'CHF');self.assertEqual(result['timezone'],'UTC')
        c=result['category_report'];self.assertEqual(c['local_currency'],'GBP')
        self.assertEqual(c['category'],'Category A');self.assertEqual(c['spent_base'],Decimal(75))
        self.assertEqual(c['spent_local'],Decimal('37.5'));self.assertEqual(c['status'],'red')


if __name__=='__main__':unittest.main()
