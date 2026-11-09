from __future__ import annotations

import asyncio
import os
import sys

import httpx

BASE = os.environ.get("ARBITERFORGE_BASE_URL", "http://127.0.0.1:8023")


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@arbiterforge.local", "password": "ChangeMe123!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        opened = await client.post(
            "/api/v1/cases", json={"title": "Демо конкурентной записи"}, headers=headers
        )
        opened.raise_for_status()
        case_id, version = opened.json()["case_id"], opened.json()["version"]
        racers = [
            client.post(
                f"/api/v1/cases/{case_id}/commands/file",
                params={"filing_ref": f"RACE-{n}"},
                headers={**headers, "If-Match": f'"{version}"'},
            )
            for n in range(2)
        ]
        codes = sorted(r.status_code for r in await asyncio.gather(*racers))
        print(f"case {case_id}: concurrent writers with If-Match {version} -> {codes}")
        return 0 if codes == [200, 409] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
