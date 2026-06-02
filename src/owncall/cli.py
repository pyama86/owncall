"""CLI entry point for OwnCall."""

import argparse
import asyncio
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OwnCall: MCP-powered Slack bot for Grafana/Prometheus alert investigation"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yml",
        help=(
            "Path to a config YAML file, or a directory containing multiple "
            "*.yml config files (one bot per file, started concurrently). "
            "Default: config.yml"
        ),
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

    from owncall.app import run_bot, run_bots
    from owncall.config import load_config

    if os.path.isdir(args.config):
        config_files = sorted(
            f for f in (
                os.path.join(args.config, name)
                for name in os.listdir(args.config)
                if name.endswith(".yml") or name.endswith(".yaml")
            )
            if os.path.isfile(f)
        )
        if not config_files:
            raise SystemExit(f"No .yml/.yaml files found in directory: {args.config}")
        logging.getLogger(__name__).info(
            "Loading %d config file(s) from %s", len(config_files), args.config
        )
        configs = [load_config(f) for f in config_files]
        asyncio.run(run_bots(configs))
    else:
        config = load_config(args.config)
        asyncio.run(run_bot(config))
