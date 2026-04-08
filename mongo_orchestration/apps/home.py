#!/usr/bin/python
# coding=utf-8
# Copyright 2026-Present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Server-side rendered web dashboard at GET /.

Data is gathered directly from the in-process singletons (no HTTP round-trip).
The browser only calls the REST API for mutations (add / remove / stop).
"""

import html as _html

from bottle import response, route


# ── HTML helpers ───────────────────────────────────────────────────────────

def _e(s):
    return _html.escape(str(s or ''))


def _badge(cls, text):
    return f'<span class="badge {cls}">{_e(text)}</span>'


def _version_span(v):
    return f'<span class="version">{_e(v)}</span>' if v else ''


_STATE_LABELS  = {1: 'PRIMARY', 2: 'SECONDARY', 7: 'ARBITER'}
_STATE_CLASSES = {1: 'role-primary', 2: 'role-secondary', 7: 'role-arbiter'}


def _role_badge(state):
    return (f'<span class="role {_STATE_CLASSES.get(state, "role-other")}">'
            f'{_STATE_LABELS.get(state, f"state {state}")}</span>')


def _btn(cls, action, data, label):
    attrs = ' '.join(f'data-{k}="{_e(v)}"' for k, v in data.items())
    return f'<button class="{cls}" data-action="{action}" {attrs}>{label}</button>'


# ── Card renderers ─────────────────────────────────────────────────────────

def _rs_members_html(rs_id, members, removable=False):
    rows = []
    for m in members:
        uri   = m.get('_uri', '')
        rmBtn = _btn('remove-btn', 'remove-member',
                     {'rs': rs_id, 'member': str(m['_id'])}, 'Remove') if removable else ''
        rows.append(
            '<div class="member">'
            + _role_badge(m['state'])
            + f'<span class="host">{_e(m.get("host", ""))}</span>'
            + (f'<span class="member-uri">{_e(uri)}</span>' if uri else '')
            + rmBtn
            + '</div>'
        )
    return ''.join(rows)


def _server_card(d):
    uri = d.get('mongodb_auth_uri') or d.get('mongodb_uri', '')
    ver = (d.get('serverInfo') or {}).get('version', '')
    return (
        '<div class="card"><div class="card-header">'
        + _badge('badge-single', 'Standalone')
        + f'<span class="id">{_e(d["id"])}</span>'
        + _version_span(ver)
        + f'<span class="uri">{_e(uri)}</span>'
        + _btn('stop-btn', 'stop', {'res': 'servers', 'id': d['id']}, 'Stop')
        + '</div></div>'
    )


def _rs_card(d):
    uri     = d.get('mongodb_auth_uri') or d.get('mongodb_uri', '')
    rs_id   = d['id']
    members = _rs_members_html(rs_id, d.get('members', []), removable=True)
    return (
        '<div class="card"><div class="card-header">'
        + _badge('badge-repl', 'Replica Set')
        + f'<span class="id">{_e(rs_id)}</span>'
        + _version_span(d.get('_version', ''))
        + f'<span class="uri">{_e(uri)}</span>'
        + _btn('add-btn',  'add-member', {'rs': rs_id},                   '+ Member')
        + _btn('stop-btn', 'stop',       {'res': 'replica_sets', 'id': rs_id}, 'Stop')
        + f'</div><div class="members">{members}</div></div>'
    )


def _shard_card(d):
    uri        = d.get('mongodb_auth_uri') or d.get('mongodb_uri', '')
    cluster_id = d['id']
    inner      = ''

    routers = d.get('routers', [])
    if routers:
        inner += '<div class="section-label">Mongos routers</div>'
        for r in routers:
            r_uri = r.get('_uri', '')
            inner += (
                '<div class="member">'
                + _badge('badge-mongos', 'mongos')
                + f'<span class="host">{_e(r.get("hostname") or r["id"])}</span>'
                + (f'<span class="member-uri">{_e(r_uri)}</span>' if r_uri else '')
                + _btn('remove-btn', 'remove-router',
                       {'cluster': cluster_id, 'router': r['id']}, 'Remove')
                + '</div>'
            )

    configsvrs = d.get('configsvrs', [])
    if configsvrs:
        inner += '<div class="section-label">Config servers</div>'
        for c in configsvrs:
            inner += (
                '<div class="member">'
                + _badge('badge-configsvr', 'configsvr')
                + f'<span class="member-uri">{_e(c.get("mongodb_uri") or c["id"])}</span>'
                + '</div>'
            )

    shards = d.get('shards', [])
    if shards:
        inner += '<div class="section-label">Shards</div>'
        for sh in shards:
            shard_id = sh['id']
            inner += (
                '<div class="member" style="flex-wrap:wrap;gap:4px;">'
                + _badge('badge-repl', shard_id)
                + _btn('remove-btn', 'remove-shard',
                       {'cluster': cluster_id, 'shard': shard_id}, 'Remove')
                + '</div>'
            )
            rs_members = sh.get('_rsMembers', [])
            if rs_members:
                inner += (
                    '<div style="padding-left:24px;">'
                    + _rs_members_html(sh.get('_id', ''), rs_members, removable=False)
                    + '</div>'
                )

    return (
        '<div class="card"><div class="card-header">'
        + _badge('badge-shard', 'Sharded Cluster')
        + f'<span class="id">{_e(cluster_id)}</span>'
        + _version_span(d.get('_version', ''))
        + f'<span class="uri">{_e(uri)}</span>'
        + _btn('add-btn',  'add-router', {'cluster': cluster_id}, '+ Router')
        + _btn('add-btn',  'add-shard',  {'cluster': cluster_id}, '+ Shard')
        + _btn('stop-btn', 'stop', {'res': 'sharded_clusters', 'id': cluster_id}, 'Stop')
        + f'</div><div class="members">{inner}</div></div>'
    )


# ── Data gathering (direct singleton access, no HTTP) ─────────────────────

def _server_version(server_id):
    """Return MongoDB version string for a server (uses --version, no MongoDB connection, cached)."""
    from mongo_orchestration.servers import Servers
    try:
        return '.'.join(str(x) for x in Servers().version(server_id))
    except Exception:
        return ''


def _server_uri(server_id):
    """Return mongodb:// URI for a server without connecting to it."""
    from mongo_orchestration.servers import Servers
    try:
        sv = Servers()._storage[server_id]
        if not sv.hostname:
            return ''
        uri = f'mongodb://{sv.hostname}'
        if sv.login:
            uri = sv.mongodb_auth_uri(sv.hostname)
        return uri
    except Exception:
        return ''


def _gather():
    from mongo_orchestration.replica_sets import ReplicaSets
    from mongo_orchestration.servers import Servers
    from mongo_orchestration.sharded_clusters import ShardedClusters

    used = set()
    rs_list, shard_list = [], []

    for rs_id in ReplicaSets():
        d = ReplicaSets().info(rs_id)
        primary = None
        for m in d.get('members', []):
            sid = m.get('server_id')
            if sid:
                used.add(sid)
            m['_uri'] = f"mongodb://{m['host']}" if m.get('host') else ''
            if m.get('state') == 1 or primary is None:
                primary = m
        if primary and primary.get('server_id'):
            d['_version'] = _server_version(primary['server_id'])
        rs_list.append(d)

    for cluster_id in ShardedClusters():
        d = ShardedClusters().info(cluster_id)
        routers = d.get('routers', [])
        for r in routers:
            used.add(r['id'])
            r['_uri'] = f"mongodb://{r['hostname']}" if r.get('hostname') else ''
        if routers:
            d['_version'] = _server_version(routers[0]['id'])
        for c in d.get('configsvrs', []):
            used.add(c['id'])
        for sh in d.get('shards', []):
            if sh.get('isReplicaSet') and sh.get('_id'):
                rs_info = ReplicaSets().info(sh['_id'])
                sh['_rsMembers'] = rs_info.get('members', [])
                for m in sh['_rsMembers']:
                    sid = m.get('server_id')
                    if sid:
                        used.add(sid)
                    m['_uri'] = f"mongodb://{m['host']}" if m.get('host') else ''
        shard_list.append(d)

    standalone = []
    for sid in Servers():
        if sid not in used:
            standalone.append({
                'id': sid,
                'mongodb_uri': _server_uri(sid),
                'serverInfo': {'version': _server_version(sid)},
            })

    releases = list(Servers().releases or {})
    return standalone, rs_list, shard_list, releases


# ── Page template ──────────────────────────────────────────────────────────

_CSS = """
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, sans-serif; max-width: 980px;
           margin: 40px auto; padding: 0 24px; color: #1a1a1a; background: #f5f5f5; }
    h1  { font-size: 1.5rem; margin-bottom: 4px; }
    h2  { font-size: 1rem; color: #555; margin: 28px 0 12px; font-weight: 600;
          text-transform: uppercase; letter-spacing: 0.05em; }
    .subtitle { font-size: 0.82rem; color: #999; margin-bottom: 28px; }
    code { font-family: ui-monospace, monospace; font-size: 0.85em;
           background: #ebebeb; padding: 1px 5px; border-radius: 3px; }
    .card { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
            margin-bottom: 12px; overflow: hidden; }
    .card-header { display: flex; align-items: center; gap: 10px;
                   padding: 12px 16px; border-bottom: 1px solid #f0f0f0; }
    .card-header .id  { font-family: ui-monospace, monospace; font-size: 0.85rem;
                        flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .card-header .uri { font-family: ui-monospace, monospace; font-size: 0.8rem;
                        color: #555; flex: 2; min-width: 0; word-break: break-all; }
    .members { padding: 0 16px 8px; }
    .section-label { font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                     letter-spacing: 0.06em; color: #aaa; margin: 10px 0 4px; }
    .member { display: flex; align-items: center; gap: 10px; padding: 4px 0;
              border-bottom: 1px solid #f5f5f5; font-size: 0.85rem; }
    .member:last-child { border-bottom: none; }
    .member .host       { font-family: ui-monospace, monospace; color: #333; }
    .member .member-uri { font-family: ui-monospace, monospace; font-size: 0.8rem; color: #777; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
             font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em; flex-shrink: 0; }
    .badge-single   { background: #dbeafe; color: #1d4ed8; }
    .badge-repl     { background: #dcfce7; color: #15803d; }
    .badge-shard    { background: #fef9c3; color: #a16207; }
    .badge-configsvr{ background: #f3e8ff; color: #7e22ce; }
    .badge-mongos   { background: #e0f2fe; color: #0369a1; }
    .version { font-size: 0.75rem; color: #888; background: #f3f4f6; padding: 2px 7px;
               border-radius: 20px; flex-shrink: 0; }
    .role { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 0.7rem;
            font-weight: 700; letter-spacing: 0.04em; flex-shrink: 0; min-width: 76px; text-align: center; }
    .role-primary   { background: #dcfce7; color: #15803d; }
    .role-secondary { background: #e0f2fe; color: #0369a1; }
    .role-arbiter   { background: #fef9c3; color: #a16207; }
    .role-other     { background: #f3f4f6; color: #6b7280; }
    .empty { color: #aaa; font-style: italic; font-size: 0.9rem; padding: 8px 0; }
    button { cursor: pointer; border-radius: 4px; font-size: 0.8rem; padding: 4px 10px;
             border: 1px solid transparent; }
    .stop-btn   { margin-left: auto; background: #fee2e2; color: #b91c1c; border-color: #fca5a5; }
    .stop-btn:hover   { background: #fecaca; }
    .add-btn    { background: #f0fdf4; color: #15803d; border-color: #86efac; }
    .add-btn:hover    { background: #dcfce7; }
    .remove-btn { margin-left: auto; background: #fef9c3; color: #92400e; border-color: #fde68a;
                  padding: 2px 7px; font-size: 0.75rem; }
    .remove-btn:hover { background: #fef3c7; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .form-card { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; }
    .form-row  { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; }
    .field     { display: flex; flex-direction: column; gap: 4px; }
    .field > span { font-size: 0.78rem; font-weight: 600; color: #666; }
    select, input[type=text] { padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 5px;
                               font-size: 0.88rem; background: #fff; }
    .checkboxes { display: flex; gap: 16px; align-items: center; padding-bottom: 2px; }
    .checkboxes label { display: flex; align-items: center; gap: 5px; font-size: 0.85rem; cursor: pointer; }
    button[type=submit] { background: #1d4ed8; color: #fff; border: none; padding: 8px 18px;
                          border-radius: 5px; font-size: 0.9rem; }
    button[type=submit]:hover { background: #1e40af; }
    #result { margin-top: 12px; padding: 10px 14px; border-radius: 6px;
              font-family: ui-monospace, monospace; font-size: 0.82rem;
              display: none; white-space: pre-wrap; }
    #result.success { background: #dcfce7; color: #15803d; border: 1px solid #86efac; }
    #result.error   { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .refresh-info { font-size: 0.75rem; color: #bbb; margin-left: 6px; font-weight: 400; }
"""

_JS = """
    // ── Mutations: all handled via fetch() + page reload ──────────────────

    document.getElementById('cluster-list').addEventListener('click', async e => {
      const btn = e.target.closest('button[data-action]');
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      const { action, res, id, rs, member, cluster, router, shard } = btn.dataset;

      const post = (path, body = {}) => fetch('/v1/' + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (action === 'stop') {
        if (!confirm('Stop ' + id + '?')) { btn.disabled = false; return; }
        await fetch('/v1/' + res + '/' + id, { method: 'DELETE' });
      } else if (action === 'add-member') {
        await post('replica_sets/' + rs + '/members', { procParams: {} });
      } else if (action === 'remove-member') {
        if (!confirm('Remove member ' + member + '?')) { btn.disabled = false; return; }
        await fetch('/v1/replica_sets/' + rs + '/members/' + member, { method: 'DELETE' });
      } else if (action === 'add-router') {
        await post('sharded_clusters/' + cluster + '/routers', {});
      } else if (action === 'remove-router') {
        if (!confirm('Remove router ' + router + '?')) { btn.disabled = false; return; }
        await fetch('/v1/sharded_clusters/' + cluster + '/routers/' + router, { method: 'DELETE' });
      } else if (action === 'add-shard') {
        await post('sharded_clusters/' + cluster + '/shards', { procParams: {} });
      } else if (action === 'remove-shard') {
        if (!confirm('Remove shard ' + shard + '?')) { btn.disabled = false; return; }
        await fetch('/v1/sharded_clusters/' + cluster + '/shards/' + shard, { method: 'DELETE' });
      }
      await refreshClusters();
      btn.disabled = false;
    });

    // ── New cluster form ───────────────────────────────────────────────────

    document.getElementById('cluster_type').addEventListener('change', function () {
      document.getElementById('single_member').disabled = this.value === 'single';
    });

    document.getElementById('launch-form').addEventListener('submit', async e => {
      e.preventDefault();
      const btn = document.getElementById('start-btn');
      btn.disabled = true; btn.textContent = 'Starting\\u2026';

      const fd = new FormData(e.target);
      const clusterType  = fd.get('cluster_type');
      const version      = fd.get('version');
      const auth         = fd.get('auth') === 'on';
      const singleMember = fd.get('single_member') === 'on';

      const base = {};
      if (version) base.version = version;
      if (auth) { base.login = 'user'; base.password = 'password'; base.auth_key = 'secret'; }

      const n = singleMember ? 1 : 3;
      let path, body;
      if (clusterType === 'single') {
        path = 'servers'; body = { ...base, name: 'mongod', procParams: {} };
      } else if (clusterType === 'repl') {
        path = 'replica_sets';
        body = { ...base, members: Array.from({ length: n }, () => ({ procParams: {} })) };
      } else {
        path = 'sharded_clusters';
        body = { ...base, configsvrs: [{}], routers: [{}],
          shards: [{ id: 'shard-0', shardParams: {
            members: Array.from({ length: n }, () => ({ procParams: {} })) } }] };
      }

      const resultEl = document.getElementById('result');
      try {
        const r = await fetch('/v1/' + path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json().catch(() => null);
        if (r.ok) {
          const uri = data?.mongodb_auth_uri || data?.mongodb_uri || '';
          resultEl.className = 'success';
          resultEl.textContent = 'Started  id: ' + data?.id + '\\n         uri: ' + uri;
          resultEl.style.display = 'block';
          btn.disabled = false; btn.textContent = 'Start';
          await refreshClusters();
        } else {
          resultEl.className = 'error';
          resultEl.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
          resultEl.style.display = 'block';
          btn.disabled = false; btn.textContent = 'Start';
        }
      } catch (err) {
        resultEl.className = 'error';
        resultEl.textContent = 'Error: ' + err.message;
        resultEl.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Start';
      }
    });

    // ── Partial refresh: update only #cluster-list without full reload ──────
    async function refreshClusters() {
      try {
        const r = await fetch('/dashboard-fragment');
        if (r.ok) {
          const html = await r.text();
          document.getElementById('cluster-list').innerHTML = html;
          document.querySelector('.refresh-info').textContent =
            'updated at ' + new Date().toLocaleTimeString();
        }
      } catch (_) {}
      scheduleRefresh();
    }

    let _refreshTimer;
    function scheduleRefresh() {
      clearTimeout(_refreshTimer);
      _refreshTimer = setTimeout(refreshClusters, 5000);
    }
    scheduleRefresh();

    document.addEventListener('click', scheduleRefresh);
"""


def _page(cards_html, version_options, generated_at):
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mongo Orchestration</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>Mongo Orchestration</h1>
  <p class="subtitle">REST API at <code>/v1/</code></p>

  <h2>Running clusters <span class="refresh-info">generated at {_e(generated_at)}</span></h2>
  <div id="cluster-list">{cards_html}</div>

  <h2>Start a new cluster</h2>
  <div class="form-card">
    <form id="launch-form">
      <div class="form-row">
        <div class="field">
          <span>Type</span>
          <select id="cluster_type" name="cluster_type">
            <option value="single">Standalone</option>
            <option value="repl">Replica Set (3 members)</option>
            <option value="shard">Sharded Cluster</option>
          </select>
        </div>
        <div class="field">
          <span>Version</span>
          <select id="version" name="version">{version_options}</select>
        </div>
        <div class="checkboxes">
          <label><input type="checkbox" name="single_member" id="single_member"> Single member</label>
          <label><input type="checkbox" name="auth"> Auth</label>
          <label><input type="checkbox" name="ssl"> SSL</label>
        </div>
        <button type="submit" id="start-btn">Start</button>
      </div>
    </form>
    <div id="result"></div>
  </div>

  <script>{_JS}</script>
</body>
</html>"""


# ── Routes ─────────────────────────────────────────────────────────────────

def _cards_html(standalone, rs_list, shard_list):
    return ''.join(
        [_server_card(d) for d in standalone]
        + [_rs_card(d) for d in rs_list]
        + [_shard_card(d) for d in shard_list]
    ) or '<p class="empty">No clusters running.</p>'


@route('/')
def dashboard():
    import datetime
    standalone, rs_list, shard_list, releases = _gather()

    version_options = '<option value="">default</option>' + ''.join(
        f'<option value="{_e(v)}">{_e(v)}</option>' for v in releases
    )

    generated_at = datetime.datetime.now().strftime('%H:%M:%S')
    response.content_type = 'text/html; charset=utf-8'
    return _page(_cards_html(standalone, rs_list, shard_list), version_options, generated_at)


@route('/dashboard-fragment')
def dashboard_fragment():
    standalone, rs_list, shard_list, _ = _gather()
    response.content_type = 'text/html; charset=utf-8'
    return _cards_html(standalone, rs_list, shard_list)
