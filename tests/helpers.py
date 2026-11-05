"""Independently invented configuration for tests; never copied from user settings."""
import yaml


def settings():
    return {'version':2,
            'defaults':{'timezone':'UTC','browser':'chrome','period':'this_month','base_currency':'USD','local_currency':'KRW','yellow_excess_max':'17'},
            'budget':{'spreadsheet_id':'synthetic-sheet','sheet':'Example tab'},
            'category_aliases':{'sample':'Category A'},'banks':{}}


def write_settings(data,config=None):
    data.mkdir(parents=True,exist_ok=True)
    path=data/'settings.yaml'
    path.write_text(yaml.safe_dump(config or settings(),sort_keys=False))
    return path
