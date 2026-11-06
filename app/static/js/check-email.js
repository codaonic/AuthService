// "Check your email": asks every few seconds whether the link has been
// opened (in any tab or on any device) and carries on with the sign-in by
// itself when it has. Works the same inside an embedded sign-in.
(function () {
  var form = document.getElementById("check-email-continue");
  var status = document.getElementById("check-email-status");
  if (!form || !window.fetch) return;

  var url = form.getAttribute("data-status-url");
  var started = Date.now();
  var stopped = false;

  function next() {
    // Every 2 seconds at first, then every 5 once it's been a few minutes.
    var delay = Date.now() - started < 3 * 60 * 1000 ? 2000 : 5000;
    setTimeout(check, delay);
  }

  function check() {
    if (stopped) return;
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (body) {
        if (body.verified) {
          stopped = true;
          status.textContent = "Email verified. Signing you in…";
          status.hidden = false;
          form.submit();
        } else if (body.expired) {
          stopped = true;
          status.textContent = "This sign-in has expired. Go back to the app and log in again.";
          status.hidden = false;
        } else {
          next();
        }
      })
      .catch(next);
  }

  next();
})();
