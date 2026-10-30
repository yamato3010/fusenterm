"""fusen - エントリーポイント"""

from .app import FusenApp


def main() -> None:
    app = FusenApp()
    app.run()


if __name__ == "__main__":
    main()
