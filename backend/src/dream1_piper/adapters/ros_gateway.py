import json
import uuid

from websockets.asyncio.client import connect


class RosGateway:
    def __init__(self, url):
        self.url = url

    async def request(self, kind, payload):
        request = {"request_id": str(uuid.uuid4()), "type": kind, "payload": payload}
        async with connect(self.url, open_timeout=1.0, close_timeout=1.0, max_size=2**20) as socket:
            await socket.send(json.dumps(request))
            response = json.loads(await socket.recv())
        if not response.get("accepted", False):
            raise RuntimeError(response.get("reason", "ROS bridge rejected request"))
        return response

    async def status(self):
        return await self.request("status", {})

    async def command(self, kind, payload):
        return await self.request(kind, payload)
