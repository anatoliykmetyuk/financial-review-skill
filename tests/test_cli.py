from contextlib import closing
import sys,json,csv,subprocess,tempfile,unittest
from pathlib import Path
from helpers import write_settings, settings
runtime=Path(__file__).resolve().parents[1]
python=sys.executable
script=str(runtime/'scripts/finance.py')


class CliTest(unittest.TestCase):
    def test_sony_ingest_reads_browser_payload_from_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            args = [python,script,'--data-dir',str(data)]

            def run(*command, payload=None):
                result = subprocess.run(args + list(command),input=payload,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)

            run('configure',str(write_settings(data)))
            account = run('account','--bank','sony-bank','--source-id','fixture','--name','Fixture savings',
                          '--currency','CAD','--source-timezone','Asia/Singapore')['account']
            day = '2032-04-03'
            row = {'date':day,'currency':'CAD','description':'円普通預金へ振替','amount':'-42.13','balance_after':'51.68'}
            payload = json.dumps({'currency':'CAD','start':day,'end':day,'result_count':1,'rows':[row]})
            command = ('ingest','-','--adapter','sony-bank','--account',account)
            self.assertEqual(run(*command,payload=payload)['added'],1)
            self.assertEqual(run(*command,payload=payload)['added'],0)
            saved, = run('query','--start',day,'--end',day)
            self.assertEqual((saved['kind'],saved['local_date'],saved['local_time']),('internal',day,None))

    def test_full_workflow_for_both_modes(self):
        with tempfile.TemporaryDirectory() as d:
         root=Path(d)
         def cli(*args):
          r=subprocess.run([python,script,'--data-dir',str(root/'data'),*map(str,args)],capture_output=True,text=True)
          assert r.returncode==0,r.stderr
          return json.loads(r.stdout)
         cli('init')
         config=settings();config['ongoing_categories']=['Category A']
         cli('configure',write_settings(root/'data',config))
         cli('account','--bank','test','--source-id','1','--name','Fixture','--currency','USD','--source-timezone','UTC')
         (root/'statement.csv').write_text('timestamp,amount,currency,description,kind,bank_transaction_id\n2026-11-02T12:00:00Z,-100,USD,Fixture shop,expense,1\n')
         cli('ingest',root/'statement.csv','--adapter','normalized','--account','test:1')
         dates=['--start','2026-11-02','--end','2026-11-03','--timezone','UTC']
         assert len(cli('classify',*dates)['unclassified'])==1
         cli('rule','--keyword','Fixture shop','--category','Category A',*dates)
         cli('assign','1','--category','Category A')
         budget={'categories':{'Category A':{'2026-11':'300'}}}
         rates={'base_currency':'USD','retrieved_at':'2026-11-05T00:00:00Z','rates':{'GBP':{'base_per_unit':'0.025','source_url':'https://wise.com/gb/currency-converter/gbp-to-usd-rate'}}}
         (root/'budget.json').write_text(json.dumps(budget));(root/'rates.json').write_text(json.dumps(rates))
         for mode in ('general','category'):
          args=['report',*dates,'--as-of','2026-11-05T00:00:00Z','--budget',str(root/'budget.json'),'--rates',str(root/'rates.json')]
          if mode=='category':args+=['--category','Category A','--local-currency','GBP']
          report=cli(*args);assert report['status']=='ready'
          (root/'report.json').write_text(json.dumps(report))
          render=[python,str(runtime/'scripts/render_report.py'),str(root/'report.json')]
          if mode=='category':render+=['--chart',str(root/'chart.html')]
          r=subprocess.run(render,capture_output=True,text=True);assert r.returncode==0,r.stderr
          if mode=='general':
           self.assertIn('🔴 **Category A** · $100.00 spent month to date / $80.00 cumulative allowance through 2026-11-08',r.stdout)
          else:
           self.assertIn('GBP',r.stdout)
           self.assertIn('visualize',r.stdout)

    def test_bootstrap_from_empty_directory_and_preserve_existing_data(self):
        import sqlite3,yaml
        with tempfile.TemporaryDirectory() as d:
            data=Path(d)/'new-user'
            args=[python,script,'--data-dir',str(data),'init','--timezone','Europe/London',
                  '--budget-spreadsheet-id','example-budget','--budget-sheet','Household']
            result=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('settings.yaml','rules.yaml','transactions.sqlite3','backups'):
                self.assertTrue((data/name).exists(),name)
            settings=yaml.safe_load((data/'settings.yaml').read_text())
            self.assertEqual(settings['budget']['spreadsheet_id'],'example-budget')
            self.assertEqual(settings['budget']['sheet'],'Household')
            self.assertIsNone(settings['defaults']['base_currency'])
            self.assertFalse(json.loads(result.stdout)['setup']['ready'])
            self.assertEqual(settings['defaults']['timezone'],'Europe/London')
            self.assertEqual(settings['banks'],{})
            with closing(sqlite3.connect(data/'transactions.sqlite3')) as db, db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],0)
                db.execute("INSERT INTO accounts(id,name,currency) VALUES ('test','Preserve','USD')")
            rules=data/'rules.yaml';rules.write_text('rules: [{category: Category A, keywords: [shop]}]\n')
            original_settings=(data/'settings.yaml').read_bytes()
            result=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['created'],[])
            self.assertIn('shop',rules.read_text())
            self.assertEqual((data/'settings.yaml').read_bytes(),original_settings)
            with closing(sqlite3.connect(data/'transactions.sqlite3')) as db, db:
                self.assertEqual(db.execute("SELECT name FROM accounts WHERE id='test'").fetchone()[0],'Preserve')

    def test_setup_is_required_and_configure_guides_completion(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            data=Path(d)/'data'
            def run(*args):return subprocess.run([python,script,'--data-dir',str(data),*map(str,args)],capture_output=True,text=True)
            result=run('init');self.assertEqual(result.returncode,0,result.stderr)
            initial=yaml.safe_load((data/'settings.yaml').read_text())
            self.assertIsNone(initial['defaults']['timezone'])
            self.assertIsNone(initial['defaults']['base_currency'])
            self.assertIsNone(initial['defaults']['local_currency'])
            self.assertEqual(set(initial['budget']),{'spreadsheet_id','sheet'})
            self.assertEqual(initial['defaults']['browser'],'chrome')
            blocked=run('query','--start','2040-01-01','--end','2040-01-02')
            self.assertEqual(blocked.returncode,2);self.assertIn('setup',blocked.stderr)
            self.assertEqual(run('configure',data/'settings.yaml').returncode,2)
            config=settings();config['defaults'].update(timezone='Europe/Paris',base_currency='CHF',local_currency='CAD',yellow_excess_max='8')
            config['budget']['sheet']='Synthetic tab'
            draft=data/'setup.yaml';draft.write_text(yaml.safe_dump(config))
            configured=run('configure',draft);self.assertEqual(configured.returncode,0,configured.stderr)
            self.assertEqual(json.loads(configured.stdout)['setup']['missing'],['tracked accounts'])
            result=run('account','--bank','synthetic','--source-id','a','--name','Sample','--currency','CHF','--source-timezone','UTC')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(run('status').stdout)['setup']['ready'])
            reread=yaml.safe_load((data/'settings.yaml').read_text())
            self.assertEqual(reread,config)


if __name__=='__main__':unittest.main()
