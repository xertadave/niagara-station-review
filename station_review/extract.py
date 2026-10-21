"""Pull the facts the checks need out of a parsed station.  No judgement happens here."""
import re
from collections import Counter, defaultdict

from .bog import walk, child, val, comps, path, status_bits, NULL_BIT, units

POINT_TYPES = ('c:NumericPoint', 'c:NumericWritable', 'c:BooleanPoint', 'c:BooleanWritable',
               'c:EnumPoint', 'c:EnumWritable', 'c:StringPoint', 'c:StringWritable')
LINK_TYPES = ('b:Link', 'b:ConversionLink')
SCHEDULE_TYPES = ('sch:BooleanSchedule', 'sch:NumericSchedule', 'sch:EnumSchedule', 'sch:StringSchedule')
DEVICE_TYPES = ('bac:BacnetDevice', 'ma:ModbusAsyncDevice', 'mt:ModbusTcpDevice', 'mbus:MbusDevice',
                'nd:NiagaraStation', 'lonworks:LonDevice')


def _sv(n):
    if n is None:
        return None, None
    v = child(n, 'value')
    s = child(n, 'status')
    return (v.v if v is not None else None), (s.v if s is not None else None)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _resolve(bog, ordv):
    if not ordv:
        return ''
    if ordv.startswith('h:'):
        n = bog.handles.get(ordv[2:])
        return path(n) if n is not None else ordv
    if 'slot:' in ordv:
        from .bog import decode_name
        p = decode_name(ordv.split('slot:', 1)[1]).lstrip('/')
        return p
    return ordv


def _device_of(n):
    """The driver device a node sits under (or None)."""
    p = n.parent
    while p is not None:
        if p.t in DEVICE_TYPES:
            return p
        p = p.parent
    return None


def _is_proxy(n):
    p = n.parent
    while p is not None:
        if p.t.endswith('PointDeviceExt'):
            return True
        if p.t in DEVICE_TYPES or p.t == 'b:Station':
            return False
        p = p.parent
    return False


def _week(sched):
    comp = child(sched, 'schedule')
    week, special = {}, []
    if comp is None:
        return week, special

    def segs(day):
        out = []
        for t in walk(day):
            if t.t == 'sch:TimeSchedule':
                ev = child(t, 'effectiveValue')
                out.append({'start': val(t, 'start', '00:00:00.000')[:5], 'finish': (val(t, 'finish') or '00:00:00.000')[:5],
                            'value': _sv(ev)[0] if ev is not None else None})
        return out
    for c in comp.kids:
        if c.name == 'week':
            for day in c.kids:
                if day.t == 'sch:DailySchedule':
                    week[day.name] = segs(day)
        if c.name == 'specialEvents':
            for ev in comps(c):
                detail = {}
                for x in walk(ev):
                    if x.v and x.name in ('set', 'alwaysEffective') and x.parent is not None:
                        detail[f'{x.parent.name}.{x.name}'] = x.v
                special.append({'name': ev.name, 'segs': segs(child(ev, 'day')) if child(ev, 'day') else [], 'detail': detail})
    return week, special


def extract(bog):
    st = bog.root
    F = {'station': st and val(st, 'stationName') or '', 'saved': bog.saved}
    services = child(st, 'Services')
    drivers = child(st, 'Drivers')

    # ---------------- links (with the last value passed along each)
    links = []
    for n in walk(st):
        if n.t in LINK_TYPES:
            tgt = n.parent
            tslot = val(n, 'targetSlotName')
            tv = child(tgt, tslot)
            links.append({'src': _resolve(bog, val(n, 'sourceOrd')), 'sslot': val(n, 'sourceSlotName'),
                          'tgt': path(tgt), 'tslot': tslot, 'value': _sv(tv)[0] if tv is not None else None,
                          'tgt_type': tgt.t})
    F['links'] = links
    linked_in = defaultdict(set)
    for l in links:
        linked_in[l['tgt']].add(l['tslot'])

    # ---------------- local platform
    bn = next((n for n in walk(drivers) if n.t == 'bac:BacnetNetwork'), None)
    ld = child(bn, 'localDevice') if bn else None
    F['niagara_version'] = (val(ld, 'firmwareRevision') if ld else None) or ''
    F['bacnet_id'] = (val(ld, 'objectId') if ld else '') or ''

    # ---------------- peers
    peers = []
    for s in walk(drivers):
        if s.t == 'nd:NiagaraStation':
            cc = child(s, 'clientConnection')
            al = child(s, 'alarms')
            peers.append({'name': s.name, 'address': (val(s, 'address') or '').replace('ip:', ''), 'enabled': val(s, 'enabled', 'true') == 'true',
                          'version': val(s, 'version'), 'host': val(s, 'hostModel'),
                          'last_connect': val(cc, 'lastConnectTime'), 'last_disconnect': val(cc, 'lastDisconnectTime'),
                          'disconnect_cause': val(cc, 'lastDisconnectCause'), 'foxs': val(cc, 'useFoxs') == 'true',
                          'alarm_last_sent': val(al, 'lastSendTime'), 'alarm_send_fail': val(al, 'lastSendFailureTime'),
                          'alarm_last_received': val(al, 'lastReceivedTime')})
    F['peers'] = peers

    # ---------------- devices and points
    devices = []
    points = []
    for d in walk(drivers):
        if d.t not in DEVICE_TYPES or d.t == 'nd:NiagaraStation':
            continue
        cfg = child(child(d, 'config'), 'deviceObject')
        net = d.parent
        while net is not None and not net.t.endswith('Network'):
            net = net.parent
        devices.append({'path': path(d), 'name': d.name, 'type': d.t, 'folder': d.parent.name if d.parent.t.endswith('DeviceFolder') else '',
                        'network': net.name if net is not None else '', 'enabled': val(d, 'enabled', 'true') == 'true',
                        'vendor': val(cfg, 'vendorName') or val(d, 'manufacturer') or '', 'model': val(cfg, 'modelName') or val(d, 'modelName') or '',
                        'firmware': (val(cfg, 'firmwareRevision') or val(d, 'versionNumber') or '').strip(),
                        'software': val(cfg, 'applicationSoftwareVersion') or '', 'object_name': val(cfg, 'objectName') or '',
                        'object_id': val(cfg, 'objectId') or '', 'address': val(d, 'deviceAddress') or val(d, 'primaryAddress') or '',
                        'secondary': val(d, 'secondaryAddress') or '', 'serial': val(d, 'fabricationNumber') or '', 'points': []})
    dev_by_path = {x['path']: x for x in devices}

    for p in walk(st):
        if p.t not in POINT_TYPES:
            continue
        pp = path(p)
        dev = _device_of(p)
        px = child(p, 'proxyExt')
        levels = {}
        for k in p.kids:
            if k.name and re.fullmatch(r'in\d+', k.name) and child(k, 'value') is not None:
                v, s = _sv(k)
                if status_bits(s) & NULL_BIT or k.name in linked_in.get(pp, ()):
                    continue
                levels[k.name] = v
        fb = child(p, 'fallback')
        rec = {'path': pp, 'name': p.name, 'type': p.t.split(':')[1], 'units': units(val(p, 'facets')),
               'proxy': _is_proxy(p), 'proxy_enabled': val(px, 'enabled', 'true') == 'true' if px is not None else True,
               'object': val(px, 'objectId') or '', 'device': path(dev) if dev is not None else '',
               'levels': levels, 'fallback': _sv(fb)[0] if fb is not None else None,
               'linked': sorted(linked_in.get(pp, ())), 'history': any(k.t.startswith('h:') and k.t.endswith('HistoryExt') for k in p.kids),
               'alarms': [k.t for k in p.kids if k.t.startswith('a:') and 'Alarm' in k.t]}
        points.append(rec)
        if dev is not None and path(dev) in dev_by_path:
            dev_by_path[path(dev)]['points'].append(pp)
    F['devices'] = devices
    F['points'] = points

    # ---------------- schedules
    scheds = []
    for s in walk(st):
        if s.t in SCHEDULE_TYPES:
            week, special = _week(s)
            ext = child(s, 'ext')
            scheds.append({'path': path(s), 'name': s.name, 'type': s.t.split(':')[1],
                           'imported': bool(ext is not None and 'Import' in ext.t),
                           'week': week, 'special': special,
                           'in_linked': 'in' in linked_in.get(path(s), ())})
    F['schedules'] = scheds

    # ---------------- histories
    hc, caps = Counter(), 0
    for h in walk(st):
        if h.t.startswith('h:') and h.t.endswith('HistoryExt'):
            hc[h.t.split(':')[1]] += 1
            if child(child(h, 'historyConfig'), 'capacity') is not None:
                caps += 1
    exports = sum(1 for n in walk(drivers) if 'HistoryExport' in n.t)
    F['histories'] = {'by_type': dict(hc), 'total': sum(hc.values()), 'capacity_set': caps, 'exports': exports}

    # ---------------- alarms
    asvc = child(services, 'AlarmService')
    recips = []
    for c in comps(asvc):
        if c.t == 'a:StationRecipient':
            recips.append({'name': c.name, 'remote': val(c, 'remoteStation'),
                           'fed_by': [_resolve(bog, val(l, 'sourceOrd')) for l in c.kids if l.t in LINK_TYPES]})
    F['alarm_recipients'] = recips
    exts = []
    for a in walk(st):
        if a.t.startswith('a:') and a.t.endswith('AlarmExt') or a.t == 'a:AlarmSourceExt':
            off = child(a, 'offnormalAlgorithm')
            exts.append({'point': path(a.parent), 'type': a.t, 'class': val(a, 'alarmClass') or 'defaultAlarmClass',
                         'algorithm': off.t if off is not None else '', 'delay_ms': val(a, 'timeDelay')})
    F['alarm_exts'] = [e for e in exts if not e['point'].startswith('Services/')]

    # ---------------- users / services / backups
    users = []
    for u in comps(child(services, 'UserService')):
        if u.t != 'b:User':
            continue
        pw = {k.name: k.v for k in walk(child(u, 'authenticator')) if k.v}
        users.append({'name': u.name, 'enabled': val(u, 'enabled', 'true') == 'true', 'expiration': val(u, 'expiration'),
                      'roles': val(u, 'roles') or '', 'last_password_change': pw.get('lastPasswordChange'),
                      'force_reset': pw.get('forceResetAtNextLogin') == 'true'})
    F['users'] = users
    fox = child(services, 'FoxService')
    web = child(services, 'WebService')
    legacy = val(fox, 'supportLegacyClients') or ''
    F['security'] = {'fox_enabled': val(fox, 'foxEnabled', 'true') == 'true', 'foxs_enabled': val(fox, 'foxsEnabled', 'false') == 'true',
                     'legacy_clients': 'default' if (not legacy or legacy.startswith('0@')) else legacy.split('@')[0],
                     'http_enabled': val(web, 'httpEnabled', 'true') == 'true', 'https_enabled': val(web, 'httpsEnabled', 'false') == 'true'}
    backups = []
    for b in child(services, 'BackupService').kids if child(services, 'BackupService') else []:
        if b.t == 'bk:BackupRecord':
            backups.append({'time': val(b, 'timestamp'), 'user': val(b, 'user'), 'host': val(b, 'host')})
    F['backups'] = sorted(backups, key=lambda x: x['time'] or '')

    # ---------------- wiresheet notes
    F['notes'] = [{'path': path(t), 'text': val(t, 'text') or ''} for t in walk(st) if t.t == 'b:WsTextBlock']
    return F
