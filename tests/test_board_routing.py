import httpx
import pytest

from hermes_clickup_sync.hermes import HermesClient


def test_get_board_rejects_payload_that_disagrees_with_board_listing():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/boards"):
            return httpx.Response(
                200,
                json={"boards": [{"slug": "default", "name": "Default", "total": 0}]},
            )
        if request.url.path.endswith("/board"):
            return httpx.Response(
                200,
                json={
                    "columns": [
                        {"name": "todo", "tasks": [{"id": "t_wrong", "status": "todo"}]}
                    ]
                },
            )
        raise AssertionError(str(request.url))

    http = httpx.Client(
        base_url="http://hermes.local",
        transport=httpx.MockTransport(handler),
    )
    client = HermesClient("http://hermes.local", http=http)

    client.list_boards()

    with pytest.raises(RuntimeError, match="board routing mismatch"):
        client.get_board("default")
