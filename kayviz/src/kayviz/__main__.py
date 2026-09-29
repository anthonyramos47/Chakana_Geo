"""
Run a standalone, shared kayviz viewer:

    python -m kayviz [--port 8000] [--host 127.0.0.1]

Scripts and notebooks that call ``kayviz.init()`` while it is running attach
to it and push geometry there, so several of them can feed one window.
"""

import argparse


def main(argv=None) -> None:
    import uvicorn
    from kayviz.server import create_app

    parser = argparse.ArgumentParser(prog="kayviz", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    print(f"[kayviz] Shared viewer at http://{args.host}:{args.port}/?app=script", flush=True)
    uvicorn.run(create_app(shared=True, default_app="script"),
                host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
