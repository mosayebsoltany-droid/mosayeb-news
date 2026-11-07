from pathlib import Path
from fastapi import Request
from fastapi.responses import HTMLResponse

APP_DIR = Path(__file__).resolve().parent.parent


def nonce_html(html: str, request: Request):
    nonce = request.state.csp_nonce
    return HTMLResponse(html.replace("<script", f'<script nonce="{nonce}"').replace(
        "<style", f'<style nonce="{nonce}"'))


def local_page(name: str, request: Request):
    return nonce_html((APP_DIR / name).read_text(encoding="utf-8"), request)
