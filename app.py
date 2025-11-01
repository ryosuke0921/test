from __future__ import annotations

import json
import math
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class OptimizationResult:
    rolls: List[int]
    z_length: float
    total_width_usage: float
    slack: float
    total_rolls: int
    total_instruction: float
    differences: List[float]
    produced_lengths: List[float]
    objective: float


class OptimizationError(Exception):
    """Raised when optimization cannot produce a feasible plan."""


def _validate_inputs(
    base_width: float, max_length: float, widths: Sequence[float], instructions: Sequence[float]
) -> None:
    if base_width <= 0:
        raise OptimizationError("原反幅は正の数で入力してください。")
    if max_length <= 0:
        raise OptimizationError("原反巻き数 (長さ) は正の数で入力してください。")
    if len(widths) != len(instructions):
        raise OptimizationError("スリット幅と指示数の数が一致しません。")
    if not widths:
        raise OptimizationError("スリット幅と指示数を入力してください。")
    for idx, width in enumerate(widths):
        if width <= 0:
            raise OptimizationError(f"スリット幅#{idx + 1}は正の数で入力してください。")
    for idx, inst in enumerate(instructions):
        if inst < 0:
            raise OptimizationError(f"スリット指示数#{idx + 1}は0以上で入力してください。")


@dataclass
class SearchState:
    widths: List[float]
    instructions: List[float]
    effective_width: float
    max_length: float
    extra_margin: int = 5
    weight_diff: float = 10.0
    weight_slack: float = 1.0
    weight_rolls: float = 0.1

    def optimize(self) -> OptimizationResult:
        best: Optional[OptimizationResult] = None
        current: List[int] = []

        max_roll_options = self._compute_roll_limits()

        def backtrack(index: int, width_usage: float) -> None:
            nonlocal best
            if index == len(self.widths):
                total_rolls = sum(current)
                if total_rolls == 0:
                    return
                result = self._evaluate_combination(current, width_usage)
                if result is None:
                    return
                if best is None or self._is_better(result, best):
                    best = result
                return

            width = self.widths[index]
            min_roll, max_roll = max_roll_options[index]
            for rolls in range(min_roll, max_roll + 1):
                new_width_usage = width_usage + width * rolls
                if new_width_usage - self.effective_width > 1e-9:
                    break
                current.append(rolls)
                backtrack(index + 1, new_width_usage)
                current.pop()

        backtrack(0, 0.0)
        if best is None:
            raise OptimizationError("条件を満たす組み合わせが見つかりませんでした。")
        return best

    def _compute_roll_limits(self) -> List[Tuple[int, int]]:
        limits: List[Tuple[int, int]] = []
        for width, inst in zip(self.widths, self.instructions):
            min_roll = 0
            width_limit = max(0, int(self.effective_width // width))
            approx_rolls = 0
            if self.max_length > 0:
                approx_rolls = math.ceil(inst / self.max_length) if inst > 0 else 0
            max_roll = min(width_limit, approx_rolls + self.extra_margin)
            if max_roll < min_roll:
                max_roll = min_roll
            limits.append((min_roll, max_roll))
        return limits

    def _evaluate_combination(
        self, rolls: Sequence[int], width_usage: float
    ) -> Optional[OptimizationResult]:
        total_rolls = sum(rolls)
        if total_rolls == 0:
            return None

        candidate_lengths = self._candidate_lengths(rolls)
        if not candidate_lengths:
            return None

        best_result: Optional[OptimizationResult] = None
        for length in candidate_lengths:
            if length <= 0 or length - self.max_length > 1e-9:
                continue
            produced = [length * r for r in rolls]
            diffs = [abs(prod - inst) for prod, inst in zip(produced, self.instructions)]
            slack = self.effective_width - width_usage
            objective = (
                self.weight_diff * sum(diffs)
                + self.weight_slack * slack
                + self.weight_rolls * total_rolls
            )
            candidate = OptimizationResult(
                rolls=list(rolls),
                z_length=length,
                total_width_usage=width_usage,
                slack=slack,
                total_rolls=total_rolls,
                total_instruction=sum(self.instructions),
                differences=diffs,
                produced_lengths=produced,
                objective=objective,
            )
            if best_result is None or self._is_better(candidate, best_result):
                best_result = candidate
        return best_result

    def _candidate_lengths(self, rolls: Sequence[int]) -> List[float]:
        candidates: set[float] = set()
        total_rolls = sum(rolls)
        if total_rolls == 0:
            return []
        total_instruction = sum(self.instructions)
        average_length = total_instruction / total_rolls
        candidates.add(min(self.max_length, average_length))
        for inst, r in zip(self.instructions, rolls):
            if r > 0:
                candidates.add(min(self.max_length, inst / r))
        return sorted(candidates)

    def _is_better(self, a: OptimizationResult, b: OptimizationResult) -> bool:
        if abs(a.objective - b.objective) > 1e-6:
            return a.objective < b.objective
        if abs(a.slack - b.slack) > 1e-6:
            return a.slack < b.slack
        diff_sum_a = sum(a.differences)
        diff_sum_b = sum(b.differences)
        if abs(diff_sum_a - diff_sum_b) > 1e-6:
            return diff_sum_a < diff_sum_b
        if a.total_rolls != b.total_rolls:
            return a.total_rolls < b.total_rolls
        return a.z_length > b.z_length


def optimize_slitting(
    base_width: float, max_length: float, widths: Sequence[float], instructions: Sequence[float]
) -> OptimizationResult:
    effective_width = base_width - 10.0
    if effective_width <= 0:
        raise OptimizationError("原反幅から10mm引いた値が0以下のため計算できません。")
    _validate_inputs(base_width, max_length, widths, instructions)
    state = SearchState(
        widths=[float(w) for w in widths],
        instructions=[float(x) for x in instructions],
        effective_width=effective_width,
        max_length=max_length,
    )
    return state.optimize()


class SlittingRequestHandler(BaseHTTPRequestHandler):
    server_version = "SlittingOptimizer/1.0"

    base_dir = Path(__file__).resolve().parent
    template_dir = base_dir / "templates"
    static_dir = base_dir / "static"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(self.template_dir / "index.html", content_type="text/html; charset=utf-8")
            return
        if self.path.startswith("/static/"):
            relative = Path(self.path[len("/static/") :])
            requested = (self.static_dir / relative).resolve()
            try:
                requested.relative_to(self.static_dir)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return
            self._serve_file(requested)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/optimize":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json_response({"success": False, "message": "JSONの形式が正しくありません。"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            base_width = float(payload.get("baseWidth", 0))
            max_length = float(payload.get("maxLength", 0))
            widths = [float(item) for item in payload.get("widths", [])]
            instructions = [float(item) for item in payload.get("instructions", [])]
            result = optimize_slitting(base_width, max_length, widths, instructions)
            response = {
                "rolls": result.rolls,
                "zLength": result.z_length,
                "widthUsage": result.total_width_usage,
                "slack": result.slack,
                "totalRolls": result.total_rolls,
                "produced": result.produced_lengths,
                "differences": result.differences,
            }
            self._json_response({"success": True, "result": response})
        except OptimizationError as exc:
            self._json_response({"success": False, "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json_response({"success": False, "message": "予期しないエラーが発生しました。"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_file(self, path: Path, *, content_type: Optional[str] = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        if content_type is None:
            content_type = self._guess_type(path)
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "ファイルを読み込めませんでした。")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_response(self, payload: Dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _guess_type(self, path: Path) -> str:
        if path.suffix == ".js":
            return "application/javascript; charset=utf-8"
        if path.suffix == ".css":
            return "text/css; charset=utf-8"
        if path.suffix == ".json":
            return "application/json; charset=utf-8"
        if path.suffix == ".html":
            return "text/html; charset=utf-8"
        return "application/octet-stream"


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), SlittingRequestHandler)
    print(f"Serving on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
