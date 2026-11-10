#!/usr/bin/env python3
"""Format report JSON as Markdown; optionally create a category chart fragment."""
import argparse
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from finance import ReviewError, read_json, currency_digits


def money(n,cur):
    places = currency_digits(cur)
    rounded=Decimal(str(n)).quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
    symbol={'EUR':'€','JPY':'¥','THB':'฿','USD':'$','GBP':'£'}.get(cur,cur+' ')
    return f'{symbol}{rounded:,.{places}f}'


def budget_weeks(segments, spent):
    """Split calendar weeks and allocate one shared spending total in order."""
    weeks=[]
    remaining=max(Decimal(str(spent)),Decimal(0))
    for segment in segments:
        day=date.fromisoformat(segment['date'])
        monday=(day-timedelta(days=day.weekday())).isoformat()
        if not weeks or weeks[-1]['monday']!=monday:
            weeks.append({'monday':monday,'segments':[]})
        weeks[-1]['segments'].append(segment)
    for week in weeks:
        week['start']=week['segments'][0]['date']
        week['end']=week['segments'][-1]['date']
        week['allowance_local']=sum((Decimal(str(s['allowance_local'])) for s in week['segments']),Decimal(0))
        week['filled_local']=min(remaining,week['allowance_local'])
        remaining-=week['filled_local']
    return weeks


def budget_check_line(check, base):
    status = check['status']
    marker = {'red': '🔴 ', 'yellow': '🟡 ', 'green': ''}[status]
    if check['cadence'] == 'ongoing':
        limit = f"cumulative allowance through {check['allowance_end']}"
    else:
        limit = f"{check['month']} monthly limit"
    spent = money(check['spent_base'], base)
    allowance = money(check['allowance_base'], base)
    balance = (f"{money(check['excess_base'], base)} over" if status != 'green'
               else f"{money(check['remaining_base'], base)} left")
    return f"- {marker}**{check['category']}** · {spent} spent month to date / {allowance} {limit} · **{balance}**"


def render(data,chart_path=None):
    if data['status']!='ready':
        raise ReviewError(f"Report is not ready: {data['status']}. Resolve listed issues before reporting.")
    base=data['base_currency']
    lines=[f"{data['start']} to {data['end']} · {data['timezone']}"]
    if data['mode']=='general':
        warnings=[r for r in data.get('budget_checks', data['categories']) if r['status']!='green']
        if not warnings and data['all_within_budget']:
            lines.extend(['', '🟢 All categories within budget.'])
        elif not warnings:
            lines.extend(['', 'No over-budget categories in the available ledger.'])
        else:
            lines.append('')
            for r in sorted(warnings, key=lambda r: -Decimal(r['excess_base'])):
                if 'cadence' in r:
                    lines.append(budget_check_line(r, base))
                else:
                    lines.append(f"{'🔴' if r['status']=='red' else '🟡'} {r['category']}: {money(r['spent_base'],base)} spent / {money(r['allowance_base'],base)} allowance; {money(r['excess_base'],base)} over.")
            total_excess = sum(Decimal(r['excess_base']) for r in warnings)
            lines.extend(['', f"**Total over budget · {money(total_excess, base)}**"])
    else:
        c=data['category_report'];cur=c['local_currency']
        checks = [r for r in data.get('budget_checks', []) if r['category'] == c['category']]
        if checks:
            lines.append('')
            lines.extend(budget_check_line(r, base) for r in checks)
        # Rates are base-currency units per one foreign-currency unit.
        factor=Decimal(1) if cur==base else Decimal(1)/Decimal(str(data['rate_snapshot']['rates'][cur]['base_per_unit']))
        weekly=len(c['segments'])==7
        labels=[]
        if len(c['monthly_base'])==1:
            labels.append(('📅 Monthly',Decimal(str(next(iter(c['monthly_base'].values()))))))
            labels.append(('📆 Weekly' if weekly else '📆 Period',c['allowance_base']))
            labels.append(('☀️ Daily',c['daily_allowances_base'][0]))
        else:
            labels.extend((f'📅 Monthly ({m})',Decimal(str(v))) for m,v in c['monthly_base'].items())
            labels.append(('📆 Weekly' if weekly else '📆 Period',c['allowance_base']))
            labels.extend((f"☀️ Daily ({s['date']})",v) for s,v in zip(c['segments'],c['daily_allowances_base']))
        labels.extend([('🍽️ Spent this week' if data.get('is_current_week') else '🍽️ Spent in period',c['spent_base']),
                       ('✅ Remaining this week' if data.get('is_current_week') else '✅ Remaining in period',c['remaining_base'])])
        lines.extend(['',c['category'],'',f'| | {base} |' if cur==base else f'| | {base} | {cur} |','|---|---:|' if cur==base else '|---|---:|---:|'])
        for label,value in labels:
            lines.append(f'| {label} | {money(value,base)} |' if cur==base else f'| {label} | {money(value,base)} | {money(Decimal(str(value))*factor,cur)} |')
        if not chart_path:
            raise ReviewError('Category reports require --chart in the current chat working directory')
        template=Path(__file__).with_name('category-chart.html').read_text()
        # Avoid JSON closing the script element, including hostile bank descriptions.
        chart_data={**data,'category_report':{**c,'budget_weeks':budget_weeks(c['segments'],c['spent_local'])}}
        payload=json.dumps(chart_data,ensure_ascii=False,default=str).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        path=Path(chart_path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(template.replace('__REPORT_JSON__',payload))
        lines.extend(['',f'visualize{{"path":"{path}"}}'])
    if 'latest_transaction' in data and not data['coverage']['usable_for_review']:
        latest = data['latest_transaction']
        recorded = latest or 'unavailable'
        if latest and 'T' in latest:
            recorded = datetime.fromisoformat(latest).isoformat(sep=' ', timespec='minutes')
        lines.extend(['', f"Ledger only. Latest recorded transaction · {recorded}. Coverage is unverified."])
    elif 'latest_transaction' in data or not data['coverage']['complete']:
        observed=[d for d in data['coverage']['days'] if d['cutoff']]
        cutoff=observed[-1]['cutoff'] if observed else 'unavailable'
        note = f"Data cutoff · {cutoff}."
        if not data['coverage']['complete']:
            note += " Coverage is partial."
        lines.extend(['', note])
    lines.extend(['',f"Wise rates retrieved: {data['rate_snapshot']['retrieved_at']}."])
    for cur,r in data['rate_snapshot'].get('rates',{}).items():
        lines.append(f"1 {cur} = {r['base_per_unit']} {base} ([Wise]({r['source_url']})).")
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--chart',type=Path)
    args=p.parse_args()
    try:
        print(render(read_json(args.report),args.chart))
    except (ReviewError,KeyError,ValueError) as e:
        p.exit(2,str(e)+'\n')


if __name__=='__main__':main()
