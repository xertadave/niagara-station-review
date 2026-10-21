"""Turn station facts into findings (actions) and status items.

Every finding has:
  code     - the kind of check (e.g. OVR, FAULT).  Rules switch whole codes off.
  match    - code plus subject (e.g. OVR:Balancing).  Earlier decisions at the same site are
             matched on this, so a decision made on one station carries to the next one.
  kind     - 'action' or 'status'
and the text fields shown on the review page and used in the report.
Nothing here may name a site: all wording is built from the station's own data.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime

TEMP_UNITS = ('°C', '°F', 'celsius', 'fahrenheit', 'K', 'Δ°C')
FAULT_UNITS = ('°C', '°F', '%RH', 'ppm')


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def _ver(v):
    try:
        return tuple(int(x) for x in re.findall(r'\d+', v or '')[:4])
    except ValueError:
        return ()


def _fmt(v):
    f = _num(v)
    if f is None:
        return str(v)
    return f'{f:.1f}'.rstrip('0').rstrip('.') if abs(f - round(f)) > 1e-6 else str(int(round(f)))


def _short(p):
    return p.replace('Drivers/', '').replace('/points/', '/')


def finding(code, subject, kind='action', **kw):
    f = {'code': code, 'match': f'{code}:{subject}' if subject else code, 'kind': kind,
         'priority': kw.pop('priority', 'Low' if kind == 'action' else ''), 'area': kw.pop('area', ''),
         'audience': kw.pop('audience', 'client'), 'where': kw.pop('where', ''), 'title': kw.pop('title'),
         'observed': kw.pop('observed', ''), 'evidence': kw.pop('evidence', []), 'impact': kw.pop('impact', ''),
         'steps': kw.pop('steps', []), 'clientText': kw.pop('client', ''), 'decision': 'undecided',
         'status': 'Open' if kind == 'action' else '', 'notes': ''}
    f.update(kw)
    f['autoText'] = f['clientText']          # the generated wording, so an edited wording can be recognised later
    return f


# ------------------------------------------------------------------ derived values
def measured_values(F):
    """Last values seen on links, for points fed (directly or via other points) from field inputs.
    Returns {point path: (value, units, root input path)}."""
    P = {p['path']: p for p in F['points']}
    out_val = {}
    for l in F['links']:
        if l['src'] in P and l['sslot'] == 'out':
            v = _num(l['value'])
            if v is not None:
                out_val.setdefault(l['src'], v)
    feeds = defaultdict(list)   # target -> sources
    for l in F['links']:
        if l['src'] in P and l['tgt'] in P and l['sslot'] == 'out':
            feeds[l['tgt']].append(l['src'])
    root = {}
    for p in F['points']:
        if p['proxy'] and p['type'] in ('NumericPoint', 'BooleanPoint'):
            if p['path'].startswith('Drivers/NiagaraNetwork') and re.search(r'sp$|setpoint|set ?point', p['name'], re.I):
                continue      # setpoints shared from other stations are not readings
            root[p['path']] = p['path']
    for _ in range(6):
        for t, srcs in feeds.items():
            if t not in root:
                for s in srcs:
                    if s in root:
                        root[t] = root[s]
                        break
    res = {}
    for pth, r in root.items():
        if pth in out_val:
            p = P[pth]
            u = p['units'] or P[r]['units']
            res[pth] = (out_val[pth], u, r)
    return res


def readings(F):
    mv = measured_values(F)
    seen, rows = set(), []
    for pth, (v, u, r) in mv.items():
        if u not in ('°C', '%RH', 'ppm', '%'):
            continue
        name = pth.split('/')[-1]
        if u == '%' and not re.search(r'hum|rh', name, re.I):
            continue
        if r in seen:          # one reading per field input, however many points it passes through
            continue
        seen.add(r)
        rows.append({'point': name, 'path': pth, 'value': v, 'units': u, 'fault': is_fault(v, u)})
    rows.sort(key=lambda x: (x['units'] != '°C', x['point'].lower()))
    return rows


def is_fault(v, u):
    """Only sensor readings are judged (temperature, humidity, CO2); counters such as kWh never are."""
    if v is None or u not in FAULT_UNITS:
        return False
    if u in ('°C', '°F'):
        return v <= -60 or v >= 150
    if u == '%RH':
        return v < -5 or v > 105
    return v < 0 or v > 10000


# ------------------------------------------------------------------ checks
def check_overrides(F):
    out = []
    for p in F['points']:
        if not p['levels']:
            continue
        if not p['proxy'] and 'in1' not in p['levels']:
            continue      # a wiresheet setting held at a level, reported as status
        lv = ', '.join(f"{k} (priority {k[2:]}) = {v}" for k, v in sorted(p['levels'].items(), key=lambda x: int(x[0][2:])))
        top = min(int(k[2:]) for k in p['levels'])
        dev = p['device'].split('/')[-1] if p['device'] else ''
        what = f"{dev} {p['name']}".strip()
        emergency = top == 1
        out.append(finding('OVR', p['name'], priority='High' if emergency else 'Medium', area='Overrides', where='Station points',
            title=f"{what} is held by a manual override",
            observed=f"The point {_short(p['path'])} has a manual {'emergency ' if emergency else ''}override set ({lv}). "
                     f"{'This beats its normal control link, so the point ignores the control logic.' if p['linked'] else 'It stays at this value until the override is released.'}",
            evidence=[_short(p['path']) + ': ' + lv] + ([f"Normal control link into slot(s): {', '.join(p['linked'])}"] if p['linked'] else []),
            impact='The equipment is not under automatic control, which can waste energy or affect comfort.',
            steps=['Check with the site team whether the override is still needed.',
                   f"If not, release it ({'Emergency Auto' if emergency else 'Auto'}) so the point returns to normal control.",
                   'Confirm the equipment returns to normal operation.'],
            client=f"{what} was found held by a manual override. The override will be released so it returns to normal control."))
    return out


def check_sensor_faults(F):
    out = []
    mv = measured_values(F)
    done = set()
    for pth, (v, u, r) in mv.items():
        if not is_fault(v, u) or r in done:
            continue
        done.add(r)
        name = pth.split('/')[-1]
        users = sorted({l['tgt'].split('/')[-2] for l in F['links'] if l['src'] == pth})
        out.append(finding('FAULT', name, priority='Medium', area='Sensors', where='Site / I/O module',
            title=f"{name} reads a fault value",
            observed=f"{_short(pth)} reads {_fmt(v)} {u}, which is outside any real range and is the typical value for an open-circuit or "
                     f"shorted sensor. Logic that uses it cannot work properly.",
            evidence=[f"Input: {_short(r)}", f"{_short(pth)} = {_fmt(v)} {u}"] + ([f"Used by: {', '.join(users)}"] if users else []),
            impact='Control that depends on this sensor will not operate correctly and nothing alerts anyone to the fault.',
            steps=['Check the sensor and its wiring on site.', 'Check the input type setting on the I/O module matches the sensor fitted.',
                   'Once it reads correctly, test the control that uses it.'],
            client=f"The {name} sensor is reading a fault value, so the control that uses it cannot operate. The sensor and its wiring will be checked and repaired."))
    return out


def check_units(F):
    out = []
    P = {p['path']: p for p in F['points']}
    feeds = defaultdict(list)
    for l in F['links']:
        if l['src'] in P and l['tgt'] in P:
            feeds[l['src']].append(l['tgt'])
    for p in F['points']:
        n, u = p['name'], p['units']
        problem = None
        if re.search(r'hum', n, re.I) and u == 'ppm':
            co2 = [t for t in feeds.get(p['path'], []) if re.search(r'co2', t, re.I)]
            problem = ('labelled as humidity but measured in ppm (a CO2 reading)' + (f"; it feeds {', '.join(_short(c) for c in co2)}" if co2 else ''),
                       'CO2 sensor is labelled as humidity', f"The {n} point is a CO2 reading labelled as humidity on the BMS. The label will be corrected.")
        elif re.search(r'temp', n, re.I) and u and u not in TEMP_UNITS and p['type'].startswith('Numeric'):
            problem = (f'a temperature input set to {u} units', f'{n} shows {u} units',
                       f"The {n} input is labelled with the wrong units. The label will be corrected.")
        if problem:
            out.append(finding('UNITS', n, priority='Low', area='Points', where='Station points', title=problem[1],
                observed=f"{_short(p['path'])} is {problem[0]}.", evidence=[f"{_short(p['path'])}: units {u}"],
                impact='Operators and reports see the wrong type of reading.', steps=['Correct the point name or its units (facets) and any graphic label.'],
                client=problem[2]))
    return out


def device_groups(F):
    """Groups of similar devices (same folder or same model on one network), 4 or more."""
    g = defaultdict(list)
    for d in F['devices']:
        key = (d['network'], d['folder'] or d['model'])
        if key[1]:
            g[key].append(d)
    return {k: v for k, v in g.items() if len(v) >= 4}


def _pattern(name):
    return re.sub(r'[0-9]+', '#', re.sub(r'(?<=-)[0-9A-Z]{1,2}$', 'X', name))


def check_groups(F):
    out = []
    P = {p['path']: p for p in F['points']}
    for (net, grp), devs in device_groups(F).items():
        label = grp
        # naming convention
        pats = Counter(_pattern(d['name']) for d in devs)
        main_pat, n_main = pats.most_common(1)[0]
        odd = [d for d in devs if _pattern(d['name']) != main_pat]
        if odd and n_main >= len(devs) * 0.6:
            names = ', '.join(d['name'] for d in odd)
            n = len(odd)
            word = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'}.get(n, str(n))
            out.append(finding('NAMING', label, priority='Low', area='Points', where='Station devices', status='Client decision',
                title=f"{n} {label} device{'s' if n > 1 else ''} do{'es' if n == 1 else ''} not follow the naming convention",
                observed=f"Most {label} devices are named like {next(d['name'] for d in devs if _pattern(d['name']) == main_pat)}; {names} use a different pattern.",
                evidence=[f"{d['name']} (instance {d['object_id'].split(':')[-1] or '?'}, {d['software'] or d['firmware']})" for d in odd],
                impact='Units are harder to find on drawings, graphics and in reports.',
                steps=['Client to decide whether to rename to the common convention.'],
                client=f"{word} {'units use' if n > 1 else 'unit uses'} a different naming convention to the rest. Client to decide on action to re-name."))
        # points missing on some devices
        names_per = {d['name']: Counter(P[x]['name'] for x in d['points'] if x in P) for d in devs}
        allnames = Counter()
        for c in names_per.values():
            allnames.update(set(c))
        for pn, cnt in allnames.items():
            if len(devs) - cnt and cnt >= len(devs) * 0.75:
                miss = [d for d, c in names_per.items() if pn not in c]
                out.append(finding('MISSING', pn, priority='Low', area='Points', where='Station devices',
                    title=f"{pn} point missing on {len(miss)} {label} device{'s' if len(miss) > 1 else ''}",
                    observed=f"{cnt} of {len(devs)} {label} devices have a {pn} point; {', '.join(miss)} do not.",
                    evidence=[f"Missing on: {', '.join(miss)}"], impact='The value cannot be seen or used for these devices.',
                    steps=['Check whether the point exists in these controllers and add it if needed.'],
                    client=f"The {pn} point is missing for {', '.join(miss)} on the BMS; to be reviewed."))
        # disabled points
        dis = defaultdict(list)
        for d in devs:
            for x in d['points']:
                if x in P and not P[x]['proxy_enabled']:
                    dis[P[x]['name']].append(d['name'])
        for pn, ds in dis.items():
            out.append(finding('DISABLED', pn, priority='Low', area='Points', where='Station devices',
                title=f"{pn} point disabled on {', '.join(ds)}",
                observed=f"The {pn} point is disabled (proxy disabled) on {', '.join(ds)}.",
                evidence=[f"{d}/{pn}: proxy enabled = false" for d in ds], impact='The value cannot be seen or commanded from the BMS.',
                steps=['Find out why it was disabled and re-enable it, or record the reason.'],
                client=f"The {pn} point is disabled on the BMS for {', '.join(ds)}; to be investigated."))
        # inconsistent fallback values
        fb = defaultdict(Counter)
        for d in devs:
            for x in d['points']:
                if x in P and P[x]['fallback'] is not None and P[x]['type'] == 'NumericWritable':
                    fb[P[x]['name']][_fmt(P[x]['fallback'])] += 1
        for pn, c in fb.items():
            if len(c) > 1 and sum(c.values()) >= 4:
                spread = ', '.join(f"{n} × {v}" for v, n in c.most_common())
                common = c.most_common(1)[0][0]
                out.append(finding('FALLBACK', pn, priority='Low', area='Points', audience='internal', where='Station devices',
                    title=f"{label} {pn} fallback values are inconsistent",
                    observed=f"The {pn} fallback values on the {label} devices vary: {spread}. Fallbacks are used if the normal control link fails.",
                    evidence=[f"{pn} fallbacks: {spread}"], impact='If the control link failed, units would control to different values.',
                    steps=[f"Set all {pn} fallbacks to one value (most common: {common})."],
                    client=f"{label} default {pn.lower()} values vary between units; these will be standardised."))
    return out


def check_schedules(F):
    out = []
    for s in F['schedules']:
        if s['type'] != 'BooleanSchedule' or s['in_linked']:
            continue
        has_on = any(seg['value'] in (None, 'true') for d in s['week'].values() for seg in d)
        ev_on = any(seg['value'] == 'true' for e in s['special'] for seg in e['segs'])
        if not has_on and not ev_on:
            out.append(finding('SCHED-EMPTY', s['name'], priority='Medium', area='Schedules', where='Schedules' + (' (imported)' if s['imported'] else ''),
                title=f"{s['name']} schedule never switches on",
                observed=f"The {s['name']} schedule has no weekly on-periods" + (' and its special events are all OFF' if s['special'] else '') +
                         ('. It is imported from the supervisor, so check there whether it is driven another way (for example a master schedule into its In slot).' if s['imported'] else '.'),
                evidence=[_short(s['path']) + ': no weekly times'] + [f"Special event {e['name']}: OFF" for e in s['special']],
                impact='Whatever this schedule enables does not run.',
                steps=['Check the schedule on the supervisor and correct it if it should run.'],
                client=f"The {s['name']} schedule is not set to operate; to be checked and corrected."))
    return out


def check_alarms(F):
    out = []
    analog = [e for e in F['alarm_exts'] if 'OutOfRange' in e['algorithm'] or 'OutOfRange' in e['type']]
    if not analog:
        out.append(finding('ALARM-ANALOG', '', priority='Medium', area='Alarms', where='Station alarms',
            title='No high or low limit alarms are configured',
            observed=f"All {len(F['alarm_exts'])} alarm extensions are on/off (change-of-state or fault) alarms. No temperature or other analogue value alarms on going out of range.",
            evidence=[f"{e['point'].split('/')[-1]} ({e['class']})" for e in F['alarm_exts'][:15]],
            impact='A failed sensor or loss of heating or cooling is only noticed through complaints.',
            steps=['Consider high/low alarms on supply air, frost and key space temperatures, held off when plant is off.'],
            client='Alarm coverage is limited to on/off conditions. High/low limit alarms are recommended for key temperatures.'))
    peers = {p['name']: p for p in F['peers']}
    for r in F['alarm_recipients']:
        p = peers.get(r['remote'])
        if p is None or not p['enabled']:
            out.append(finding('ALARM-ROUTE', '', priority='Medium', area='Alarms', where='Alarm service',
                title='An alarm route points at a disabled or missing station',
                observed=f"Alarm recipient {r['name']} sends to station '{r['remote']}', which is {'disabled' if p else 'not in the Niagara network'}.",
                evidence=[f"{r['name']} → {r['remote']}"] + [f"Other recipients: {x['name']} → {x['remote']}" for x in F['alarm_recipients'] if x is not r],
                impact='Alarms routed only this way are not delivered.',
                steps=['Route the alarm classes to the active supervisor recipient.', 'Raise a test alarm and confirm it arrives.'],
                client='One alarm route points to an inactive station; routing to be checked.'))
    return out


def check_users(F, today):
    issues = []
    for u in F['users']:
        if not u['enabled']:
            continue
        exp = _date(u['expiration'])
        if exp and exp < today:
            issues.append(f"{u['name']}: expired {exp:%d %b %Y} but still present")
        if u['force_reset']:
            issues.append(f"{u['name']}: password reset at next login still pending (account not used)")
        lpc = _date(u['last_password_change'])
        if lpc and (today - lpc).days > 730 and 'admin' in u['roles']:
            issues.append(f"{u['name']}: admin, password last changed {lpc:%d %b %Y}")
        if u['name'] == 'admin':
            issues.append('admin: default account still enabled')
    shared = [u['name'] for u in F['users'] if u['enabled'] and 'admin' in u['roles'] and '.' not in u['name'] and u['name'] != 'admin']
    if shared:
        issues.append(f"Shared (non-personal) accounts with the admin role: {', '.join(shared)}")
    if not issues:
        return []
    return [finding('USERS', '', priority='Medium', area='Security', audience='internal', where='User service',
        title='User accounts need a review',
        observed=f"There are {len(F['users'])} accounts on the station; several should be removed or have their rights reduced.",
        evidence=issues, impact='Unused and shared admin accounts make unauthorised access more likely.',
        steps=['Remove expired and unused accounts.', 'Give shared accounts only the rights they need.', 'Check the password policy.'],
        client='A review of controller user accounts is recommended; several accounts are flagged for removal or reduced rights.')]


def check_security(F):
    s = F['security']
    ev = []
    if s['fox_enabled']:
        ev.append('Plain Fox (unencrypted) is enabled')
    if s['legacy_clients'] == 'default':
        ev.append('Support legacy clients is at "Default: Yes"')
    if s['http_enabled']:
        ev.append('HTTP (unencrypted) is enabled')
    for p in F['peers']:
        if p['enabled'] and not p['foxs']:
            ev.append(f"Link to {p['name']} uses plain Fox")
    if not ev:
        return []
    return [finding('SEC', '', priority='Medium', area='Security', audience='internal', where='Station services',
        title='Unencrypted connections appear to be enabled', observed='Some connections can be made without encryption.',
        evidence=ev, impact='Unencrypted connections expose credentials and data on the network.',
        steps=['Move station links to Foxs.', 'Disable plain Fox, legacy clients and HTTP once all users are on secure connections.'],
        client='Unencrypted controller connections should be disabled once all links use secure connections.')]


def check_version(F):
    mine = _ver(F['niagara_version'])
    newer = [p for p in F['peers'] if p['version'] and _ver(p['version']) > mine]
    if not mine or not newer:
        return []
    top = max(newer, key=lambda p: _ver(p['version']))
    return [finding('VERSION', '', priority='Low', area='Software', where='Platform',
        title='Station software is behind another station',
        observed=f"This station runs Niagara {F['niagara_version']}; {top['name']} runs {top['version']}.",
        evidence=[f"{p['name']}: {p['version']}" for p in F['peers'] if p['version']],
        impact='Missing fixes and a version mismatch between stations.', steps=['Plan an update in a maintenance window.'],
        client='Controller software is behind the supervisor; an update is recommended at a planned visit.')]


def check_backups(F, today):
    if not F['backups']:
        return []
    last = _date(F['backups'][-1]['time'])
    if not last or (today - last).days < 183:
        return []
    return [finding('BACKUP', '', priority='Medium', area='Resilience', where='Platform',
        title=f"Last recorded station backup is {(today - last).days // 30} months old",
        observed=f"The station holds {len(F['backups'])} backup records; the latest is {last:%d %b %Y}.",
        evidence=[f"{b['time'][:10]} by {b['user']} from {b['host']}" for b in F['backups'][-3:]],
        impact='Rebuilding from an old backup would lose later changes.', steps=['Take a full backup and agree a backup interval.'],
        client='The most recent controller backup on record is old. A new backup will be taken.')]


def check_histories(F):
    h = F['histories']
    if not h['total'] or h['capacity_set'] or h['exports']:
        return []
    return [finding('HISTORY', '', priority='Low', area='Trending', audience='internal', where='Histories',
        title='Check that trend data is kept beyond the station',
        observed=f"There are {h['total']} trend logs at the default capacity and no history export, so long-term storage depends on the supervisor importing them.",
        evidence=[f"{k}: {v}" for k, v in h['by_type'].items()], impact='Only a short period of data may be held.',
        steps=['Confirm the supervisor imports these histories.'],
        client='Trend logging is in place; long-term data retention on the supervisor to be confirmed.')]


def check_mbus(F):
    sec = defaultdict(list)
    for d in F['devices']:
        if d['secondary']:
            sec[d['secondary']].append(d['name'])
    dup = {k: v for k, v in sec.items() if len(v) > 1}
    if not dup:
        return []
    return [finding('MBUS-DUP', '', priority='Low', area='Metering', audience='internal', where='M-Bus',
        title='Duplicate M-Bus secondary addresses', observed='Some meters share a secondary address.',
        evidence=[f"{k}: {', '.join(v)}" for k, v in dup.items()], impact='Wrong meter data if secondary addressing is ever used.',
        steps=['Correct the secondary addresses from a scan or the meter labels.'],
        client='Heat meter addressing records contain duplicates; to be corrected.')]


def check_frost(F):
    out = []
    for p in F['points']:
        if re.fullmatch(r'frost.?sp', p['name'], re.I) and p['type'] == 'NumericWritable' and not p['linked']:
            v = _num(p['fallback'])
            if v is not None and v < 5:
                out.append(finding('FROST', p['name'], priority='Review', area='Control logic', audience='internal', where='Wiresheet',
                    title='Frost protection setpoint is low', observed=f"{_short(p['path'])} is {_fmt(v)} °C.",
                    evidence=[f"{_short(p['path'])} = {_fmt(v)} °C"], impact='Little margin before a frost trip.',
                    steps=['Check against the specification; 5 °C is common.'], client='Frost protection setpoints reviewed.'))
    return out


# ------------------------------------------------------------------ status
def status_items(F):
    S = []
    P = {p['path']: p for p in F['points']}
    manual = [p for p in F['points'] if p['levels'] and (p['proxy'] or 'in1' in p['levels'])]
    S.append(finding('ST-MANUAL', '', 'status', area='Overrides', title='Points in manual', count=len(manual),
        result='See actions' if manual else 'Satisfactory',
        observed=(f"{len(manual)} point(s) in manual: " + ', '.join(_short(p['path']) for p in manual)) if manual else 'No points are held in manual.',
        client=('Apart from the items in the actions, no plant or terminal unit points were found in manual override.' if manual else
                'No plant or terminal unit points were found in manual override.')))
    settings = [p for p in F['points'] if p['levels'] and not p['proxy'] and 'in1' not in p['levels']]
    if settings:
        S.append(finding('ST-SETTINGS', '', 'status', area='Settings', title='Settings held at a priority level',
            observed='Wiresheet settings set by hand: ' + '; '.join(f"{_short(p['path'])} = {list(p['levels'].values())[0]}" for p in settings),
            client='Some control settings are held at fixed values by design.'))
    r = readings(F)
    if r:
        S.append(finding('ST-READINGS', '', 'status', area='Readings', title=f"Readings in the backup ({F['saved']})",
            observed='; '.join(f"{x['point']} {'FAULT ' if x['fault'] else ''}{_fmt(x['value'])} {x['units']}" for x in r[:20]),
            client='Readings at the time of the review are listed below.', readings=r[:20]))
    for s in F['schedules']:
        if s['type'] != 'BooleanSchedule':
            continue
        days = []
        for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
            segs = [f"{x['start']}–{x['finish'] if x['finish'] != '00:00' else '24:00'}" for x in s['week'].get(d, []) if x['value'] in (None, 'true')]
            if segs:
                days.append(f"{d[:3].title()} {', '.join(segs)}")
        if not days:
            continue
        S.append(finding('ST-SCHEDULE', s['name'], 'status', area='Schedules', title=f"{s['name']} schedule",
            observed='; '.join(days) + (f". Special events: {', '.join(e['name'] for e in s['special'])}" if s['special'] else '. No holiday events.'),
            client=f"The {s['name']} schedule runs {'; '.join(days)}."))
    groups = device_groups(F)
    for (net, grp), devs in groups.items():
        S.append(finding('ST-GROUP', grp, 'status', area='Devices', title=f"{grp} devices",
            observed=f"{len(devs)} × {devs[0]['vendor']} {devs[0]['model']} on {net}; software {', '.join(sorted({d['software'] or d['firmware'] for d in devs}))}.",
            client=f"{len(devs)} {grp} devices are connected and controlled from this controller."))
    meters = [d for d in F['devices'] if d['type'] in ('ma:ModbusAsyncDevice', 'mt:ModbusTcpDevice', 'mbus:MbusDevice')]
    if meters:
        mb = [d['name'] for d in meters if d['type'] == 'mbus:MbusDevice']
        md = [d['name'] for d in meters if d['type'] != 'mbus:MbusDevice']
        S.append(finding('ST-METERING', '', 'status', area='Metering', title='Metering',
            observed=(f"Modbus: {', '.join(md)}. " if md else '') + (f"M-Bus: {', '.join(mb)}." if mb else ''),
            client=f"{len(md)} Modbus and {len(mb)} M-Bus meters are read by this controller."))
    h = F['histories']
    if h['total']:
        S.append(finding('ST-TRENDING', '', 'status', area='Trending', title='Trend logging',
            observed=f"{h['total']} trend logs: " + ', '.join(f"{v} {k}" for k, v in h['by_type'].items()) + '.',
            client='Trend logging is configured for plant, terminal unit and metering points.'))
    others = [d for d in F['devices'] if d['type'] == 'bac:BacnetDevice' and not any(d in v for v in groups.values())]
    if others:
        S.append(finding('ST-DEVICES', '', 'status', area='Devices', title='Field devices',
            observed='; '.join(f"{d['name']} ({d['vendor']} {d['model']} {d['firmware']})" for d in others),
            client='Field controllers are operational.'))
    if F['peers']:
        S.append(finding('ST-COMMS', '', 'status', area='Station', title='Station communications',
            observed='; '.join(f"{p['name']} ({p['address']}, {'enabled' if p['enabled'] else 'disabled'}, {p['version'] or '?'}; last connected {(p['last_connect'] or '?')[:16]})" for p in F['peers']),
            client='The controller is communicating with the supervisor and other controllers.'))
    return S


def run_checks(F, today=None):
    today = today or datetime.now()
    acts = (check_overrides(F) + check_sensor_faults(F) + check_units(F) + check_groups(F) + check_schedules(F) +
            check_alarms(F) + check_users(F, today) + check_security(F) + check_version(F) + check_backups(F, today) +
            check_histories(F) + check_mbus(F) + check_frost(F))
    order = {'High': 0, 'Medium': 1, 'Low': 2, 'Review': 3}
    acts.sort(key=lambda f: order.get(f['priority'], 9))
    items = acts + status_items(F)
    for i, f in enumerate(items, 1):
        f['id'] = f"{'a' if f['kind'] == 'action' else 's'}{i:02d}"
        f['order'] = i
    return items
