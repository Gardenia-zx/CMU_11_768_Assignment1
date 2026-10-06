"""The Part 1 coding agent: fix a software issue and submit a git patch."""

from __future__ import annotations

import json
from typing import Any

from assignment.agent.base import (
    DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
    DEFAULT_COMPACTION_MAX_TOKENS,
    Agent,
    format_tool_output,
)
from assignment.agent.tools import EXECUTE_TOOL, SEND_MESSAGE_TOOL
from assignment.env import Environment

class CodeAgent(Agent):
    """An agent that fixes a software issue and submits a git patch."""

    def __init__(
        self,
        task: str,
        environment: Environment,
        model: str | None = None,
        logs_save_path: str | None = None,
        step_limit: int = 100,
        skills_path: str | None = None,
        auto_stop_environment: bool = True,
        compact_threshold_tokens: int | None = None,
        compaction_keep_recent_steps: int = DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
        compaction_max_tokens: int = DEFAULT_COMPACTION_MAX_TOKENS,
    ):
        super().__init__(
            environment=environment,
            model=model,
            logs_save_path=logs_save_path,
            step_limit=step_limit,
            skills_path=skills_path,
            auto_stop_environment=auto_stop_environment,
            compact_threshold_tokens=compact_threshold_tokens,
            compaction_keep_recent_steps=compaction_keep_recent_steps,
            compaction_max_tokens=compaction_max_tokens,
        )
        self.task = task
        self.submitted_patch = ""

        # TODO(Part 1.3): Make the `execute` and `send_message` tools available
        # to the agent.
        self.tools.extend([EXECUTE_TOOL, SEND_MESSAGE_TOOL])

        # TODO(1.1.b): Construct the system prompt and task_prompt. These
        # should be usable by the `Agent.build_prompt` method.
        system_info = {
            "machine": self.env.machine,
            "release": self.env.release,
            "system": self.env.system,
            "version": self.env.version,
        }

        system_info_block = f"""<system_information>
        {json.dumps(system_info, indent=2)}
        </system_information>"""
        self.system_prompt = (
            "You are a coding agent working in a terminal environment.\n"
            "Use the available tools to inspect the repository, reproduce the reported "
            "issue, identify the root cause, implement a focused fix, and run relevant tests.\n"
            "Continue until the task is complete. Do not claim success without verification.\n\n"
            f"{system_info_block}"
        )

        self.task_prompt = f"""Solve the following software engineering task:

        {self.task}"""
        # TODO(1.4): If any skills are available to the agent, make their
        # descriptions/metadata available to the agent in the prompt.

        if self.skills:
            catalog = "\n".join(
                skill["metadata"] for skill in self.skills.values()
            )
            self.system_prompt += (
                "\n\nReusable skills are available. "
                "Call `invoke_skill` with a skill name to load its instructions."
                f"\n\n<skills>\n{catalog}\n</skills>"
            )
    def execute_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Execute ``execute`` and ``send_message`` calls in the code sandbox."""

        # TODO(Part 1.3): Parse each call, execute recognized tools, and return
        # one message per call (there may be multiple tool calls in one agent
        # response!). Malformed JSON and unknown tools must become recoverable
        # observations relayed to the agent instead of exceptions.
        observations = []

        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")
            function = tool_call.get("function")
            result: str

            if not isinstance(function, dict):
                result = "Invalid tool call: missing function object."
            else:
                function_name = function.get("name")
                function_arguments = function.get("arguments")
                try:
                    args = json.loads(function_arguments)
                    if not isinstance(args, dict):
                        raise TypeError("tool arguments must be a JSON object")

                    if function_name == "execute":
                        result = format_tool_output(self.env.execute(**args))
                    elif function_name == "send_message":
                        summary = args.get("summary")
                        if isinstance(summary, str):
                            result = summary
                            self.finished = True
                        else:
                            result = "The summary argument must be a string."
                    elif function_name == "invoke_skill":
                        skill_name = args.get("name")
                        if isinstance(skill_name, str) and skill_name in self.skills:
                            result = self.skills[skill_name]["content"]
                        else:
                            result = "The skill name is not valid."
                    else:
                        result = f"Unknown tool: {function_name}."
                except (json.JSONDecodeError, TypeError) as error:
                    result = f"Invalid arguments for {function_name}: {error}"

            observations.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                }
            )

        return observations
