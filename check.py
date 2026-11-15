"""Отладочная страница content.db.
Запуск:
    python debug_content.py
Открыть:
    http://127.0.0.1:8091/
"""
import sqlite3
from pathlib import Path

from aiohttp import web

BASE_DIR = Path(__file__).resolve().parent
CONTENT_DB = BASE_DIR / "content.db"


def _conn():
    conn = sqlite3.connect(str(CONTENT_DB), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, sql, params=()):
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as e:
        return [{"__error__": str(e)}]


def _stats(conn):
    out = {}
    def one(sql):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:
            return None
    out["fragments_total"] = one("SELECT COUNT(*) FROM fragments")
    out["fragments_short"] = one(
        "SELECT COUNT(*) FROM fragments WHERE LENGTH(TRIM(text_ba)) <= 40"
    )
    out["translations_total"] = one("SELECT COUNT(*) FROM translations")
    out["translations_confirmed"] = one(
        "SELECT COUNT(*) FROM translations WHERE status='confirmed'"
    )
    out["translations_pending"] = one(
        "SELECT COUNT(*) FROM translations WHERE status='pending'"
    )
    out["translations_review"] = one(
        "SELECT COUNT(*) FROM translations WHERE status='expert_review'"
    )
    out["fragments_without_confirmed"] = one("""
        SELECT COUNT(*) FROM fragments f
        WHERE NOT EXISTS (
            SELECT 1 FROM translations t
            WHERE t.fragment_id = f.fragment_id
              AND t.lang_pair = f.lang_pair
              AND t.status = 'confirmed'
        )
    """)
    out["dictionary_total"] = one("SELECT COUNT(*) FROM dictionary")
    return out


async def index(request):
    if not CONTENT_DB.exists():
        return web.Response(
            text=f"content.db не найден: {CONTENT_DB}",
            content_type="text/plain",
            status=404,
        )

    conn = _conn()
    try:
        stats = _stats(conn)

        frags = _rows(conn, """
            SELECT f.fragment_id, f.text_ba, f.lang_pair, f.source,
                   f.is_parsed, f.created_at,
                   (SELECT COUNT(*) FROM translations t
                    WHERE t.fragment_id = f.fragment_id) AS tr_count,
                   (SELECT COUNT(*) FROM translations t
                    WHERE t.fragment_id = f.fragment_id AND t.status='confirmed') AS tr_confirmed
            FROM fragments f
            ORDER BY f.fragment_id DESC
            LIMIT 500
        """)

        trans = _rows(conn, """
            SELECT t.id, t.fragment_id, t.lang_pair, t.translation,
                   t.normalized, t.confirmed, t.status, t.source,
                   t.is_parsed, t.user_id, t.created_at, t.updated_at,
                   f.text_ba
            FROM translations t
            LEFT JOIN fragments f ON f.fragment_id = t.fragment_id
            ORDER BY t.id DESC
            LIMIT 500
        """)

        votes = _rows(conn, """
            SELECT id, translation_id, user_id, vote_type, created_at
            FROM translation_votes ORDER BY id DESC LIMIT 200
        """)

        dict_rows = _rows(conn, """
            SELECT id, word, translation, lang_pair, is_parsed, status,
                   source, confirmed, created_at
            FROM dictionary ORDER BY id DESC LIMIT 200
        """)

    finally:
        conn.close()

    html = _render(stats, frags, trans, votes, dict_rows)
    return web.Response(text=html, content_type="text/html")


def _esc(v):
    if v is None:
        return '<span class="muted">NULL</span>'
    s = str(v)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _badge(text, cls=""):
    return f'<span class="badge {cls}">{_esc(text)}</span>'


def _render(stats, frags, trans, votes, dict_rows):
    def stat_card(label, value, warn=False):
        cls = "stat warn" if warn and (value == 0 or value is None) else "stat"
        return f'<div class="{cls}"><div class="k">{_esc(label)}</div><div class="v">{_esc(value if value is not None else "—")}</div></div>'

    stats_html = "".join([
        stat_card("Фрагментов", stats["fragments_total"]),
        stat_card("Коротких (≤40)", stats["fragments_short"]),
        stat_card("Без confirmed", stats["fragments_without_confirmed"], warn=True),
        stat_card("Переводов всего", stats["translations_total"]),
        stat_card("confirmed", stats["translations_confirmed"], warn=True),
        stat_card("pending", stats["translations_pending"]),
        stat_card("expert_review", stats["translations_review"]),
        stat_card("dictionary", stats["dictionary_total"]),
    ])

    def frag_row(f):
        words = len((f["text_ba"] or "").split())
        warn = ""
        if words > 3:
            warn = ' class="warn-row"'
        if f["tr_confirmed"] == 0:
            warn = ' class="err-row"'
        return (
            f"<tr{warn}>"
            f"<td>{_esc(f['fragment_id'])}</td>"
            f"<td>{_esc(f['text_ba'])}</td>"
            f"<td>{_esc(f['lang_pair'])}</td>"
            f"<td>{words}</td>"
            f"<td>{_esc(f['source'])}</td>"
            f"<td>{_badge('parsed' if f['is_parsed'] else 'raw', 'ok' if f['is_parsed'] else '')}</td>"
            f"<td>{_esc(f['tr_count'])}</td>"
            f"<td>{_esc(f['tr_confirmed'])}</td>"
            f"<td>{_esc(f['created_at'])}</td>"
            f"</tr>"
        )

    def trans_row(t):
        cls = {
            "confirmed": "ok-row",
            "pending": "pend-row",
            "expert_review": "rev-row",
            "rejected": "err-row",
        }.get(t["status"], "")
        cls = f' class="{cls}"' if cls else ""
        return (
            f"<tr{cls}>"
            f"<td>{_esc(t['id'])}</td>"
            f"<td>{_esc(t['fragment_id'])}</td>"
            f"<td>{_esc(t['text_ba'])}</td>"
            f"<td>{_esc(t['lang_pair'])}</td>"
            f"<td>{_esc(t['translation'])}</td>"
            f"<td>{_esc(t['normalized'])}</td>"
            f"<td>{_esc(t['confirmed'])}</td>"
            f"<td>{_badge(t['status'], 'ok' if t['status']=='confirmed' else 'warn' if t['status'] in ('pending','expert_review') else 'err')}</td>"
            f"<td>{_esc(t['source'])}</td>"
            f"<td>{_esc(t['user_id'])}</td>"
            f"<td>{_esc(t['updated_at'])}</td>"
            f"</tr>"
        )

    def dict_row(d):
        return (
            f"<tr>"
            f"<td>{_esc(d['id'])}</td>"
            f"<td>{_esc(d['word'])}</td>"
            f"<td>{_esc(d['translation'])}</td>"
            f"<td>{_esc(d['lang_pair'])}</td>"
            f"<td>{_esc(d['is_parsed'])}</td>"
            f"<td>{_badge(d['status'], 'ok' if d['status']=='confirmed' else 'warn')}</td>"
            f"<td>{_esc(d['source'])}</td>"
            f"<td>{_esc(d['created_at'])}</td>"
            f"</tr>"
        )

    frags_html = "".join(frag_row(f) for f in frags) or '<tr><td colspan="9" class="muted">пусто</td></tr>'
    trans_html = "".join(trans_row(t) for t in trans) or '<tr><td colspan="11" class="muted">пусто</td></tr>'
    votes_html = "".join(
        f"<tr><td>{_esc(v['id'])}</td><td>{_esc(v['translation_id'])}</td>"
        f"<td>{_esc(v['user_id'])}</td><td>{_esc(v['vote_type'])}</td>"
        f"<td>{_esc(v['created_at'])}</td></tr>"
        for v in votes
    ) or '<tr><td colspan="5" class="muted">пусто</td></tr>'
    dict_html = "".join(dict_row(d) for d in dict_rows) or '<tr><td colspan="8" class="muted">пусто</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>content.db — отладка</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f8f5;color:#1f2e27}}
h1{{margin:20px 24px 8px;font-size:22px}}
h2{{margin:26px 24px 10px;font-size:16px;color:#178553}}
.path{{margin:0 24px 18px;color:#6b7a72;font-size:12px;font-family:monospace}}
.stats{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin:0 24px 24px}}
.stat{{background:#fff;border:1px solid #dbe6dc;border-radius:12px;padding:12px}}
.stat .k{{font-size:11px;color:#7d9387;text-transform:uppercase;letter-spacing:.05em}}
.stat .v{{font-size:22px;font-weight:700;margin-top:4px}}
.stat.warn{{border-color:#e8c97b;background:#fff8e6}}
.wrap{{margin:0 24px 28px;background:#fff;border:1px solid #dbe6dc;border-radius:12px;overflow:auto;max-height:70vh}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eef3ee;white-space:nowrap}}
th{{background:#f1f6f1;position:sticky;top:0;font-weight:600;font-size:12px;color:#3b5044}}
tr:hover td{{background:#f9fcf8}}
.muted{{color:#9aaba1;font-style:italic}}
.badge{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;background:#eef3ee;color:#4a5d52}}
.badge.ok{{background:#dff3e1;color:#166b3d}}
.badge.warn{{background:#fff1cf;color:#8a610b}}
.badge.err{{background:#fde2e2;color:#a02c2c}}
tr.ok-row td{{background:#f0fbf2}}
tr.pend-row td{{background:#fffdf2}}
tr.rev-row td{{background:#fff8e6}}
tr.err-row td{{background:#fdf3f3}}
tr.warn-row td:first-child{{box-shadow:inset 4px 0 0 #e8c97b}}
.toolbar{{display:flex;gap:10px;margin:0 24px 14px}}
.toolbar a{{text-decoration:none;font-size:13px;color:#178553;background:#fff;border:1px solid #dbe6dc;padding:7px 12px;border-radius:8px}}
.toolbar a:hover{{background:#eef7ef}}
</style>
</head>
<body>
<h1>content.db — отладочная страница</h1>
<div class="path">{_esc(CONTENT_DB)}</div>
<div class="toolbar">
  <a href="/">Обновить</a>
  <a href="/raw/fragments">JSON: fragments</a>
  <a href="/raw/translations">JSON: translations</a>
  <a href="/raw/dictionary">JSON: dictionary</a>
</div>
<div class="stats">{stats_html}</div>

<h2>Fragments <span class="muted">(топ-500 новых)</span></h2>
<div class="wrap"><table>
<tr><th>ID</th><th>text_ba</th><th>lang</th><th>слов</th><th>source</th><th>parsed</th><th>tr</th><th>conf</th><th>created</th></tr>
{frags_html}
</table></div>

<h2>Translations <span class="muted">(топ-500 новых)</span></h2>
<div class="wrap"><table>
<tr><th>ID</th><th>frag</th><th>text_ba</th><th>lang</th><th>translation</th><th>normalized</th><th>conf</th><th>status</th><th>source</th><th>user</th><th>updated</th></tr>
{trans_html}
</table></div>

<h2>Dictionary <span class="muted">(топ-200)</span></h2>
<div class="wrap"><table>
<tr><th>ID</th><th>word</th><th>translation</th><th>lang</th><th>parsed</th><th>status</th><th>source</th><th>created</th></tr>
{dict_html}
</table></div>

<h2>Translation votes <span class="muted">(топ-200)</span></h2>
<div class="wrap"><table>
<tr><th>ID</th><th>translation</th><th>user</th><th>type</th><th>created</th></tr>
{votes_html}
</table></div>

</body>
</html>"""


async def raw_fragments(request):
    conn = _conn()
    try:
        rows = _rows(conn, "SELECT * FROM fragments ORDER BY fragment_id DESC LIMIT 1000")
    finally:
        conn.close()
    return web.json_response(rows)


async def raw_translations(request):
    conn = _conn()
    try:
        rows = _rows(conn, "SELECT * FROM translations ORDER BY id DESC LIMIT 1000")
    finally:
        conn.close()
    return web.json_response(rows)


async def raw_dictionary(request):
    conn = _conn()
    try:
        rows = _rows(conn, "SELECT * FROM dictionary ORDER BY id DESC LIMIT 1000")
    finally:
        conn.close()
    return web.json_response(rows)


def create_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/raw/fragments", raw_fragments)
    app.router.add_get("/raw/translations", raw_translations)
    app.router.add_get("/raw/dictionary", raw_dictionary)
    return app


if __name__ == "__main__":
    print(f"DB: {CONTENT_DB}")
    print("Открой: http://127.0.0.1:8091/")
    web.run_app(create_app(), host="127.0.0.1", port=8091)