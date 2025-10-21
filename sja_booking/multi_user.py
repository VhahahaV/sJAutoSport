"""多用户管理模块"""

from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from rich.console import Console
from .models import AuthConfig, UserAuth, BookingTarget


@dataclass
class UserBookingResult:
    """单个用户的预订结果"""
    nickname: str
    success: bool
    message: str
    order_id: Optional[str] = None
    error: Optional[str] = None


class MultiUserManager:
    """多用户管理器"""
    
    def __init__(self, auth_config: AuthConfig, console: Console):
        self.auth_config = auth_config
        self.console = console
        self.users = auth_config.users or []
        self._current_user_index = 0
    
    def get_available_users(self) -> List[UserAuth]:
        """获取可用的用户列表"""
        return [user for user in self.users if user.cookie or user.token]
    
    def get_current_user(self) -> Optional[UserAuth]:
        """获取当前用户"""
        available_users = self.get_available_users()
        if not available_users:
            return None
        return available_users[self._current_user_index % len(available_users)]
    
    def switch_to_next_user(self) -> Optional[UserAuth]:
        """切换到下一个用户"""
        available_users = self.get_available_users()
        if not available_users:
            return None
        
        self._current_user_index = (self._current_user_index + 1) % len(available_users)
        return self.get_current_user()
    
    def get_users_for_booking(self, target: BookingTarget) -> List[UserAuth]:
        """根据BookingTarget获取需要预订的用户列表"""
        available_users = self.get_available_users()
        
        if not available_users:
            return []
        
        # 如果指定了目标用户
        if target.target_users:
            target_users = [user for user in available_users if user.nickname in target.target_users]
            if target_users:
                return target_users
        
        # 如果指定了排除用户
        if target.exclude_users:
            return [user for user in available_users if user.nickname not in target.exclude_users]
        
        # 默认返回所有用户
        return available_users
    
    def handle_rate_limit(self, error_msg: str) -> Optional[UserAuth]:
        """处理频率限制，切换到下一个用户"""
        if "请求过于频繁" in error_msg or "频率" in error_msg or "500" in error_msg:
            next_user = self.switch_to_next_user()
            if next_user:
                self.console.print(f"[yellow]检测到频率限制，切换到用户: {next_user.nickname}[/yellow]")
            return next_user
        return None
    
    def print_user_status(self, results: List[UserBookingResult]):
        """打印所有用户的预订状态"""
        if not results:
            return
        
        self.console.print(f"\n[bold]📊 多用户预订结果汇总[/bold]")
        
        success_count = sum(1 for r in results if r.success)
        total_count = len(results)
        
        self.console.print(f"[green]✅ 成功: {success_count}/{total_count}[/green]")
        
        for result in results:
            if result.success:
                self.console.print(f"[green]  {result.nickname}: {result.message}[/green]")
                if result.order_id:
                    self.console.print(f"[green]    订单ID: {result.order_id}[/green]")
            else:
                self.console.print(f"[red]  {result.nickname}: {result.message}[/red]")
                if result.error:
                    self.console.print(f"[red]    错误: {result.error}[/red]")
    
    def get_user_by_nickname(self, nickname: str) -> Optional[UserAuth]:
        """根据昵称获取用户"""
        for user in self.users:
            if user.nickname == nickname:
                return user
        return None
    
    def list_users(self):
        """列出所有用户"""
        if not self.users:
            self.console.print("[yellow]没有配置任何用户[/yellow]")
            return
        
        self.console.print("[bold]👥 已配置的用户列表:[/bold]")
        for i, user in enumerate(self.users, 1):
            status = "✅ 可用" if (user.cookie or user.token) else "❌ 不可用"
            self.console.print(f"  {i}. {user.nickname} - {status}")
            if user.username:
                self.console.print(f"     用户名: {user.username}")
    
    def validate_users(self) -> Tuple[bool, List[str]]:
        """验证用户配置"""
        errors = []
        
        if not self.users:
            errors.append("没有配置任何用户")
            return False, errors
        
        available_count = 0
        for user in self.users:
            if not user.nickname:
                errors.append("存在没有昵称的用户")
            elif not (user.cookie or user.token or user.username):
                errors.append(f"用户 '{user.nickname}' 没有配置任何认证信息")
            else:
                available_count += 1
        
        if available_count == 0:
            errors.append("没有可用的用户（所有用户都缺少认证信息）")
        
        return len(errors) == 0, errors
