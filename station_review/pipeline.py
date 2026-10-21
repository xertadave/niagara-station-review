"""Upload -> facts -> findings -> a short system summary for the report."""
from datetime import datetime

from .bog import Bog
from .checks import run_checks, device_groups
from .extract import extract


def summarise(F):
    groups = device_groups(F)
    g = '; '.join(f"{len(v)} × {v[0]['vendor']} {v[0]['model']} ({k[1]})" for k, v in groups.items())
    in_groups = {d['path'] for v in groups.values() for d in v}
    other = [d for d in F['devices'] if d['type'] == 'bac:BacnetDevice' and d['path'] not in in_groups]
    meters = [d for d in F['devices'] if d['type'] in ('ma:ModbusAsyncDevice', 'mt:ModbusTcpDevice', 'mbus:MbusDevice')]
    nm = sum(1 for d in meters if d['type'] != 'mbus:MbusDevice')
    nb = sum(1 for d in meters if d['type'] == 'mbus:MbusDevice')
    newest = max((p for p in F['peers'] if p['enabled'] and p['version']), key=lambda p: [int(x) for x in p['version'].split('.') if x.isdigit()], default=None)
    return {'groups': g, 'devices': '; '.join(f"{d['vendor']} {d['model']}".strip() + f" ({d['name']})" for d in other),
            'metering': ', '.join(x for x in [f"{nm} Modbus meters" if nm else '', f"{nb} M-Bus heat meters" if nb else ''] if x),
            'supervisor': f"{newest['name']} (Niagara {newest['version']})" if newest else ''}


def analyse(data, today=None):
    bog = Bog(data)
    F = extract(bog)
    items = run_checks(F, today or datetime.now())
    return F, items, summarise(F)
