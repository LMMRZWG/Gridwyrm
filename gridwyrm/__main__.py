"""Entry point, so the package can be started with python -m gridwyrm."""

from .app import App


def main():
    App().run()


if __name__ == "__main__":
    main()
