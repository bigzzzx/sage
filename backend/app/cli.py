"""One-off administrative commands for a new SAGE installation."""
from __future__ import annotations

import argparse
import getpass
import sqlite3
from pathlib import Path

from app.api.auth import _hash_password
from app.db import SessionLocal, engine, init_db
from app.models import User


def _create_user(username: str, password: str, display_name: str, role: str) -> str:
    """Create a user without preset credentials; refuse existing names."""
    if not 2 <= len(username) <= 32 or not username.isascii() or not username.replace("_", "").isalnum():
        raise ValueError("用户名须为 2-32 位 ASCII 字母、数字或下划线")
    if len(password) < 12:
        raise ValueError("管理员密码至少 12 位")
    init_db()
    with SessionLocal() as db:
        if db.query(User).filter_by(username=username).first():
            raise ValueError("用户名已存在；不会更改现有账号的角色或密码")
        user = User(username=username, password_hash=_hash_password(password),
                    display_name=display_name.strip() or username, role=role,
                    current_profile="big_data")
        db.add(user)
        db.commit()
        return user.id


def create_admin(username: str, password: str, display_name: str = "") -> str:
    return _create_user(username, password, display_name, "manager")


def create_member(username: str, password: str, display_name: str = "") -> str:
    return _create_user(username, password, display_name, "member")


def backup_sqlite(output: str) -> Path:
    """Create a consistent SQLite snapshot; never replace an existing file."""
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database:
        raise ValueError("备份命令仅支持当前 SQLite 数据库")
    source = Path(engine.url.database).resolve()
    destination = Path(output).resolve()
    if source == destination or destination.exists():
        raise ValueError("备份目标不能是数据库本身，也不能覆盖现有文件")
    if not source.is_file() or not destination.parent.is_dir():
        raise ValueError("数据库或备份目标目录不存在")
    with sqlite3.connect(source) as from_db, sqlite3.connect(destination) as to_db:
        from_db.backup(to_db)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="SAGE 管理命令")
    subcommands = parser.add_subparsers(dest="command", required=True)
    admin = subcommands.add_parser("create-admin", help="交互式创建管理员")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="")
    member = subcommands.add_parser("create-member", help="交互式创建普通成员")
    member.add_argument("--username", required=True)
    member.add_argument("--display-name", default="")
    backup = subcommands.add_parser("backup", help="在线备份当前 SQLite 数据库")
    backup.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command in {"create-admin", "create-member"}:
        password = getpass.getpass("账号密码（至少 12 位）：")
        confirm = getpass.getpass("再次输入密码：")
        if password != confirm:
            parser.error("两次输入的密码不一致")
        try:
            create = create_admin if args.command == "create-admin" else create_member
            user_id = create(args.username, password, args.display_name)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"账号 {args.username} 已创建（ID: {user_id}）")
    elif args.command == "backup":
        try:
            path = backup_sqlite(args.output)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"SQLite 备份已创建：{path}")


if __name__ == "__main__":
    main()
