"""用现有回测引擎驱动只在本机监听的策略界面。"""

from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from inspect import signature
import json
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter

import pandas as pd
import yaml

from .signals import FACTORS
from .workflow import _demo_prices, analyze

logger = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
EDITABLE = {
    "evaluation_start", "evaluation_end", "initial_cash", "commission", "slippage",
    "sell_fee", "lot_size", "max_exposure", "max_weight", "entry", "exit", "z_window",
    "top_n", "rank_buffer", "rebalance_every", "min_assets", "ic_min_assets",
    "ic_window", "ic_min_periods", "forward_period", "normalization", "weighting",
    "allow_short", "contract_multiplier", "margin_rate", "max_contracts",
    "fee_per_contract", "factors",
}


@lru_cache(maxsize=6)
def _read_csv(path, modified, size):
    """按文件版本缓存，回测前由引擎复制和校验输入。"""
    return pd.read_csv(path, dtype={"symbol": "string"}, encoding="utf-8-sig")


def _records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=12))


class Dashboard:
    def __init__(self, config):
        self.config = config
        self.data_root = Path(config["project"]["data_dir"]).resolve()
        self.profiles = {
            name: {**config.get("backtest", {}), **settings}
            for name, settings in config["research"]["profiles"].items()
        }
        self.lock = Lock()

    def _files(self):
        files = {}
        for path in sorted(self.data_root.glob("*.csv")):
            resolved = path.resolve()
            if resolved.parent == self.data_root and resolved.is_file():
                files[path.name] = resolved
        return files

    def _prices(self, dataset, files):
        if dataset == "demo":
            return _demo_prices(), "stock"
        if dataset not in files:
            raise ValueError("所选 CSV 不在项目行情目录")
        path = files[dataset]
        stat = path.stat()
        frame = _read_csv(path, stat.st_mtime_ns, stat.st_size)
        market = "future" if dataset.startswith("future_") else "stock"
        if not {"date", "open", "close"}.issubset(frame.columns) or frame.empty:
            raise ValueError(f"{dataset} 缺少 date、open、close 或没有记录")
        if "symbol" not in frame:
            parts = dataset.split("_")
            symbol = parts[1] if len(parts) >= 3 and parts[0] in {"stock", "future"} else None
            frame = frame.assign(symbol=symbol or self.config[market]["default_symbol"])
        return frame, market

    def catalog(self):
        files = self._files()
        sources = []
        for name in [*files, "demo"]:
            try:
                frame, market = self._prices(name, files)
                dates = pd.to_datetime(frame["date"])
                if dates.isna().all():
                    raise ValueError("没有有效交易日期")
                sources.append({
                    "id": name,
                    "market": market,
                    "synthetic": name == "demo",
                    "symbols": sorted(frame["symbol"].dropna().astype(str).str.strip().unique()),
                    "first": dates.min().date().isoformat(),
                    "last": dates.max().date().isoformat(),
                })
            except (ValueError, TypeError, OSError) as error:
                sources.append({"id": name, "error": str(error)})
        return {
            "datasets": sources,
            "profiles": self.profiles,
            "factor_types": {
                key: {name: parameter.default for name, parameter in signature(factor).parameters.items()}
                for key, factor in FACTORS.items()
            },
        }

    def run(self, request):
        if not isinstance(request, dict):
            raise ValueError("回测参数须为 JSON 对象")
        profile = request.get("profile")
        dataset = request.get("dataset")
        if not isinstance(profile, str) or profile not in self.profiles or not isinstance(dataset, str):
            raise ValueError("请选择策略和行情")
        custom = request.get("settings", {})
        if not isinstance(custom, dict) or set(custom) - EDITABLE:
            raise ValueError("回测参数包含未知字段")
        settings = {**self.profiles[profile], **custom}
        if not isinstance(settings["factors"], dict) or not 1 <= len(settings["factors"]) <= 32:
            raise ValueError("请选择 1 到 32 个因子")
        if any(value is None for key, value in custom.items() if key not in {"evaluation_start", "evaluation_end"}):
            raise ValueError("数值控件须填写有效数字")
        frame, market = self._prices(dataset, self._files())
        if market != settings["market"]:
            raise ValueError("行情类别与策略不匹配")
        symbol = request.get("symbol")
        if settings["mode"] == "timing":
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("请选择一个标的")
            frame = frame.loc[frame["symbol"].astype("string").str.strip().eq(symbol)]
            settings["symbols"] = [symbol]
            if frame.empty:
                raise ValueError("行情中没有所选标的")
        else:
            symbol = None
        started = perf_counter()
        tables = analyze(frame, settings)
        seconds = perf_counter() - started
        equity_cols = ["equity", "drawdown", "gross_exposure_ratio"]
        curves = tables["equity"][equity_cols].add_prefix("strategy_").join(
            tables["benchmark_equity"][equity_cols].add_prefix("benchmark_")
        )
        saved = {key: self.config[key] for key in ("project", "stock", "future", "backtest")}
        saved["research"] = {"default_profile": "dashboard_strategy", "profiles": {"dashboard_strategy": settings}}
        return {
            "dataset": dataset,
            "profile": profile,
            "symbol": symbol,
            "seconds": round(seconds, 3),
            "metrics": _records(tables["metrics"].reset_index()),
            "curves": _records(curves.reset_index()),
            "factors": _records(tables["ic_summary"].reset_index()),
            "trade_count": len(tables["trades"]),
            "trades": _records(tables["trades"].tail(100).iloc[::-1]),
            "trades_csv": tables["trades"].to_csv(index=False),
            "curves_csv": curves.to_csv(),
            "yaml": yaml.safe_dump(saved, allow_unicode=True, sort_keys=False),
        }


def serve(config, port):
    if not 1 <= port <= 65535:
        raise ValueError("端口须在 1 到 65535 之间")
    dashboard = Dashboard(config)
    logging.getLogger("factor_miner.engine.broker").setLevel(logging.WARNING)
    local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in local_hosts}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, data):
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def _local_request(self):
            return self.headers.get("Host") in local_hosts and self.headers.get("Origin") in origins | {None}

        def do_GET(self):
            if not self._local_request():
                self._json(HTTPStatus.FORBIDDEN, {"error": "界面仅供本机使用"})
            elif self.path in ASSETS:
                name, content_type = ASSETS[self.path]
                self._send(HTTPStatus.OK, (STATIC / name).read_bytes(), content_type)
            elif self.path == "/api/catalog":
                self._json(HTTPStatus.OK, dashboard.catalog())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "未知页面"})

        def do_POST(self):
            if not self._local_request():
                self._json(HTTPStatus.FORBIDDEN, {"error": "请求来源不匹配"})
                return
            if self.path != "/api/run":
                self._json(HTTPStatus.NOT_FOUND, {"error": "未知接口"})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "需要 JSON 请求"})
                return
            if not dashboard.lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "当前已有回测运行，请稍后重试"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("请求大小超出范围")
                payload = json.loads(self.rfile.read(size))
                result = dashboard.run(payload)
            except (ValueError, TypeError, KeyError, OSError, OverflowError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception:
                logger.exception("本机研究界面回测失败")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "回测失败，请查看启动终端"})
            else:
                self._json(HTTPStatus.OK, result)
            finally:
                dashboard.lock.release()

        def log_message(self, format, *args):
            logger.debug(format, *args)

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"策略研究台 http://127.0.0.1:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
