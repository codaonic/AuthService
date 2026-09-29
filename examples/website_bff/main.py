"""Minimal "Backend-For-Frontend" (BFF) website integration.

The pattern: the browser only ever holds an opaque, HttpOnly session cookie
for THIS backend. Access/refresh tokens from the auth service live only on
this server, in a server-side session store -- never sent to, or readable
by, the browser or its JavaScript. When this site needs to call another API
on the user's behalf, it does so itself, server-side, and returns the
result; the token never travels any further than this process.

Register a confidential client for this example first, from the auth
service's own repo:

    uv run python -m app.cli register-client \\
        --client-id website-bff-example \\
        --type confidential \\
        --redirect-uri http://localhost:9003/callback \\
        --grant-type authorization_code --grant-type refresh_token

Copy the printed client_secret into CLIENT_SECRET below, then:

    uv sync
    uv run uvicorn main:app --reload --port 9003

Then open http://localhost:9003 in a browser. "Call the downstream API on
your behalf" talks to ../example_api -- run that too (port 9001) to see it
actually resolve, or just watch it fail with a clear connection error if
you haven't.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

ISSUER = "http://localhost:8000"
CLIENT_ID = "website-bff-example"
CLIENT_SECRET = "REPLACE_WITH_THE_SECRET_PRINTED_AT_REGISTRATION"
REDIRECT_URI = "http://localhost:9003/callback"
RESOURCE = "https://api.example.com"  # the downstream API this site calls on the user's behalf
SCOPE = "openid profile email"
DOWNSTREAM_API = "http://localhost:9001/me"  # ../example_api

SESSION_COOKIE = "bff_session"

app = FastAPI(title="Example website (BFF pattern)")

# In-memory stores for this example only -- a real deployment would use
# Redis or a database, the same way the auth service itself does.
PENDING_LOGINS: dict[str, dict] = {}  # state -> {"verifier", "popup"}
SESSIONS: dict[str, dict] = {}  # session_id -> {"access_token", "refresh_token", "sub", "email"}


def _make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    session = SESSIONS.get(request.cookies.get(SESSION_COOKIE))
    widget_script = f'<script src="{ISSUER}/static/js/auth-widget.js"></script>'

    if session is None:
        # Two ways to log in, both hitting the same /login route -- only the
        # UX differs. The full-page link is the baseline that always works;
        # the styled button demonstrates AuthWidget.openPopup(): this site's
        # own markup/CSS, a popup for the actual (this-service-hosted) form,
        # and no page navigation away from this site at all.
        return f"""
        <h1>Example website (BFF pattern)</h1>
        <p><a href="/login">Log in (full-page redirect)</a></p>
        <button id="popup-login" style="font: inherit; padding: 10px 18px; border-radius: 8px;
            border: none; background: #111827; color: #fff; cursor: pointer;">
          Sign in with Acme
        </button>
        {widget_script}
        <script>
          document.getElementById("popup-login").addEventListener("click", function () {{
            AuthWidget.openPopup("/login?popup=1")
              .then(function () {{ window.location.reload(); }})
              .catch(function (err) {{ if (err.message !== "cancelled") alert(err.message); }});
          }});
        </script>
        """

    return f"""
    <h1>Example website (BFF pattern)</h1>
    <p>Logged in as <strong>{session['email']}</strong>.</p>
    <p>Your browser never saw a token -- only an opaque session cookie.</p>
    <p><a href="/call-api">Call the downstream API on your behalf</a></p>
    <p><a href="/logout">Log out</a></p>
    """


@app.get("/login")
async def login(popup: bool = False):
    verifier, challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(16)
    PENDING_LOGINS[state] = {"verifier": verifier, "popup": popup}

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "resource": RESOURCE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": SCOPE,
        "state": state,
    }
    return RedirectResponse(f"{ISSUER}/authorize?{urlencode(params)}")


@app.get("/callback")
async def callback(code: str, state: str):
    pending = PENDING_LOGINS.pop(state, None)
    if pending is None:
        return HTMLResponse("Invalid or expired login attempt. <a href='/login'>Try again</a>.", status_code=400)

    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            f"{ISSUER}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": pending["verifier"],
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        # Ask the auth service who this token belongs to, rather than
        # decoding the JWT ourselves -- one fewer dependency, and it's the
        # auth service's job to say what a token means, not this site's.
        userinfo_resp = await http.get(
            f"{ISSUER}/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        userinfo_resp.raise_for_status()
        who = userinfo_resp.json()

    session_id = secrets.token_urlsafe(32)
    SESSIONS[session_id] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "sub": who["sub"],
        "email": who["email"],
    }

    if pending["popup"]:
        # No redirect back to "/" here -- this response IS still the popup
        # window. Tell the opener it's done and close, instead of navigating
        # the popup anywhere. AuthWidget listens for exactly this message.
        response = HTMLResponse(
            "<script>"
            "window.opener.postMessage({type: 'auth-widget:complete', success: true}, window.location.origin);"
            "window.close();"
            "</script>"
        )
    else:
        response = RedirectResponse("/")
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax")
    return response


@app.get("/call-api")
async def call_api(request: Request):
    session = SESSIONS.get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return RedirectResponse("/login")

    async with httpx.AsyncClient() as http:
        try:
            resp = await http.get(
                DOWNSTREAM_API, headers={"Authorization": f"Bearer {session['access_token']}"}
            )
            body = f"{resp.status_code}: {resp.text}"
        except httpx.ConnectError:
            body = f"Couldn't reach {DOWNSTREAM_API} -- is ../example_api running on port 9001?"

    return HTMLResponse(f"<pre>{body}</pre><p><a href='/'>Back</a></p>")


@app.get("/logout")
async def logout(request: Request):
    SESSIONS.pop(request.cookies.get(SESSION_COOKIE), None)
    response = RedirectResponse("/")
    response.delete_cookie(SESSION_COOKIE)
    return response
