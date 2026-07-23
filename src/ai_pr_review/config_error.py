"""配置错误类型定义。

提供统一的配置错误异常体系，携带字段名、当前值、期望值与修复建议，
便于在启动校验时输出友好、可操作的错误提示。
"""

from typing import Any


class ConfigError(Exception):
    """配置错误基类。

    携带 field（字段名）、current_value（当前值）、expected（期望约束）、
    suggestion（修复建议）四项上下文，__str__ 输出可直接展示给用户的修复提示。
    """

    def __init__(
        self,
        field: str,
        current_value: Any,
        expected: str,
        suggestion: str,
    ) -> None:
        self.field = field
        self.current_value = current_value
        self.expected = expected
        self.suggestion = suggestion
        message = self._format_message()
        super().__init__(message)

    def _format_message(self) -> str:
        # 拼接字段名、当前值、期望值与修复建议，形成可读的错误描述
        return (
            f"配置项 '{self.field}' 无效："
            f"当前值={self.current_value!r}，期望{self.expected}。"
            f"修复建议：{self.suggestion}"
        )

    def __str__(self) -> str:
        return self._format_message()


class MissingRequiredError(ConfigError):
    """缺少必填配置项。

    current_value 固定为 None，expected 固定为“非空值”，
    调用方只需提供 field 与 suggestion。
    """

    def __init__(self, field: str, suggestion: str) -> None:
        super().__init__(
            field=field,
            current_value=None,
            expected="非空值",
            suggestion=suggestion,
        )


class InvalidValueError(ConfigError):
    """配置项值非法或越界。

    复用基类的字段构造逻辑，用于范围、枚举等校验失败场景。
    """

    pass
