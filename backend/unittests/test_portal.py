"""门户公开接口单元测试。"""
from app import create_app


def test_portal_summary_public():
    app = create_app()
    client = app.test_client()
    res = client.get("/api/portal/summary")
    assert res.status_code == 200
    body = res.get_json()
    assert body["code"] == 0
    data = body["data"]
    for key in (
        "modelTotal",
        "readyCount",
        "datasetTotal",
        "jobTotal",
        "jobsRunning",
        "taskKinds",
        "categoryKinds",
        "taskDistribution",
        "categoryRanking",
    ):
        assert key in data
