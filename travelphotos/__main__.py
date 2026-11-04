"""Start the local web interface: python -m travelphotos"""

from __future__ import annotations

import argparse
import webbrowser

from .server import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m travelphotos", description="旅行照片整理（本機網頁介面）")
    parser.add_argument("--port", type=int, default=8765, help="本機連接埠，預設 8765；0 表示自動選")
    parser.add_argument("--input", default="", help="預先填入的照片資料夾")
    parser.add_argument("--no-browser", action="store_true", help="不要自動開啟瀏覽器")
    args = parser.parse_args(argv)

    server, url, _state = create_server(args.port, args.input)
    print(f"旅行照片整理已啟動：{url}")
    print("只在這台電腦上提供服務，照片不會上傳。按 Ctrl+C 結束。")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
