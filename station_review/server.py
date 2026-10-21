"""Station Review web server (standard library only).

  /                 upload a station backup (.bog), see earlier reviews, rules and settings
  /review?id=...    review the findings: Include / Disregard with reasons, then download the report
"""
import argparse
import json
import os
import re
import threading
import traceback
import webbrowser
from email import policy
from email.parser import BytesParser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import store, report
from .pipeline import analyse

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')
VERSION = '1.0.0'
MAX_UPLOAD = 60 * 1024 * 1024


def parse_multipart(headers, body):
    msg = BytesParser(policy=policy.HTTP).parsebytes(
        b'Content-Type: ' + headers.get('Content-Type', '').encode() + b'\r\n\r\n' + body)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        fn = part.get_filename()
        data = part.get_payload(decode=True) or b''
        if fn:
            files.append((name, os.path.basename(fn.replace('\\', '/')), data))
        else:
            fields[name] = data.decode('utf-8', errors='replace')
    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = 'StationReview/' + VERSION

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, default=str), 'application/json')

    def static(self, name, ctype):
        with open(os.path.join(WEB, name), 'rb') as fh:
            self.send(200, fh.read(), ctype)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_UPLOAD:
            raise ValueError('file too large')
        return self.rfile.read(n) if n else b''

    def jbody(self):
        b = self.body()
        return json.loads(b or b'{}')

    # ------------------------------------------------------------ GET
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == '/':
                return self.static('index.html', 'text/html; charset=utf-8')
            if u.path == '/review':
                return self.static('review.html', 'text/html; charset=utf-8')
            if u.path in ('/style.css', '/app.js'):
                return self.static(u.path[1:], 'text/css' if u.path.endswith('.css') else 'application/javascript')
            if u.path == '/logo.png':
                own = store.p('branding', 'logo.png')
                if os.path.exists(own):
                    with open(own, 'rb') as fh:
                        return self.send(200, fh.read(), 'image/png')
                return self.static('logo.png', 'image/png')
            if u.path == '/api/info':
                return self.json({'version': VERSION, 'settings': store.settings(), 'sites': store.sites(),
                                  'own_template': os.path.exists(store.p('branding', 'template.docx'))})
            if u.path == '/api/reviews':
                return self.json(store.list_reviews())
            if u.path == '/api/rules':
                return self.json(store.rules())
            m = re.fullmatch(r'/api/review/([\w-]+)', u.path)
            if m:
                meta, items = store.get_review(m.group(1))
                return self.json({'meta': meta, 'items': items, 'version': VERSION})
            m = re.fullmatch(r'/api/review/([\w-]+)/report\.docx', u.path)
            if m:
                rid = store.check_id(m.group(1))
                fp = store.p('reviews', rid, 'report.docx')
                if not os.path.exists(fp):
                    return self.json({'error': 'build the report first'}, 404)
                meta, _ = store.get_review(rid)
                name = re.sub(r'[^A-Za-z0-9._ -]+', '_', f"{meta['station']}_BMS_PPM_Report.docx")
                with open(fp, 'rb') as fh:
                    return self.send(200, fh.read(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                     {'Content-Disposition': f'attachment; filename="{name}"'})
            if u.path == '/api/rules/export':
                return self.send(200, json.dumps(store.rules(), indent=1, ensure_ascii=False), 'application/json',
                                 {'Content-Disposition': 'attachment; filename="station-review-rules.json"'})
            self.send(404, 'not found', 'text/plain')
        except ValueError as e:
            self.json({'error': str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self.json({'error': f'{type(e).__name__}: {e}'}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == '/api/upload':
                fields, files = parse_multipart(self.headers, self.body())
                site = (fields.get('site') or '').strip()
                if not site:
                    raise ValueError('enter the site name')
                bog = next((f for f in files if f[1].lower().endswith(('.bog', '.xml'))), None)
                if not bog:
                    raise ValueError('choose a station backup (.bog) file')
                F, items, summary = analyse(bog[2])
                rid = store.create_review(site, F['station'] or os.path.splitext(bog[1])[0], F['saved'], F['niagara_version'],
                                          bog[2], items, bog[1], summary)
                return self.json({'id': rid})
            m = re.fullmatch(r'/api/review/([\w-]+)/item/(\w+)', u.path)
            if m:
                return self.json(store.update_item(m.group(1), m.group(2), self.jbody()))
            m = re.fullmatch(r'/api/review/([\w-]+)/meta', u.path)
            if m:
                return self.json(store.update_meta(m.group(1), self.jbody()))
            m = re.fullmatch(r'/api/review/([\w-]+)/report', u.path)
            if m:
                rid = store.check_id(m.group(1))
                meta, items = store.get_review(rid)
                s = store.settings()
                report.build(meta, items, s, store.p('reviews', rid, 'report.docx'), report.template_path(store.DATA, s))
                store.update_meta(rid, {'state': 'issued'})
                return self.json({'ok': True, 'url': f'/api/review/{rid}/report.docx',
                                  'undecided': sum(1 for i in items if i.get('decision') == 'undecided')})
            m = re.fullmatch(r'/api/review/([\w-]+)/delete', u.path)
            if m:
                store.delete_review(m.group(1))
                return self.json({'ok': True})
            if u.path == '/api/settings':
                return self.json(store.save_settings(self.jbody()))
            if u.path == '/api/template':
                _, files = parse_multipart(self.headers, self.body())
                f = next((f for f in files if f[1].lower().endswith('.docx')), None)
                if not f:
                    raise ValueError('choose a Word .docx template')
                os.makedirs(store.p('branding'), exist_ok=True)
                with open(store.p('branding', 'template.docx'), 'wb') as fh:
                    fh.write(f[2])
                return self.json({'ok': True})
            if u.path == '/api/template/clear':
                fp = store.p('branding', 'template.docx')
                if os.path.exists(fp):
                    os.remove(fp)
                return self.json({'ok': True})
            if u.path == '/api/rules':
                b = self.jbody()
                return self.json(add_rule(b))
            if u.path == '/api/rules/import':       # before /api/rules/<id>, which would take 'import' as a rule id (v1.0.0 fix)
                b = self.jbody()
                return self.json(import_rules(b.get('rules', []), b.get('site', '')))
            m = re.fullmatch(r'/api/rules/([\w.-]+)', u.path)
            if m:
                return self.json(edit_rule(m.group(1), self.jbody()))
            self.send(404, 'not found', 'text/plain')
        except ValueError as e:
            self.json({'error': str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self.json({'error': f'{type(e).__name__}: {e}'}, 500)


# ------------------------------------------------------------------ rules editing
def _clean_rule(b, base=None):
    r = dict(base or {})
    for k in ('text', 'reason', 'scope', 'site'):
        if k in b:
            r[k] = str(b[k]).strip()
    if 'applies' in b:
        a = b['applies']
        r['applies'] = [x.strip() for x in (a.split(',') if isinstance(a, str) else a) if str(x).strip()]
    if 'active' in b:
        r['active'] = bool(b['active'])
    if 'list_as_reviewed' in b:
        r['list_as_reviewed'] = bool(b['list_as_reviewed'])
    if r.get('scope') not in ('site', 'all'):
        r['scope'] = 'all'
    if r['scope'] == 'all':
        r['site'] = ''
    if not r.get('applies'):
        raise ValueError('say which checks the rule applies to (e.g. SCHED-EMPTY or OVR:Balancing)')
    return r


def add_rule(b):
    from datetime import datetime
    import uuid
    with store.LOCK:
        R = store.rules()
        r = _clean_rule(b, {'id': 'r-' + uuid.uuid4().hex[:8], 'active': True, 'created': datetime.now().isoformat(timespec='seconds'),
                            'source': 'added directly'})
        R.append(r)
        store.save_rules(R)
        return r


def edit_rule(rid, b):
    with store.LOCK:
        R = store.rules()
        r = next((x for x in R if x['id'] == rid), None)
        if r is None:
            raise ValueError('rule not found')
        if b.get('delete'):
            R.remove(r)
            store.save_rules(R)
            return {'deleted': rid}
        R[R.index(r)] = _clean_rule(b, r)
        store.save_rules(R)
        return R[R.index(next(x for x in R if x['id'] == rid))]


def import_rules(rules, site):
    """Rules exported from another PC.  Site-scoped rules whose site is the placeholder {{SITE}} (or blank)
    are attached to the site chosen on import."""
    added = 0
    with store.LOCK:
        R = store.rules()
        have = {x['id'] for x in R}
        for r in rules:
            r = dict(r)
            if r.get('scope') == 'site' and (not r.get('site') or r.get('site') == '{{SITE}}'):
                if not site:
                    raise ValueError('choose the site these rules belong to')
                r['site'] = site
            r = _clean_rule(r, {'id': r.get('id') or f'r-imp{added}', 'active': True, 'source': 'imported'})
            if r['id'] in have:
                r['id'] += '-imp'
            R.append(r)
            added += 1
        store.save_rules(R)
    return {'added': added}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='station_review', description='Niagara station backup review and PPM report')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8780)
    ap.add_argument('--data', default=os.path.join(os.path.dirname(HERE), 'data'))
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args(argv)
    store.set_data(os.path.abspath(a.data))
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f'http://127.0.0.1:{a.port}/'
    print(f'Station Review {VERSION} running at {url}  (data: {store.DATA})')
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
