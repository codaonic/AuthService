/**
 * Auth Elements: put this service's sign-in inside your own page, styled to
 * match your design. The form runs in an iframe served by the auth service,
 * so the password never touches your page or its scripts. What you get back
 * is a one-time authorization code, which your backend exchanges at /token
 * like any other sign-in.
 *
 * An admin must first add your page's origin (e.g. https://app.example.com)
 * under the application's "Embed origins".
 *
 *   <script src="https://auth.example.com/static/js/auth-elements.js"></script>
 *   <div id="sign-in"></div>
 *   <script>
 *     const auth = AuthElements({
 *       clientId: "my-app",
 *       resource: "https://api.example.com",
 *       scope: "openid profile email",
 *       appearance: { colorPrimary: "#6b4eff", borderRadius: "12px", fontFamily: "Inter, sans-serif" },
 *     });
 *     const login = auth.create("login");          // or "signup"
 *     login.on("success", ({ code, codeVerifier }) => {
 *       // send both to your backend, which calls POST /token
 *     });
 *     login.on("error", (err) => console.error(err));
 *     login.mount("#sign-in");
 *   </script>
 *
 * PKCE: by default the verifier is made here in the browser and returned
 * with the code (fine for a public client). To keep it on your server
 * instead, create the challenge there and pass { codeChallenge } to create();
 * success then carries only the code.
 *
 * appearance: colorPrimary, colorPrimaryText, colorBackground,
 * colorInputBackground, colorText, colorTextSecondary, colorBorder,
 * colorDanger, fontFamily (unquoted names), borderRadius ("8px", "0.5rem"),
 * theme ("light" | "dark"). Anything else is ignored.
 */
window.AuthElements = (function () {
  var script = document.currentScript;
  var scriptOrigin = script && script.src ? new URL(script.src).origin : null;

  function randomString(bytes) {
    var data = crypto.getRandomValues(new Uint8Array(bytes));
    return base64url(data);
  }

  function base64url(bytes) {
    var str = "";
    for (var i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function pkceChallenge(verifier) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)).then(function (digest) {
      return base64url(new Uint8Array(digest));
    });
  }

  function AuthElements(options) {
    options = options || {};
    var issuer = (options.issuer || scriptOrigin || "").replace(/\/+$/, "");
    if (!issuer) throw new Error("AuthElements: pass { issuer } (the auth service's URL)");
    if (!options.clientId) throw new Error("AuthElements: pass { clientId }");
    if (!options.resource) throw new Error("AuthElements: pass { resource } (the API the token is for)");
    var issuerOrigin = new URL(issuer).origin;

    function create(screen, elementOptions) {
      if (screen !== "login" && screen !== "signup") {
        throw new Error('AuthElements: create("login") or create("signup")');
      }
      elementOptions = elementOptions || {};
      var handlers = { ready: [], success: [], error: [] };
      var frameId = randomString(16);
      var state = elementOptions.state || randomString(16);
      var iframe = null;
      var verifier = null;
      var readyTimer = null;

      function emit(event, payload) {
        handlers[event].forEach(function (fn) {
          fn(payload);
        });
      }

      function onMessage(event) {
        if (!iframe || event.source !== iframe.contentWindow || event.origin !== issuerOrigin) return;
        var data = event.data || {};
        if (data.frameId !== frameId || typeof data.type !== "string") return;

        if (data.type === "auth-elements:ready") {
          clearTimeout(readyTimer);
          emit("ready", {});
        } else if (data.type === "auth-elements:resize" && data.height > 0) {
          iframe.style.height = data.height + "px";
        } else if (data.type === "auth-elements:success") {
          if (data.state !== state) {
            emit("error", new Error("AuthElements: state mismatch -- sign-in result ignored"));
            return;
          }
          var result = { code: data.code, state: state };
          if (verifier) result.codeVerifier = verifier;
          emit("success", result);
        }
      }

      function mount(target) {
        var container = typeof target === "string" ? document.querySelector(target) : target;
        if (!container) throw new Error("AuthElements: mount target not found");
        if (iframe) throw new Error("AuthElements: already mounted");

        var challenge = elementOptions.codeChallenge
          ? Promise.resolve(elementOptions.codeChallenge)
          : pkceChallenge((verifier = randomString(48)));

        return challenge.then(function (codeChallenge) {
          var params = new URLSearchParams({
            response_type: "code",
            response_mode: "web_message",
            client_id: options.clientId,
            resource: options.resource,
            scope: options.scope || "",
            code_challenge: codeChallenge,
            code_challenge_method: "S256",
            state: state,
            origin: window.location.origin,
            frame_id: frameId,
            screen: screen,
            appearance: JSON.stringify(options.appearance || {}),
          });

          iframe = document.createElement("iframe");
          iframe.src = issuer + "/authorize?" + params.toString();
          iframe.title = screen === "signup" ? "Create account" : "Sign in";
          iframe.style.cssText = "width:100%;border:0;display:block;color-scheme:normal;height:" + (options.height || 460) + "px";
          // Passkeys need the iframe to be allowed to use WebAuthn.
          iframe.allow = "publickey-credentials-get";
          // The whole flow (sign-in, signup, forgot password) stays inside the
          // frame: no top-level navigation and no popups from it.
          iframe.setAttribute("sandbox", "allow-forms allow-scripts allow-same-origin");

          window.addEventListener("message", onMessage);
          readyTimer = setTimeout(function () {
            emit(
              "error",
              new Error(
                "AuthElements: sign-in did not load -- check that " +
                  window.location.origin +
                  " is listed under this application's Embed origins",
              ),
            );
          }, options.loadTimeoutMs || 15000);
          container.appendChild(iframe);
        });
      }

      function unmount() {
        clearTimeout(readyTimer);
        window.removeEventListener("message", onMessage);
        if (iframe && iframe.parentNode) iframe.parentNode.removeChild(iframe);
        iframe = null;
      }

      return {
        mount: mount,
        unmount: unmount,
        on: function (event, fn) {
          if (!handlers[event]) throw new Error("AuthElements: unknown event " + event);
          handlers[event].push(fn);
          return this;
        },
      };
    }

    return { create: create };
  }

  return AuthElements;
})();
