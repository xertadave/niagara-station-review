"""Reviews, decisions and rules, kept as JSON files in the data folder (never in git).

  data/settings.json                 report author, title, template choice
  data/rules.json                    standing rules learnt from 'Disregard' decisions
  data/reviews/<id>/meta.json        site, station, dates, summary note, state
  data/reviews/<id>/items.json       findings and status items with the reviewer's decisions
  data/reviews/<id>/station.bog      the uploaded backup
  data/reviews/<id>/report.docx      the last report built
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

LOCK = threading.RLock()
DATA = None

DEFAULT_SETTINGS = {'author': '', 'role': '', 'report_title': 'Remote PPM Report', 'company_team': 'Smart Buildings',
                    'use_template': True}


def set_data(path):
    global DATA
    DATA = path
    os.makedirs(os.path.join(DATA, 'reviews'), exist_ok=True)


def p(*a):
    return os.path.join(DATA, *a)


def load(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return json.loads(json.dumps(default))


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def settings():
    return {**DEFAULT_SETTINGS, **load(p('settings.json'), {})}


def save_settings(new):
    s = settings()
    for k in DEFAULT_SETTINGS:
        if k in new:
            s[k] = new[k]
    save(p('settings.json'), s)
    return s


def norm_site(s):
    return re.sub(r'\s+', ' ', (s or '').strip()).lower()


# ------------------------------------------------------------------ rules
def rules():
    return load(p('rules.json'), [])


def save_rules(r):
    save(p('rules.json'), r)


def rule_applies(rule, item, site):
    if not rule.get('active', True):
        return False
    if rule.get('scope') == 'site' and norm_site(rule.get('site')) != norm_site(site):
        return False
    for pat in rule.get('applies', []):
        pat = pat.strip().lower()
        if not pat:
            continue
        for key in (item['code'].lower(), item['match'].lower()):
            if pat == key or (pat.endswith('*') and key.startswith(pat[:-1])):
                return True
    return False


# ------------------------------------------------------------------ reviews
def new_id():
    return time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]


def check_id(rid):
    if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9a-f]{6}', rid or '') or not os.path.isdir(p('reviews', rid)):
        raise ValueError('review not found')
    return rid


def list_reviews():
    out = []
    for rid in sorted(os.listdir(p('reviews')), reverse=True):
        m = load(p('reviews', rid, 'meta.json'), None)
        if m:
            items = load(p('reviews', rid, 'items.json'), [])
            m['counts'] = {k: sum(1 for i in items if i.get('decision') == k) for k in ('include', 'disregard', 'undecided')}
            m['has_report'] = os.path.exists(p('reviews', rid, 'report.docx'))
            out.append(m)
    return out


def sites():
    return sorted({m['site'] for m in list_reviews() if m.get('site')} | {r['site'] for r in rules() if r.get('site')}, key=str.lower)


def previous_decisions(site, rid):
    """Latest decision for each finding 'match' made at this site in earlier reviews.
    Ordered by creation time (meta 'ts'), not by id: two reviews made in the same second have ids whose
    order is random (v1.0.0 fix - decisions were sometimes not carried)."""
    prev = {}
    for m in sorted(list_reviews(), key=lambda x: (x.get('ts', 0), x['id'])):
        if m['id'] == rid or norm_site(m['site']) != norm_site(site):
            continue
        for it in load(p('reviews', m['id'], 'items.json'), []):
            if it.get('decision') in ('include', 'disregard'):
                prev[it['match']] = {**it, '_station': m['station'], '_date': m['created'][:10]}
    return prev


def apply_history(items, site, rid):
    """Mark findings already decided at this site (rules or earlier reviews).
    Disregarded before -> 'precedent' (pre-set to disregard, shown under Already decided).
    Included before  -> tagged as carried, with the earlier wording, left undecided for the reviewer."""
    R = rules()
    prev = previous_decisions(site, rid)
    for it in items:
        hit = next((r for r in R if rule_applies(r, it, site)), None)
        if hit:
            it.update({'kind': 'precedent', 'was_kind': it['kind'], 'decision': 'disregard', 'rule_id': hit['id'],
                       'disregardReason': f"Rule: {hit['text']}" + (f" ({hit['reason']})" if hit.get('reason') else ''),
                       'listAsReviewed': bool(hit.get('list_as_reviewed')), 'reportReason': hit.get('reason') or ''})
            continue
        pr = prev.get(it['match'])
        if not pr:
            continue
        if pr['decision'] == 'disregard':
            reason = pr.get('disregardReason') or 'not required'
            if pr.get('kind') != 'precedent':        # keep the original wording when it was itself carried
                reason = f"Decided on {pr['_station']} ({pr['_date']}): {reason}"
            it.update({'kind': 'precedent', 'was_kind': it['kind'], 'decision': 'disregard', 'disregardReason': reason,
                       'reportReason': pr.get('reportReason') or pr.get('disregardReason') or '',
                       'listAsReviewed': bool(pr.get('listAsReviewed'))})
        else:
            if pr.get('kind') == 'precedent':        # brought back in on an earlier review
                it['decision'] = 'undecided'
            it['carried'] = pr.get('carried') or pr['_station']
            for k in ('priority', 'audience'):          # not 'result': it depends on this station's data
                if pr.get(k):
                    it[k] = pr[k]
            # Only wording the reviewer wrote is carried; generated wording is rebuilt from this station's data
            # so counts and names stay right.  (A carried wording is flagged so its details get checked.)
            if (pr.get('clientText') or '').strip() and (pr.get('clientText') or '').strip() != (pr.get('autoText') or '').strip():
                it['clientText'] = pr['clientText']
                it['wordingCarried'] = True
            if pr.get('status') in ('Client decision',):
                it['status'] = pr['status']
    return items


def create_review(site, station, saved, version, bog_bytes, items, bog_name, summary=None):
    with LOCK:
        rid = new_id()
        d = p('reviews', rid)
        os.makedirs(d)
        with open(os.path.join(d, 'station.bog'), 'wb') as fh:
            fh.write(bog_bytes)
        meta = {'id': rid, 'ts': time.time(), 'site': site.strip(), 'station': station, 'saved': saved, 'niagara': version,
                'created': datetime.now().isoformat(timespec='seconds'), 'bog_name': bog_name, 'summary_note': '', 'state': 'review',
                'summary': summary or {}}
        apply_history(items, site, rid)
        save(os.path.join(d, 'meta.json'), meta)
        save(os.path.join(d, 'items.json'), items)
        return rid


def get_review(rid):
    check_id(rid)
    return load(p('reviews', rid, 'meta.json'), {}), load(p('reviews', rid, 'items.json'), [])


EDITABLE = ('decision', 'priority', 'status', 'clientText', 'notes', 'disregardReason', 'ruleScope', 'ruleText',
            'ruleApplies', 'listAsReviewed', 'result', 'audience')


def update_item(rid, fid, patch):
    with LOCK:
        meta, items = get_review(rid)
        it = next((i for i in items if i['id'] == fid), None)
        if it is None:
            raise ValueError('finding not found')
        for k in EDITABLE:
            if k in patch:
                it[k] = patch[k]
        sync_rule(meta, it)
        save(p('reviews', rid, 'items.json'), items)
        return it


def sync_rule(meta, it):
    """A Disregard with 'This site' or 'All sites' becomes (or updates) a standing rule; anything
    else removes the rule this finding created."""
    R = rules()
    rid = f"r-{meta['id']}-{it['id']}"
    want = it.get('decision') == 'disregard' and it.get('ruleScope') in ('site', 'all') and it.get('kind') != 'precedent'
    existing = next((r for r in R if r['id'] == rid), None)
    if not want:
        if existing:
            R.remove(existing)
            save_rules(R)
        return
    rule = existing or {'id': rid, 'created': datetime.now().isoformat(timespec='seconds'), 'active': True}
    rule.update({'scope': it['ruleScope'], 'site': meta['site'] if it['ruleScope'] == 'site' else '',
                 'applies': [x.strip() for x in (it.get('ruleApplies') or it['match']).split(',') if x.strip()],
                 'text': it.get('ruleText') or f"Don't raise \"{it['title']}\"",
                 'reason': it.get('disregardReason', ''), 'list_as_reviewed': bool(it.get('listAsReviewed')),
                 'source': f"{meta['station']} {it['id']}"})
    if not existing:
        R.append(rule)
    save_rules(R)


def update_meta(rid, patch):
    with LOCK:
        meta, _ = get_review(rid)
        for k in ('summary_note', 'site', 'state', 'readings_note'):
            if k in patch:
                meta[k] = patch[k]
        save(p('reviews', rid, 'meta.json'), meta)
        return meta


def delete_review(rid):
    import shutil
    check_id(rid)
    shutil.rmtree(p('reviews', rid))
