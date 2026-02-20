import time

from fastapi.testclient import TestClient

from openfinance.api.main import app


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 8.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row["status"] in {"done", "failed"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(f"task timeout: {task_id}")


def main() -> None:
    client = TestClient(app)
    ds = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr21_smoke_dataset",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-03-31",
            "seed": 21,
            "base_price": 100.0,
        },
    )
    ds.raise_for_status()
    done = _wait_task(client, ds.json()["task_id"])
    assert done["status"] == "done", f"dataset task failed: {done}"
    dataset_version = done["result"]["dataset_version"]

    formulas = [
        ("pr21_rank_mean_smoke", "Rank(Ts_Mean(close, 20))"),
        ("pr21_zscore_smoke", "ZScore(momentum_20)"),
        ("pr21_winsor_smoke", "Winsorize(Clip((close-open)/open, -0.2, 0.2), 0.05, 0.95)"),
    ]
    versions: list[str] = []
    for factor_id, formula in formulas:
        version = f"{factor_id}_v1"
        run = client.post(
            "/workbench/factors/run",
            json={
                "dataset_version": dataset_version,
                "factor_id": factor_id,
                "factor_version": version,
                "formula": formula,
                "inputs": ["close", "open", "volume"],
                "availability_lag": "0s",
                "decay_lags": 5,
            },
        )
        run.raise_for_status()
        payload = run.json()
        report = payload["report"]
        assert "turnover_proxy" in report
        assert "in_sample_ic_mean" in report
        assert "out_sample_ic_mean" in report
        assert "oos_split_ratio" in report
        versions.append(version)

    for version in versions:
        detail = client.get(f"/workbench/factors/{version}")
        detail.raise_for_status()
        report = detail.json().get("report") or {}
        assert "turnover_proxy" in report
        assert "in_sample_rank_ic_mean" in report
        assert "out_sample_rank_ic_mean" in report

    print("PR21 smoke passed.")
    print(f"dataset_version={dataset_version} factors={len(versions)}")


if __name__ == "__main__":
    main()

