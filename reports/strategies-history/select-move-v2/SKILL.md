---
name: select-move-v2
description: Choose White moves using two-ply minimax with history-aware tie-breaking for repeated positions, first development, and castling. Use for programmatic chess strategy experiments.
---

# Select move v2

Use this strategy instead of the original select-move strategy when this skill
is loaded. Keep the original skill as the baseline for comparison.

## Execution contract

Choose and commit each White move inside one run_python snippet.
simulate_move(fen, move=None) inspects a hypothetical position; supplying a UCI
move applies exactly one ply without changing the live game or invoking the bot.
play_move(move) commits a White move and automatically triggers Black's reply.
Call it exactly once, as the final statement of a move-producing snippet.
Read the resulting updated board before choosing another move.

The sandbox already provides simulate_move and play_move. It also has chess
and httpx installed. This skill permits importing chess, httpx, sys, and
collections. Each run_python call starts a fresh namespace: include the required
definitions and retrieve a fresh snapshot on every turn.

## History and position identity

The current runner receives the chess server port in sys.argv[1]. Read
/api/state from http://127.0.0.1 on that port to obtain the current FEN and the
complete history. This is a read-only request. Use the supplied functions for
all simulations and commits.

The assignment starts from the standard chess position. Reconstruct a
chess.Board by replaying every history entry's UCI move, recording the initial
position and the position after every ply. Require its canonical full FEN to
match the live snapshot before searching. If history cannot be retrieved or
reconstructed consistently, report the error without committing a move.

A position key is the first four fields of board.fen(en_passant="legal"):
piece placement, side to move, castling rights, and legal en-passant information.
Exclude both move counters. A repeated UCI move alone is not a repeated position.

Track all previously touched source and destination squares. A knight or bishop
qualifies for first development only when it is still on its original square
(b1/g1 for knights, c1/f1 for bishops), that square has never been touched by a
previous move, and the candidate moves it off White's back rank. This prevents
rewarding the same piece for repeatedly leaving and returning.

## Search and primary score

On the first full move, choose the first legal move from e2e4, d2d4, c2c4, g1f3
without searching. Commit this opening inside run_python as well. If none is
legal, use the search below.

Otherwise sort the current legal White moves by UCI. For every candidate:
simulate White's move, then simulate every legal Black reply. Evaluate each
result and take the minimum score for that candidate. Evaluate reported
terminal positions immediately. Search exactly two plies.

Keep the original primary evaluation, from White's perspective:

- White wins: +100000; Black wins: -100000; any reported draw: 0.
- Material: pawn 100, knight 320, bishop 330, rook 500, queen 900, king 0.
  Add White's values and subtract Black's.
- Each piece on d4, e4, d5, or e5: +12 for White, -12 for Black.
- If the side to move is in check: +25 when it is Black, -25 when it is White.

Do not add development or repetition penalties to this primary score.

## Root tie-breaking

For each White candidate, compute this tuple and maximize it lexicographically:

    (score, -repeat_count, develops_piece, castles, -reverses_last_move)

- repeat_count: prior occurrences of the position immediately after this White
  candidate, counting actual recorded positions of both colors.
- develops_piece: 1 for first development as defined above, otherwise 0.
- castles: 1 for a legal White castle, otherwise 0.
- reverses_last_move: 1 if the candidate reverses the source and destination
  of the previous actual White move, otherwise 0.

Because score is first, these preferences only decide between equally scored
candidates. They never ban a move or override a strictly better primary score.
Only replace the best candidate when its entire tuple is strictly greater.
The initial UCI ordering settles a complete tie.

These are root preferences; Black's simulated replies still minimize the
unchanged primary score. A reversal is only a heuristic, not proof of repetition.
The simulation API lacks repetition history. This version uses real history
for tie-breaking; it does not implement a complete history-aware draw search.
Reported draws remain worth 0, and a repeated move remains available when needed.

## Reference snippet

Use the following implementation in run_python. Diagnostic printing may be
adjusted; preserve the search, ranking, and single final commit. Do not follow
a successful snippet with a standalone play_move tool call for the same turn.

~~~python
import sys
from collections import Counter

import chess
import httpx

VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
CENTER = {"d4", "e4", "d5", "e5"}
HOMES = {
    chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT,
    chess.C1: chess.BISHOP, chess.F1: chess.BISHOP,
}

def position_key(fen):
    board = chess.Board(fen)
    return " ".join(board.fen(en_passant="legal").split()[:4])

def evaluate(state):
    if state["game_over"]:
        winner = state.get("winner")
        return 100000 if winner == "white" else -100000 if winner == "black" else 0
    score = 0
    for square, piece in state["squares"].items():
        sign = 1 if piece.isupper() else -1
        score += sign * VALUES[piece.lower()]
        if square in CENTER:
            score += sign * 12
    if state["in_check"]:
        score += 25 if state["turn"] == "black" else -25
    return score

port = int(sys.argv[1])
with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
    response = client.get("/api/state")
    response.raise_for_status()
    live = response.json()

if live["game_over"]:
    print("GAME_OVER", live["status"])
else:
    board = chess.Board()
    counts = Counter({position_key(board.fen()): 1})
    touched = set()
    last_white = None
    for entry in live["history"]:
        move = chess.Move.from_uci(entry["uci"])
        if board.turn == chess.WHITE:
            last_white = move
        touched.update((move.from_square, move.to_square))
        board.push_uci(entry["uci"])
        counts[position_key(board.fen())] += 1

    current = chess.Board(live["fen"])
    if board.fen(en_passant="legal") != current.fen(en_passant="legal"):
        raise ValueError("Recorded history does not match the live FEN.")
    if board.turn != chess.WHITE:
        raise ValueError("The live game is not ready for a White move.")

    root = simulate_move(live["fen"])
    legal = sorted(root["legal_moves"])
    if not legal:
        raise ValueError("No legal White move is available.")

    best = None
    best_rank = None
    if board.fullmove_number == 1:
        best = next((m for m in ("e2e4", "d2d4", "c2c4", "g1f3") if m in legal), None)

    if best is None:
        for candidate in legal:
            after = simulate_move(root["fen"], candidate)
            if after["game_over"]:
                score = evaluate(after)
            else:
                score = min(
                    evaluate(simulate_move(after["fen"], reply))
                    for reply in sorted(after["legal_moves"])
                )

            move = chess.Move.from_uci(candidate)
            piece = board.piece_at(move.from_square)
            repeat_count = counts[position_key(after["fen"])]
            develops_piece = int(
                move.from_square in HOMES
                and move.from_square not in touched
                and piece.color == chess.WHITE
                and piece.piece_type == HOMES[move.from_square]
                and chess.square_rank(move.to_square) > 0
            )
            castles = int(
                piece.piece_type == chess.KING
                and candidate in ("e1g1", "e1c1")
            )
            reverses_last_move = int(
                last_white is not None
                and move.from_square == last_white.to_square
                and move.to_square == last_white.from_square
            )
            rank = (score, -repeat_count, develops_piece, castles, -reverses_last_move)
            print(candidate, "RANK", rank)
            if best_rank is None or rank > best_rank:
                best, best_rank = candidate, rank

    print("CHOSEN", best, "RANK", best_rank)
    play_move(best)
~~~

When comparing with the baseline, retain the chosen move, its rank, the final
game result, and the number of model requests. A different move in the recorded
tie position is evidence of changed selection, not a guarantee of winning.
