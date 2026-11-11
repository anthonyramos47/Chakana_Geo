"""
Run a standalone, shared kayviz viewer:

    python -m kayviz [--port 8000] [--host 127.0.0.1]
    python -m kayviz --host 0.0.0.0 --allow-network     # reachable from other machines

Scripts and notebooks that call ``kayviz.init()`` while it is running attach
to it and push geometry there, so several of them can feed one window.
"""

import argparse


def main(argv=None) -> None:
    import uvicorn
    from kayviz.server import create_app, ws_impl, WS_MAX_SIZE
    from kayviz.security import is_loopback

    parser = argparse.ArgumentParser(prog="kayviz", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--allow-network", action="store_true",
                        help="serve a non-local --host: anyone who can reach this machine "
                             "on --port sees the scene and can run its GUI actions")
    args = parser.parse_args(argv)

    network = not is_loopback(args.host)
    if network and not args.allow_network:
        parser.error(f"--host {args.host} makes the viewer reachable from other machines, "
                     f"with no password: anyone who can reach port {args.port} sees the "
                     f"scene and can run its GUI actions. Add --allow-network to do it.")
    if network:
        print(f"[kayviz] WARNING: serving on {args.host}:{args.port} — reachable from the "
              f"network, without authentication.", flush=True)

    print(f"[kayviz] Shared viewer at http://{args.host}:{args.port}/?app=script", flush=True)
    app = create_app(shared=True, default_app="script", network=network)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port,
                                           log_level="warning", ws=ws_impl(),
                                           ws_max_size=WS_MAX_SIZE,
                                           timeout_graceful_shutdown=2))
    app.state.shutdown = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
