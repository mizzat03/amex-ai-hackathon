"""CLI entry point for the separate synthetic producer process."""

import argparse
import asyncio
from uuid import uuid4

import redis.asyncio as redis

from backend.config import get_settings
from simulator.service import SimulatorService


async def run(command: str) -> None:
    settings = get_settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    service = SimulatorService(client, settings)
    request_id = f"cli_{uuid4().hex}"
    try:
        await service.initialize()
        if command == "start":
            result = await service.start(request_id)
        elif command == "inject":
            await service.start(f"{request_id}_start")
            result = await service.inject(request_id)
        elif command == "recover":
            await service.start(f"{request_id}_start")
            await service.inject(f"{request_id}_inject")
            result = await service.recover(request_id)
        elif command == "reset":
            result = await service.reset(request_id, "RESET_SYNTHETIC_DEMO")
        else:
            raise ValueError(f"unsupported command {command}")
        print(result.model_dump_json(indent=2))
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic AMEX incident demo producer")
    parser.add_argument("command", choices=("start", "inject", "recover", "reset"))
    args = parser.parse_args()
    asyncio.run(run(args.command))


if __name__ == "__main__":
    main()
