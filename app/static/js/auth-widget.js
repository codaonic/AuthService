/**
 * A tiny, framework-agnostic helper for embedding this auth service's
 * login/signup as a popup instead of a full-page redirect -- the site
 * keeps its own button/design, the popup is still this service's own
 * hosted page (optionally themed per client, see Client.logo_url/
 * brand_color), so the password never touches the site's own code.
 *
 * Usage (from the site that owns the popup's opener window):
 *
 *   AuthWidget.openPopup("/login?popup=1")
 *     .then(() => { // signed in -- refetch whatever depends on that })
 *     .catch((err) => { if (err.message !== "cancelled") showError(err); });
 *
 * The URL passed in is *your own* login-initiation endpoint (the one that
 * redirects to this auth service's /authorize with a PKCE challenge you
 * generated) -- not this auth service's /authorize directly, since PKCE's
 * verifier has to be known server-side to complete the code exchange. See
 * examples/website_bff for a full worked example, including the ~3 lines
 * your own callback route needs to close the popup and signal this file.
 */
window.AuthWidget = (function () {
  function openPopup(url, options) {
    options = options || {};
    var width = options.width || 480;
    var height = options.height || 640;
    var left = window.screenX + (window.outerWidth - width) / 2;
    var top = window.screenY + (window.outerHeight - height) / 2;

    var popup = window.open(
      url,
      "auth-widget",
      "width=" + width + ",height=" + height + ",left=" + left + ",top=" + top + ",resizable=yes,scrollbars=yes",
    );

    if (!popup) {
      var blocked = new Error("Popup was blocked -- call openPopup() from a direct click handler, not async code.");
      if (options.onError) options.onError(blocked);
      return Promise.reject(blocked);
    }

    return new Promise(function (resolve, reject) {
      var settled = false;

      function cleanup() {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
      }

      function onMessage(event) {
        if (event.source !== popup) return;
        var data = event.data;
        if (!data || data.type !== "auth-widget:complete") return;
        settled = true;
        cleanup();
        if (data.success) {
          if (options.onSuccess) options.onSuccess(data);
          resolve(data);
        } else {
          var err = new Error(data.error || "Sign-in failed");
          if (options.onError) options.onError(err);
          reject(err);
        }
      }

      window.addEventListener("message", onMessage);

      // The user can also just close the popup (its X button) without it
      // ever sending a message -- treat that as cancellation, not an error.
      var pollClosed = setInterval(function () {
        if (popup.closed && !settled) {
          settled = true;
          cleanup();
          var err = new Error("cancelled");
          if (options.onCancel) options.onCancel();
          reject(err);
        }
      }, 400);
    });
  }

  return { openPopup: openPopup };
})();
