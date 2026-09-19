from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mico.tools.base")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]

    async def execute(self, **kwargs) -> str:
        """Execute the tool function (handling both sync and async functions) and return string output."""
        try:
            if inspect.iscoroutinefunction(self.func):
                result = await self.func(**kwargs)
            else:
                result = self.func(**kwargs)
                if inspect.isawaitable(result):
                    result = await result

            if isinstance(result, str):
                return result
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, default=str)
            return str(result)
        except Exception as exc:
            logger.exception("Error executing tool %s with args %s", self.name, kwargs)
            return f"Error executing {self.name}: {exc}"

    def to_openai_schema(self) -> dict[str, Any]:
        """Format tool description for OpenAI/Groq tool-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Format tool description for Google GenAI function declaration."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self.tools.values())

    async def execute(self, name: str, **kwargs) -> str:
        tool = self.get(name)
        if not tool:
            return f"Error: Tool '{name}' is not registered."
        return await tool.execute(**kwargs)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self.tools.values()]

    def to_gemini_declarations(self) -> list[dict[str, Any]]:
        return [tool.to_gemini_declaration() for tool in self.tools.values()]
