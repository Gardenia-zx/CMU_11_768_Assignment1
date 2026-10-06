import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx

from assignment.agent.chess_agent import ChessAgent


def execute_in_docker(command: list[str], *, shell: bool = False) -> dict:
    """Execute a sandbox command in the running local chess container."""
    if shell:
        raise ValueError("Docker adapter requires shell=False")

    completed = subprocess.run(
        ["docker", "exec", "assignment-chess-local", *command],
        capture_output=True,
        text=True,
        check=False,
    )

    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output": completed.stdout + completed.stderr,
        "returncode": completed.returncode,
        "exception_info": "",
    }


def main():
    project_dir = Path(__file__).resolve().parents[1]
    output_dir = project_dir / "artifacts"
    parser = argparse.ArgumentParser(
        description="Play chess against the existing local Docker server."
    )
    parser.add_argument("--model", help="Override OPENAI_MODEL for this run.")
    parser.add_argument(
        "--play-move-only",
        action="store_true",
        help="Enable only play_move for the observation A/B experiment.",
    )
    parser.add_argument("--omit-legal-moves", action="store_true")
    parser.add_argument("--step-limit", type=int, default=200)
    parser.add_argument(
        "--trajectory", type=Path, default=output_dir / "part3-trajectory.json"
    )
    parser.add_argument(
        "--result", type=Path, default=output_dir / "game-result.json"
    )
    args = parser.parse_args()
    if args.step_limit < 1:
        parser.error("--step-limit must be positive")
    args.trajectory.parent.mkdir(parents=True, exist_ok=True)
    args.result.parent.mkdir(parents=True, exist_ok=True)

    server_url = "http://127.0.0.1:8000"

    with httpx.Client(base_url=server_url, timeout=20) as client:
        agent = ChessAgent(
            environment=SimpleNamespace(
                server_url=server_url,
                execute=execute_in_docker,
            ),
            http_client=client,
            model=args.model,
            programmatic_tools=not args.play_move_only,
            skills_path=(
                None
                if args.play_move_only
                else str(project_dir / "tasks" / "chess-skills")
            ),
            include_legal_moves=not args.omit_legal_moves,
            logs_save_path=str(args.trajectory),
            step_limit=args.step_limit,
            auto_stop_environment=False,
        )

        try:
            agent.run()
        finally:
            args.result.write_text(
                json.dumps(agent.last_state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    print(f"game_over: {agent.last_state.get('game_over')}")
    print(f"Trajectory: {args.trajectory}")
    print(f"Result: {args.result}")


if __name__ == "__main__":
    main()
