"""管理后台的业务逻辑 + 命令行入口。

只读元数据：标题、数量、用量、状态、报错——不返回小说原文与分镜内容。
命令行：python -m server.admin promote|demote <用户名> / list / backfill-usage
"""
import csv
import io
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.manifest import sum_usage
from server import audit, auth, novels, pricing, store, usage


class AdminError(Exception):
    """可预期的拒绝（400）。"""


class NotFound(AdminError):
    """目标不存在（404）。"""


PURPOSES = ("convert", "digest")
FAILED_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(user_id: str) -> dict:
    u = auth.get_user_raw(user_id)
    if u is None:
        raise NotFound("用户不存在")
    return u


def _row(u: dict, month_cost: float) -> dict:
    c = novels.counts(u["id"])
    return {"id": u["id"], "username": u["username"], "role": u["role"],
            "disabled": u["disabled"], "created_at": u.get("created_at"),
            "last_seen_at": u.get("last_seen_at"), "has_password": u["has_password"],
            "monthly_cap_usd": u.get("monthly_cap_usd"), **c,
            "month_cost_usd": month_cost}


def _month_costs(table: dict) -> dict:
    out: dict = {}
    for r in usage.read(since=usage.month_start()):
        out[r["user_id"]] = out.get(r["user_id"], 0.0) + (pricing.cost(r, table) or 0.0)
    return out


def user_rows(table: dict) -> list:
    costs = _month_costs(table)
    return [_row(u, costs.get(u["id"], 0.0)) for u in auth.list_users_safe()]


def user_detail(user_id: str, table: dict) -> dict:
    u = _user(user_id)
    rows = usage.read(user_id=user_id)
    recent = []
    for r in list(reversed(rows))[:50]:
        nt, ct = novels.titles(user_id, r.get("novel_id"), r.get("chapter_id"))
        recent.append({**r, "novel_title": nt, "chapter_title": ct,
                       "cost_usd": pricing.cost(r, table)})
    month = sum(pricing.cost(r, table) or 0.0 for r in rows
                if usage._when(r) >= usage.month_start())
    since = _now() - timedelta(days=30)
    return {"user": _row(u, month), "recent": recent,
            "daily": usage.daily_series([r for r in rows if usage._when(r) >= since],
                                        30, table)}


def _active_admins() -> list:
    return [u for u in auth.list_users_safe() if u["role"] == "admin" and not u["disabled"]]


def _guard_last_admin(user_id: str) -> None:
    """user_id 将失去管理权（降级或停用）时，系统里必须还有别的未停用管理员。"""
    others = [u for u in _active_admins() if u["id"] != user_id]
    if not others:
        raise AdminError("至少保留一个管理员")


def patch_user(admin_user: dict, user_id: str, body: dict) -> dict:
    if len(body) != 1:
        raise AdminError("一次只能修改一项")
    (field, value), = body.items()
    target = _user(user_id)
    self_edit = user_id == admin_user["id"]
    if field == "disabled":
        if not isinstance(value, bool):
            raise AdminError("disabled 必须是 true 或 false")
        if value and self_edit:
            raise AdminError("不能停用自己")
        if value and target["role"] == "admin":
            _guard_last_admin(user_id)
        action = "disable" if value else "enable"
    elif field == "role":
        if value not in auth.ROLES:
            raise AdminError("角色只能是 admin 或 user")
        if self_edit:
            raise AdminError("不能修改自己的角色")
        if value == "user" and target["role"] == "admin":
            _guard_last_admin(user_id)
        action = "grant_admin" if value == "admin" else "revoke_admin"
    elif field == "monthly_cap_usd":
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise AdminError("月上限必须是非负数，或留空表示不限")
            value = float(value)
        action = "set_cap"
    else:
        raise AdminError(f"不支持修改 {field}")
    before = {field: target.get(field)}
    auth.update_user(user_id, **{field: value})
    audit.write(admin_user, action, target, before, {field: value})
    return _row(_user(user_id), _month_costs(pricing.load()).get(user_id, 0.0))


def reset_password(admin_user: dict, user_id: str, password: str) -> None:
    target = _user(user_id)
    try:
        auth.set_password(user_id, password)
    except auth.AuthError as e:
        raise AdminError(str(e))
    audit.write(admin_user, "reset_password", target)


def _version_files(min_mtime: Optional[float] = None):
    users_root = auth.DATA_DIR / "users"
    if not users_root.exists():
        return
    for udir in users_root.iterdir():
        if not udir.is_dir():
            continue
        for path in novels.novels_dir(udir.name).glob("*/chapters/*/versions/*.json"):
            try:
                if min_mtime is not None and path.stat().st_mtime < min_mtime:
                    continue
                yield udir.name, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue


def jobs_view(memory_jobs: list) -> dict:
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    now = _now()
    running = []
    for j in memory_jobs:
        if j.get("status") not in ("queued", "running"):
            continue
        started = j.get("created_at")
        elapsed = None
        if started:
            elapsed = int((now - datetime.fromisoformat(started)).total_seconds())
        running.append({"id": j["id"], "user_id": j.get("user_id"),
                        "username": names.get(j.get("user_id")), "status": j["status"],
                        "work_title": j.get("work_title"), "chapter": j.get("chapter"),
                        "chars": j.get("chars"), "created_at": started,
                        "elapsed_sec": elapsed})
    since = now - timedelta(days=FAILED_DAYS)
    failed = []
    for uid, v in _version_files(min_mtime=since.timestamp()):
        if v.get("status") != "failed" or not v.get("created_at"):
            continue
        if datetime.fromisoformat(v["created_at"]) < since:
            continue
        m = v.get("manifest") or {}
        nt, ct = novels.titles(uid, v.get("novel_id"), v.get("chapter_id"))
        failed.append({"id": v["id"], "user_id": uid, "username": names.get(uid),
                       "novel_title": nt, "chapter_title": ct,
                       "created_at": v["created_at"],
                       "chars": (m.get("input") or {}).get("normalized_chars")
                       or len(v.get("input_text") or ""),
                       "attempts": len(m.get("attempts") or []),
                       "error": (v.get("error") or "")[:300]})
    failed.sort(key=lambda x: x["created_at"], reverse=True)
    return {"running": running, "failed": failed}


def overview(table: dict, running: int) -> dict:
    now = _now()
    users = auth.list_users_safe()
    week = now - timedelta(days=7)
    active = sum(1 for u in users
                 if u.get("last_seen_at") and datetime.fromisoformat(u["last_seen_at"]) >= week)
    rows = usage.read(since=now - timedelta(days=30))
    tokens = sum(r.get(k) or 0 for r in rows
                 for k in ("input", "output", "cache_read", "cache_write"))
    cost = sum(pricing.cost(r, table) or 0.0 for r in rows)
    return {"users": len(users), "active_7d": active, "tokens_30d": tokens,
            "cost_30d": cost, "running": running,
            "failed_7d": len(jobs_view([])["failed"]),
            "daily": usage.daily_series(rows, 30, table, now=now),
            "unpriced_models": usage.unpriced_models(rows, table)}


def usage_report(group: str, days: int, table: dict) -> dict:
    rows = usage.read(since=_now() - timedelta(days=days))
    try:
        groups = usage.aggregate(rows, group, table)
    except ValueError as e:
        raise AdminError(str(e))
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    for g in groups:
        g["label"] = names.get(g["key"], g["key"]) if group == "user" else g["key"]
    return {"group": group, "days": days, "rows": groups,
            "per_k_chars": usage.per_k_chars(rows, table),
            "unpriced_models": usage.unpriced_models(rows, table)}


CSV_FIELDS = ("at", "user_id", "username", "purpose", "model", "ok", "calls", "input",
              "output", "cache_read", "cache_write", "chars", "cost_usd")


def usage_csv(days: int, table: dict) -> str:
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_FIELDS)
    for r in usage.read(since=_now() - timedelta(days=days)):
        c = pricing.cost(r, table)
        w.writerow([r["at"], r.get("user_id"), names.get(r.get("user_id"), ""),
                    r.get("purpose"), r.get("model"), r.get("ok"), r.get("calls"),
                    r.get("input"), r.get("output"), r.get("cache_read"),
                    r.get("cache_write"), r.get("chars"),
                    "" if c is None else f"{c:.6f}"])
    return buf.getvalue()


def backfill_usage() -> dict:
    """从已有版本记录补导转换用量；按 (user_id, version_id, purpose) 去重，重复执行安全。"""
    seen = {(r.get("user_id"), r.get("version_id"), r.get("purpose")) for r in usage.read()}
    added = existing = skipped = 0
    for uid, v in _version_files():
        key = (uid, v.get("id"), "convert")
        if key in seen:
            existing += 1
            continue
        m = v.get("manifest") or {}
        totals = m.get("usage") or (sum_usage(m["attempts"]) if m.get("attempts") else None)
        if not totals or not any(totals.get(k) for k in usage.TOKENS):
            skipped += 1
            continue
        usage.record(user_id=uid, purpose="convert",
                     model=(m.get("contracts") or {}).get("model") or "unknown",
                     usage=totals,
                     ok=v.get("status") in ("succeeded", "completed_with_warnings"),
                     chars=(m.get("input") or {}).get("normalized_chars")
                     or len(v.get("input_text") or ""),
                     novel_id=v.get("novel_id"), chapter_id=v.get("chapter_id"),
                     version_id=v.get("id"), at=v.get("created_at") or store.now_iso())
        seen.add(key)
        added += 1
    return {"added": added, "existing": existing, "skipped_no_usage": skipped}


def _find(username: str) -> Optional[dict]:
    return next((u for u in auth.list_users_safe()
                 if u["username"].lower() == username.lower()), None)


def main(argv: list) -> int:
    if not argv or argv[0] not in ("promote", "demote", "list", "backfill-usage"):
        print("用法: python -m server.admin promote|demote <用户名> | list | backfill-usage")
        return 2
    cmd = argv[0]
    if cmd == "list":
        for u in auth.list_users_safe():
            flag = " [停用]" if u["disabled"] else ""
            print(f"{u['id']}  {u['role']:5}  {u['username']}{flag}")
        return 0
    if cmd == "backfill-usage":
        print(backfill_usage())
        return 0
    if len(argv) < 2:
        print("缺少用户名")
        return 2
    u = _find(argv[1])
    if u is None:
        print(f"找不到用户：{argv[1]}")
        return 1
    if cmd == "demote" and u["role"] == "admin":
        try:
            _guard_last_admin(u["id"])
        except AdminError as e:
            print(e)
            return 1
    auth.update_user(u["id"], role="admin" if cmd == "promote" else "user")
    print(f"{u['username']} → {'admin' if cmd == 'promote' else 'user'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
