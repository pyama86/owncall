"""CLI entry point for OwnCall."""

import argparse
import asyncio
import logging


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OwnCall: MCP-powered Slack bot for Grafana/Prometheus alert investigation"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yml",
        help="Path to config YAML file (default: config.yml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from owncall.app import run_bot
    from owncall.config import load_config

    config = load_config(args.config)
    asyncio.run(run_bot(config))
