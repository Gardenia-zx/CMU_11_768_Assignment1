---
name: select-move-v2
description: Choose White moves using two-ply minimax with material and piece activity, plus history-aware repetition and recent-reversal preferences. Use for programmatic chess strategy experiments.
---

# Select move v2

Use this strategy when loaded. Keep the original select-move skill as the
baseline for comparison.

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

Read /api/state from http://127.0.0.1 on the server port in sys.argv[1] to obtain
the current FEN and complete history. This request is read-only. Use the supplied
functions for all simulations and commits.

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
(b1/g1 for knights, c1/f1 for bishops), that square has never been touched, and
the candidate moves it off White's back rank. Also retain the last eight actual
White moves; these are eight White turns, not eight plies.

## Two-ply search

On the first full move, choose the first legal move from e2e4, d2d4, c2c4, g1f3
without searching. Commit this opening inside run_python as well. If none is
legal, use the search below.

Otherwise sort the current legal White moves by UCI. For every candidate,
simulate White's move, then simulate every legal Black reply. Evaluate each
result with the same complete evaluation and take the minimum score for that
candidate. Evaluate reported terminal positions immediately. Search exactly
two plies: one White move and one Black reply. Do not extend captures, add a
third ply, or deepen the search. Activity calculation uses only the leaf board
and makes no extra simulation requests.

## Evaluation

All nonterminal components are measured from White's perspective:

- Material: pawn 100, knight 320, bishop 330, rook 500, queen 900, king 0.
  Add White's values and subtract Black's.
- Center: each piece on d4, e4, d5, or e5 contributes +12 for White or -12
  for Black.
- Check: +25 if Black is in check, -25 if White is in check, otherwise 0.
- Activity: calculate weighted activity for each side, then add White's
  activity minus Black's activity.

For each knight, bishop, rook, and queen, count its attacked squares after
excluding friendly-occupied squares and squares attacked by enemy pawns.
Intersect the remaining squares with its absolute-pin direction mask; an
unpinned piece has the full-board mask. Each remaining target contributes
4 for a knight, 3 for a bishop, 2 for a rook, or 1 for a queen. Do not count
pawns or kings as active pieces, but do use pawn attacks to filter the targets.

This is an approximate measure of piece activity, not a count of legal moves
or a guarantee that each target is safe. It handles absolute pins and pawn
attacks, but not every tactical threat or check-evasion restriction. Calculate
both sides identically, regardless of whose turn it is. Moving a pawn can earn
activity value by opening another piece's line. Returning a piece to a cramped
square can lose that value; development therefore has a persistent effect.

Return +100000 for a reported White win, -100000 for a Black win, and 0 for a
reported draw before adding any positional terms. Otherwise:

    score = material + center + check + white_activity - black_activity

Captures and immediate recaptures are already reflected in the material of
the leaf after Black's reply. Do not add a separate capture bonus or subtract
a piece's full value merely because it is attacked. A longer exchange or a
plan beyond Black's immediate reply remains outside this search. Activity
weights are initial experimental values; they do not guarantee a win or
eliminate all cycles. Keep them fixed within a comparison run.

## Root tie-breaking

For each White candidate, maximize this tuple lexicographically:

    (score, -repeat_count, -recent_reversal, develops_piece, castles)

- repeat_count: prior occurrences of the position immediately after this White
  candidate, counting actual recorded positions of both colors.
- recent_reversal: 1 if the candidate reverses the source and destination
  of any of the last eight actual White moves, otherwise 0. This catches a
  short return even when another White piece moved in between.
- develops_piece: 1 for first development as defined above, otherwise 0.
- castles: 1 for a legal White castle, otherwise 0.

Activity is part of score and therefore precedes all history preferences;
whole-position novelty alone is not progress. These preferences only decide
between equally scored candidates, never ban a legal move, and never override
a strictly better score. Only replace the best candidate when its entire tuple
is strictly greater. Initial UCI ordering settles a complete tie.

These history preferences apply only at the root. The simulation API lacks
repetition history, so this is not a complete history-aware draw search. A
recent reversal is a heuristic rather than proof of repetition. Reported draws
remain worth 0, and repeated moves remain available when needed.

## Reference snippet

Use this implementation in run_python. Candidate printing may be adjusted;
retain the chosen move's rank, worst Black reply, and evaluation components.
Preserve the evaluation, two-ply search, history checks, and single final commit.
Do not follow a successful snippet with another play_move call for the same turn.

~~~python
import sys
from collections import Counter

import chess
import httpx

VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
ACTIVITY_WEIGHTS = {
    chess.KNIGHT: 4, chess.BISHOP: 3, chess.ROOK: 2, chess.QUEEN: 1,
}
HOMES = {
    chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT,
    chess.C1: chess.BISHOP, chess.F1: chess.BISHOP,
}

def position_key(fen):
    position = chess.Board(fen)
    return " ".join(position.fen(en_passant="legal").split()[:4])

def activity(position, color):
    friendly = chess.SquareSet(position.occupied_co[color])
    enemy_pawn_attacks = chess.SquareSet()
    for square in position.pieces(chess.PAWN, not color):
        enemy_pawn_attacks |= position.attacks(square)
    total = 0
    for piece_type, weight in ACTIVITY_WEIGHTS.items():
        for square in position.pieces(piece_type, color):
            targets = position.attacks(square) - friendly - enemy_pawn_attacks
            targets &= position.pin(color, square)
            total += weight * len(targets)
    return total

def evaluate(state):
    if state["game_over"]:
        winner = state.get("winner")
        score = 100000 if winner == "white" else -100000 if winner == "black" else 0
        return score, {"terminal": state["status"], "score": score}
    position = chess.Board(state["fen"])
    material = 0
    center = 0
    for square, piece in position.piece_map().items():
        sign = 1 if piece.color == chess.WHITE else -1
        material += sign * VALUES[piece.symbol().lower()]
        if square in CENTER:
            center += sign * 12
    check = (25 if state["turn"] == "black" else -25) if state["in_check"] else 0
    white_activity = activity(position, chess.WHITE)
    black_activity = activity(position, chess.BLACK)
    activity_score = white_activity - black_activity
    score = material + center + check + activity_score
    return score, {
        "material": material, "center": center, "check": check,
        "white_activity": white_activity, "black_activity": black_activity,
        "activity": activity_score, "score": score,
    }

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
    recent_white = []
    for entry in live["history"]:
        move = chess.Move.from_uci(entry["uci"])
        if board.turn == chess.WHITE:
            recent_white.append(move)
        touched.update((move.from_square, move.to_square))
        board.push_uci(entry["uci"])
        counts[position_key(board.fen())] += 1
    recent_white = recent_white[-8:]

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
    best_reply = None
    best_parts = {"opening": True}
    if board.fullmove_number == 1:
        best = next((m for m in ("e2e4", "d2d4", "c2c4", "g1f3") if m in legal), None)

    if best is None:
        for candidate in legal:
            after = simulate_move(root["fen"], candidate)
            worst_reply = None
            if after["game_over"]:
                score, parts = evaluate(after)
            else:
                score = None
                for reply in sorted(after["legal_moves"]):
                    reply_state = simulate_move(after["fen"], reply)
                    reply_score, reply_parts = evaluate(reply_state)
                    if score is None or reply_score < score:
                        score, parts = reply_score, reply_parts
                        worst_reply = reply
                if score is None:
                    raise ValueError("Nonterminal simulation has no legal Black reply.")

            move = chess.Move.from_uci(candidate)
            piece = board.piece_at(move.from_square)
            repeat_count = counts[position_key(after["fen"])]
            recent_reversal = int(any(
                move.from_square == previous.to_square
                and move.to_square == previous.from_square
                for previous in recent_white
            ))
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
            rank = (score, -repeat_count, -recent_reversal, develops_piece, castles)
            print(candidate, "RANK", rank, "WORST_REPLY", worst_reply)
            if best_rank is None or rank > best_rank:
                best, best_rank = candidate, rank
                best_reply, best_parts = worst_reply, parts

    print("CHOSEN", best, "RANK", best_rank)
    print("WORST_REPLY", best_reply, "PARTS", best_parts)
    play_move(best)
~~~

For comparison runs, record the chosen move's rank, worst reply, material,
both sides' activity, final game result, total plies, and model request count.
Compare long quiet stretches and repeated piece paths as well as outcomes.
More captures alone do not prove improvement: preserve net material and check
whether the pieces become more active. A step-limit stop is an unfinished game
when game_over is false. Run the actual game only when the user requests it.
