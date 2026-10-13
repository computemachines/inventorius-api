import os
import uvicorn
from .server import InventoryReader, create_app

reader = InventoryReader(
    os.environ["INVENTORIUS_MCP_API_URL"], os.environ["INVENTORIUS_MCP_PUBLIC_URL"],
    os.environ["INVENTORIUS_DEPLOYMENT_ENVIRONMENT"],
)
uvicorn.run(create_app(reader), host="0.0.0.0", port=8002, proxy_headers=False,
            access_log=False, log_level="warning", limit_concurrency=32)
