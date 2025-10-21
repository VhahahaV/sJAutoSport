"""
用户管理模块 - 处理用户选择、创建和管理
"""
import os
import getpass
from typing import Optional, List, Tuple
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from .models import UserAuth, AuthConfig

console = Console()


def select_user(auth_config: AuthConfig) -> Tuple[Optional[UserAuth], bool]:
    """
    让用户选择已有用户或创建新用户
    
    Returns:
        Tuple[Optional[UserAuth], bool]: (选中的用户, 是否为新用户)
    """
    existing_users = [user for user in auth_config.users if user.username]
    
    if not existing_users:
        console.print("[blue]没有找到已保存的用户，将创建新用户[/blue]")
        return None, True
    
    # 显示已有用户列表
    console.print("\n[bold blue]已保存的用户列表：[/bold blue]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("序号", style="dim", width=6)
    table.add_column("昵称", style="cyan")
    table.add_column("用户名", style="green")
    
    for i, user in enumerate(existing_users, 1):
        table.add_row(str(i), user.nickname, user.username or "未设置")
    
    console.print(table)
    
    # 用户选择
    console.print("\n[bold yellow]请选择操作：[/bold yellow]")
    console.print("[cyan]1.[/cyan] 选择已有用户")
    console.print("[cyan]2.[/cyan] 创建新用户")
    console.print("[cyan]3.[/cyan] 删除用户")
    console.print("[cyan]4.[/cyan] 取消")
    
    while True:
        try:
            choice = Prompt.ask(
                "\n请输入选择",
                choices=["1", "2", "3", "4"],
                default="1"
            )
        except EOFError:
            # 在非交互式环境中，使用默认选择
            choice = "1"
            console.print("\n[blue]非交互式环境，使用默认选择：选择已有用户[/blue]")
        
        if choice == "1":  # 选择已有用户
            try:
                try:
                    user_index = int(Prompt.ask("请输入用户序号", default="1")) - 1
                except EOFError:
                    user_index = 0  # 默认选择第一个用户
                    console.print("[blue]非交互式环境，选择第一个用户[/blue]")
                
                if 0 <= user_index < len(existing_users):
                    selected_user = existing_users[user_index]
                    console.print(f"[green]已选择用户：{selected_user.nickname}[/green]")
                    return selected_user, False
                else:
                    console.print("[red]无效的用户序号[/red]")
            except ValueError:
                console.print("[red]请输入有效的数字[/red]")
        
        elif choice == "2":  # 创建新用户
            return None, True
        
        elif choice == "3":  # 删除用户
            try:
                user_index = int(Prompt.ask("请输入要删除的用户序号", default="1")) - 1
                if 0 <= user_index < len(existing_users):
                    user_to_delete = existing_users[user_index]
                    if Confirm.ask(f"确认删除用户 '{user_to_delete.nickname}' 吗？"):
                        auth_config.users.remove(user_to_delete)
                        console.print(f"[green]已删除用户：{user_to_delete.nickname}[/green]")
                    else:
                        console.print("[yellow]取消删除[/yellow]")
                else:
                    console.print("[red]无效的用户序号[/red]")
            except ValueError:
                console.print("[red]请输入有效的数字[/red]")
        
        elif choice == "4":  # 退出
            console.print("[yellow]取消登录[/yellow]")
            return None, False


def create_new_user() -> Optional[UserAuth]:
    """
    创建新用户
    
    Returns:
        Optional[UserAuth]: 新创建的用户，如果用户取消则返回 None
    """
    console.print("\n[bold blue]创建新用户[/bold blue]")
    
    username = Prompt.ask("请输入用户名（邮箱）")
    if not username:
        console.print("[red]用户名不能为空[/red]")
        return None
    
    password = getpass.getpass("请输入密码: ")
    if not password:
        console.print("[red]密码不能为空[/red]")
        return None
    
    # 询问是否记住用户
    if Confirm.ask("是否记住此用户？"):
        nickname = Prompt.ask("请输入用户昵称", default=username.split("@")[0])
        if not nickname:
            nickname = username.split("@")[0]
        
        # 询问是否保存密码
        save_password = Confirm.ask("是否保存密码？（不推荐）", default=False)
        
        new_user = UserAuth(
            nickname=nickname,
            cookie=None,
            token=None,
            username=username,
            password=password if save_password else None
        )
        
        console.print(f"[green]已创建用户：{nickname}[/green]")
        return new_user
    else:
        # 临时用户，不保存
        temp_user = UserAuth(
            nickname="临时用户",
            cookie=None,
            token=None,
            username=username,
            password=None
        )
        console.print("[yellow]创建临时用户（不保存）[/yellow]")
        return temp_user


def get_login_credentials(user: Optional[UserAuth]) -> Tuple[str, str, Optional[UserAuth]]:
    """
    获取登录凭据
    
    Args:
        user: 选中的用户，如果为 None 则创建新用户
    
    Returns:
        Tuple[str, str, Optional[UserAuth]]: (username, password, 对应的用户对象)
    """
    if user and user.username:
        console.print(f"[blue]使用用户：{user.nickname} ({user.username})[/blue]")
        
        if user.password:
            # 使用保存的密码
            try:
                if Confirm.ask("使用保存的密码登录？", default=True):
                    return user.username, user.password, user
            except EOFError:
                console.print("[blue]非交互式环境，使用保存的密码[/blue]")
                return user.username, user.password, user
        
        # 输入密码
        try:
            password = getpass.getpass("请输入密码: ")
        except EOFError:
            # 在非交互式环境中，提示用户使用命令行参数
            console.print("[red]非交互式环境无法输入密码，请使用命令行参数：[/red]")
            console.print("[blue]python main.py login --username <用户名> --password <密码>[/blue]")
            raise ValueError("非交互式环境无法输入密码")
        
        return user.username, password, user
    else:
        # 创建新用户
        new_user = create_new_user()
        if new_user:
            if new_user.password:
                return new_user.username, new_user.password, new_user
            else:
                try:
                    password = getpass.getpass("请输入密码: ")
                    return new_user.username, password, new_user
                except EOFError:
                    console.print("[red]非交互式环境无法输入密码[/red]")
                    raise ValueError("非交互式环境无法输入密码")
        else:
            raise ValueError("用户取消登录")


def save_user_to_config(user: UserAuth, auth_config: AuthConfig) -> None:
    """
    将用户保存到配置中
    """
    if user.nickname == "临时用户":
        return  # 不保存临时用户
    
    # 检查是否已存在相同用户名的用户
    existing_user = None
    for existing in auth_config.users:
        if existing.username == user.username:
            existing_user = existing
            break
    
    if existing_user:
        # 更新现有用户
        existing_user.nickname = user.nickname
        existing_user.password = user.password
        existing_user.username = user.username
        if user.cookie:
            existing_user.cookie = user.cookie
        console.print(f"[blue]已更新用户：{user.nickname}[/blue]")
    else:
        # 添加新用户
        auth_config.users.append(user)
        console.print(f"[green]已添加新用户：{user.nickname}[/green]")


def show_user_management_menu(auth_config: AuthConfig) -> None:
    """
    显示用户管理菜单
    """
    console.print("\n[bold blue]用户管理菜单[/bold blue]")
    console.print("\n[bold yellow]请选择操作：[/bold yellow]")
    console.print("[cyan]1.[/cyan] 查看用户列表")
    console.print("[cyan]2.[/cyan] 添加用户")
    console.print("[cyan]3.[/cyan] 删除用户")
    console.print("[cyan]4.[/cyan] 返回")
    
    while True:
        choice = Prompt.ask(
            "\n请输入选择",
            choices=["1", "2", "3", "4"],
            default="1"
        )
        
        if choice == "1":  # 查看用户列表
            show_users(auth_config)
        
        elif choice == "2":  # 添加用户
            new_user = create_new_user()
            if new_user and new_user.nickname != "临时用户":
                auth_config.users.append(new_user)
                console.print(f"[green]已添加用户：{new_user.nickname}[/green]")
        
        elif choice == "3":  # 删除用户
            delete_user(auth_config)
        
        elif choice == "4":  # 返回
            break


def show_users(auth_config: AuthConfig) -> None:
    """
    显示用户列表
    """
    users = [user for user in auth_config.users if user.username]
    
    if not users:
        console.print("[yellow]没有已保存的用户[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("昵称", style="cyan")
    table.add_column("用户名", style="green")
    table.add_column("密码已保存", style="yellow")
    
    for user in users:
        password_saved = "是" if user.password else "否"
        table.add_row(user.nickname, user.username or "未设置", password_saved)
    
    console.print(table)


def delete_user(auth_config: AuthConfig) -> None:
    """
    删除用户
    """
    users = [user for user in auth_config.users if user.username]
    
    if not users:
        console.print("[yellow]没有可删除的用户[/yellow]")
        return
    
    show_users(auth_config)
    
    try:
        user_index = int(Prompt.ask("请输入要删除的用户序号", default="1")) - 1
        if 0 <= user_index < len(users):
            user_to_delete = users[user_index]
            if Confirm.ask(f"确认删除用户 '{user_to_delete.nickname}' 吗？"):
                auth_config.users.remove(user_to_delete)
                console.print(f"[green]已删除用户：{user_to_delete.nickname}[/green]")
            else:
                console.print("[yellow]取消删除[/yellow]")
        else:
            console.print("[red]无效的用户序号[/red]")
    except ValueError:
        console.print("[red]请输入有效的数字[/red]")
