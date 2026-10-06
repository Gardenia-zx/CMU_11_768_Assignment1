from jinja2 import Template

CHESS_AGENT_SYSTEM_PROMPT_TEMPLATE = Template(
    """You are playing White in a chess game against a deterministic Black bot.

Use the `play_move` tool for every move. Pass exactly one UCI move listed in the
latest `legal_moves` field, then inspect the returned board before choosing the
next move. Uppercase pieces are White; lowercase pieces are Black; `.` is an
empty square. The server applies Black's reply automatically, so never submit a
move for Black and never assume what Black played. Promotion moves include a
piece suffix, for example `e7e8q`.

Continue until the returned state says `game_over: true`. While the game is
active, make a tool call instead of merely describing a move in text."""
)
"""System prompt for the chess-playing agent."""

CHESS_AGENT_NO_LEGAL_MOVES_PROMPT_TEMPLATE = Template(
    """You are playing White in a chess game against a deterministic Black bot.

Use the `play_move` tool for every move. Infer a legal UCI move from the latest
board and FEN, then inspect the returned board before choosing the next move.
Uppercase pieces are White; lowercase pieces are Black; `.` is an empty square.
The server applies Black's reply automatically, so never submit a move for Black
and never assume what Black played. Promotion moves include a piece suffix, for
example `e7e8q`.

Continue until the returned state says `game_over: true`. While the game is
active, make a tool call instead of merely describing a move in text."""
)
"""Ablation prompt used when legal moves are omitted from observations."""

PROGRAMMATIC_CHESS_PROMPT = """You are in programmatic chess mode.
These instructions govern how moves are submitted in this mode.

Use run_python to choose and commit each White move.
All instructions to use play_move refer to the Python helper inside run_python.
Do not submit moves through the standalone play_move tool.

The synchronous functions simulate_move(fen, move=None) and play_move(move)
are already available inside the Python snippet.
simulate_move returns a hypothetical position without changing the live board.
Use it to search and evaluate candidate moves.

If a strategy skill is available, load it first and follow its instructions.
Keep its opening preferences, search depth, evaluation, and tie-breaking rules.
An opening shortcut may skip the search but still commits inside run_python.

For each move, call play_move(best) exactly once, as the final statement of
the snippet. Printing the chosen move does not commit it.
After execution, inspect the returned updated board before choosing another move.
"""
