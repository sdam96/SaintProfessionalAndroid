import flet as ft

from ui.app import SaintApp


async def main(page: ft.Page) -> None:
    SaintApp(page).start()


ft.run(main)