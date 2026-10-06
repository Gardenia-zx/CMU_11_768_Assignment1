"""Tool definitions exposed to the model, in the OpenAI tool-calling format."""

EXECUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute",
        "description": (
            "Run a bash command and return its stdout, stderr, and exit code. "
            "A non-zero exit code is reported, not raised.\n"
            "\n"
            "Every command runs in a new subshell, so a `cd` or an export does not "
            "carry over to the next command. Use the `cwd` and `env` arguments "
            "instead. Files you write do persist.\n"
            "\n"
            "Commands are non-interactive and cannot prompt for input, so pass "
            "flags like `-y` where a command would otherwise ask for confirmation. "
            "Prefer commands that produce little output; when reading a file, use "
            "`head`, `tail`, or `sed -n '10,20p'` rather than printing all of it.\n"
            "\n"
            "Useful patterns:\n"
            "- Create a file: `cat <<'EOF' > newfile.py` ... `EOF`\n"
            "- Edit in place: `sed -i 's/old/new/g' filename.py` (drop the trailing "
            "`g` to replace only the first match; restrict to a line range with "
            "`sed -i '1,10s/old/new/g'`)\n"
            "- View numbered lines: `nl -ba filename.py | sed -n '10,20p'`"
        ),
        # The nested env object intentionally accepts arbitrary variable names,
        # which is incompatible with strict schemas on some providers.
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "anyOf": [
                        {
                            "type": "string",
                            "description": 'A shell command line, e.g. "ls -la | head".',
                        },
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                'The command as an argv list, e.g. ["ls", "-la"]. '
                                "Use this with shell=false when arguments contain "
                                "characters the shell would interpret."
                            ),
                        },
                    ],
                    "description": "The command to run.",
                },
                "shell": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Whether to run the command through a shell, which enables "
                        "pipes, redirection, and globbing. Defaults to true. Set to "
                        "false when passing an argv list."
                    ),
                },
                "cwd": {
                    "type": ["string", "null"],
                    "description": (
                        "Absolute path to run the command in. Defaults to the "
                        "sandbox's current working directory."
                    ),
                },
                "timeout": {
                    "type": ["number", "null"],
                    "description": (
                        "Seconds to allow the command to run before killing it. "
                        "Defaults to no timeout."
                    ),
                },
                "env": {
                    "type": ["object", "null"],
                    "additionalProperties": {"type": "string"},
                    "description": "Extra environment variables to set for this command.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

SEND_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_message",
        "description": ("Send a message to the user."),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": ("Content of the message"),
                },
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
}

INVOKE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "invoke_skill",
        "description": (
            "Load a skill and return its instructions. A skill is a short guide "
            "for one kind of work, written ahead of time.\n"
            "\n"
            "Call this before starting work a skill covers, and follow what it "
            "says in place of your default approach."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "The skill's directory name, for example `hello-skill`."
                    ),
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}

# TODO(3.1.a): Define an OpenAI function-tool schema named ``play_move``.
# It must accept exactly one required string argument named ``move``, explain
# that moves use UCI notation (for example e2e4), and reject extra arguments.
PLAY_MOVE_TOOL: dict = {
    "type":"function",
    "function": {
        "name": "play_move",
        "description": (
            "Play one legal move as White in the current live chess game. "
            "Use UCI notation, such as e2e4 or e7e8q for pawn promotion. "
            "The server automatically plays Black's reply and returns the updated game state. "
            "Call this tool at most once per assistant response."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "move":{
                    "type": "string",
                    "description": (
                        "The move in UCI notation: the starting square followed by the "
                        "destination square, for example e2e4. "
                        "For pawn promotion, append q, r, b, or n, for example e7e8q."
                    ),
                },
            },
            "required": ["move"],
            "additionalProperties": False,
        },
    },
}

# TODO(3.3): Define the `simulate_move` tool, like the `play_move` tool.
SIMULATE_MOVE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "simulate_move",
        "description": (
            "Inspect a chess position or simulate one legal move without changing "
            "the live game. Provide a complete six-field FEN. "
            "Omit move or pass null to inspect the position and its legal moves. "
            "Provide a UCI move to simulate exactly one ply for the side to move. "
            "No automatic opponent reply is played."
        ),
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "move":{
                    "type": ["string","null"],
                    "description": (
                        "An optional move in UCI notation, such as e2e4 or e7e8q. "
                        "Omit it or pass null to inspect the position without applying a move."
                    ),
                },
                "fen":{
                    "type": "string",
                    "description": "The complete six-field FEN describing the position to inspect or simulate.",
                },
            },
            "required": ["fen"],
            "additionalProperties": False,
        },
    },
}

# TODO()
RUN_PYTHON_TOOL: dict = {
    "type":"function",
    "function": {
        "name": "run_python",
        "description": (
            "Run Python code inside the chess sandbox to inspect positions, "
            "simulate candidate moves, and select a move. "
            "Use simulate_move for planning without changing the live game. "
            "Call play_move at most once to commit a move; "
            "the server automatically plays Black's reply. "
            "Returns captured stdout, stderr, and any Python exception."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code":{
                    "type": "string",
                    "description": (
                        "Python source code to execute in the chess sandbox. "
                        "Use print() to display results. "
                        "The synchronous functions simulate_move(fen, move=None) "
                        "and play_move(move) are available."
                    ),
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}
