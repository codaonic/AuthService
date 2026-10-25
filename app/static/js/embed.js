/**
 * Runs inside an embedded sign-in page (see app/oidc/embed.py and
 * auth-elements.js). Talks only to the one origin this flow was opened for,
 * and only with the page that embedded it:
 *
 *   auth-elements:ready    the form is showing
 *   auth-elements:resize   { height } -- so the iframe can fit its content
 *   auth-elements:success  { code, state } -- the one-time authorization code
 */
(function () {
  var body = document.body;
  var origin = body.dataset.embedOrigin;
  var frameId = body.dataset.frameId;
  if (!origin || window.parent === window) return;

  function send(type, extra) {
    var message = { type: "auth-elements:" + type, frameId: frameId };
    for (var key in extra || {}) message[key] = extra[key];
    window.parent.postMessage(message, origin);
  }

  if (body.dataset.result === "success") {
    send("success", { code: body.dataset.code, state: body.dataset.state || null });
    return;
  }

  var page = document.querySelector(".page") || body;
  function resize() {
    send("resize", { height: Math.ceil(page.getBoundingClientRect().height) });
  }
  send("ready");
  resize();
  if (window.ResizeObserver) new ResizeObserver(resize).observe(page);
  else window.addEventListener("resize", resize);
})();
