import json
from datetime import date, timedelta
from decimal import Decimal
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_report import render, budget_weeks
from finance import ReviewError


def fixture():
    return {'base_currency':'USD','status':'ready','mode':'category','start':'2026-11-02','end':'2026-11-08','timezone':'UTC','is_current_week':True,
            'coverage':{'complete':False,'days':[{'cutoff':'2026-11-05T03:00:00Z'}]},'all_within_budget':True,
            'rate_snapshot':{'base_currency':'USD','retrieved_at':'2026-11-05T03:00:00Z','rates':{'KRW':{'base_per_unit':'0.005','source_url':'https://wise.com/gb/currency-converter/krw-to-usd-rate'}}},
            'category_report':{'category':'Category A','local_currency':'KRW','monthly_base':{'2026-11':'300'},
              'allowance_base':'70','allowance_local':'14000','spent_base':'80','spent_local':'16000','remaining_base':'-10','remaining_local':'-2000','excess_local':'2000',
              'percent_used':'114.2857','daily_allowances_base':['10']*7,
              'segments':[{'date':f'2026-11-{i:02}','allowance_local':'2000'} for i in range(2,9)],
              'days':[{'date':f'2026-11-{i:02}','status':'complete' if i<5 else 'partial' if i==5 else 'missing','total_local':'4000' if i<6 else None,
                       'transactions':[{'local_time':'09:20','description':'First shop','spent_local':'1000'},
                                       {'local_time':'13:40','description':'Second shop','spent_local':'3000'}] if i<6 else []} for i in range(2,9)]}}


class RenderTest(unittest.TestCase):
    def test_category_format_and_script_escaping(self):
        with tempfile.TemporaryDirectory() as d:
            data=fixture();data['category_report']['days'][0]['transactions'][0]['description']='</script><script>alert(1)</script>'
            path=Path(d)/'chart.html';text=render(data,path);html=path.read_text()
            self.assertIn('| 📆 Weekly | $70.00 | KRW 14,000 |',text)
            self.assertIn('| 🍽️ Spent this week | $80.00 | KRW 16,000 |',text)
            self.assertNotIn('</script><script>alert',html)
            self.assertIn('\\u003c/script',html)
            self.assertNotIn('__REPORT_JSON__',html)

    def test_historical_week_labels(self):
        with tempfile.TemporaryDirectory() as d:
            data=fixture();data['is_current_week']=False
            self.assertIn('🍽️ Spent in period',render(data,Path(d)/'chart.html'))

    def test_nonready_report_cannot_render(self):
        with self.assertRaises(ReviewError): render({'status':'needs-classification'})

    def test_ledger_only_latest_posting_preserves_date_precision(self):
        data = fixture()
        data.update(mode='general',categories=[],latest_transaction='2026-11-04')
        data['coverage']['usable_for_review'] = False
        self.assertIn('Latest recorded transaction · 2026-11-04. Coverage',render(data))

    def test_general_base_warnings_and_all_clear(self):
        data=fixture();data['mode']='general'
        data['categories']=[
            {'category':'Category A','status':'yellow','spent_base':'80.004','allowance_base':'70','excess_base':'10.004'},
            {'category':'Category B','status':'red','spent_base':'100.004','allowance_base':'70','excess_base':'30.004'},
            {'category':'Category C','status':'green','spent_base':'30','allowance_base':'70','excess_base':'0'},
        ]
        text=render(data)
        self.assertIn('🟡 Category A: $80.00 spent / $70.00 allowance; $10.00 over.',text)
        self.assertIn('**Total over budget · $40.01**',text)
        self.assertNotIn('Category C',text)
        self.assertNotIn('visualize',text)
        data['categories']=data['categories'][2:]
        text=render(data)
        self.assertIn('🟢 All categories',text)
        self.assertNotIn('Total over budget',text)

    def segments(self,start,count,amount='1000'):
        first=date.fromisoformat(start)
        return [{'date':(first+timedelta(days=i)).isoformat(),'allowance_local':amount} for i in range(count)]

    def test_two_full_weeks_use_one_spending_total(self):
        weeks=budget_weeks(self.segments('2026-11-02',14),'3500')
        self.assertEqual([len(w['segments']) for w in weeks],[7,7])
        self.assertEqual([w['filled_local'] for w in weeks],[Decimal('3500'),Decimal('0')])
        self.assertEqual([w['allowance_local'] for w in weeks],[Decimal('7000')]*2)

    def test_partial_weeks_overflow_thursday_to_wednesday(self):
        weeks=budget_weeks(self.segments('2026-11-05',7),'5000')
        self.assertEqual([(w['start'],w['end']) for w in weeks],[('2026-11-05','2026-11-08'),('2026-11-09','2026-11-11')])
        self.assertEqual([len(w['segments']) for w in weeks],[4,3])
        self.assertEqual([w['filled_local'] for w in weeks],[Decimal('4000'),Decimal('1000')])

    def test_short_period_and_week_boundary(self):
        self.assertEqual(len(budget_weeks(self.segments('2026-11-03',3),'0')),1)
        self.assertEqual([len(w['segments']) for w in budget_weeks(self.segments('2026-11-08',2),'0')],[1,1])

    def test_cross_month_allowances_and_three_bars(self):
        segments=self.segments('2026-10-29',13)
        for s in segments:s['allowance_local']='10' if s['date'].startswith('2026-10') else '20'
        weeks=budget_weeks(segments,'185')
        self.assertEqual([w['allowance_local'] for w in weeks],[Decimal(50),Decimal(140),Decimal(40)])
        self.assertEqual([w['filled_local'] for w in weeks],[Decimal(50),Decimal(135),Decimal(0)])
        self.assertEqual(sum(w['filled_local'] for w in weeks),Decimal(185))
        over=budget_weeks(segments,'250')
        self.assertEqual([w['filled_local'] for w in over],[Decimal(50),Decimal(140),Decimal(40)])

    def test_zero_budget_and_net_refunds(self):
        self.assertEqual([w['filled_local'] for w in budget_weeks(self.segments('2026-11-05',7,'0'),'100')],[Decimal(0)]*2)
        self.assertEqual([w['filled_local'] for w in budget_weeks(self.segments('2026-11-05',7),'-100')],[Decimal(0)]*2)

    def test_renderer_includes_week_allocations(self):
        with tempfile.TemporaryDirectory() as d:
            data=fixture();c=data['category_report']
            c['segments']=self.segments('2026-11-05',7)
            c['spent_local']='5000'
            path=Path(d)/'chart.html';render(data,path)
            payload=path.read_text().split('  const data = ',1)[1].split(';\n  const root',1)[0]
            weeks=json.loads(payload)['category_report']['budget_weeks']
            self.assertEqual([w['filled_local'] for w in weeks],['4000','1000'])


    def test_rate_output_uses_configured_base_currency(self):
        data=fixture();data['mode']='general';data['categories']=[]
        data['base_currency']='CAD';data['rate_snapshot']['base_currency']='CAD'
        text=render(data)
        self.assertIn('1 KRW = 0.005 CAD',text)
        self.assertNotIn('€',text)


if __name__=='__main__':unittest.main()
