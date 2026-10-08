document.addEventListener("click", (event) => {
  const toggle = event.target.closest(".toggle-visibility");
  if (!toggle) return;

  const input = document.getElementById(toggle.dataset.target);
  if (!input) return;

  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  toggle.setAttribute("aria-pressed", String(!showing));
  toggle.setAttribute("aria-label", showing ? "Show password" : "Hide password");
});

document.querySelectorAll("form.form").forEach((form) => {
  form.addEventListener("submit", () => {
    // Deferred: disabling a submit button synchronously here would drop its
    // name/value from the in-flight submission if it's the one that was
    // clicked (e.g. consent.html's Allow/Deny, where that value is the
    // whole point) -- the browser only reads submitter name/value before
    // the submit event finishes, but disabled state is checked at that same
    // point, so a same-tick disable excludes it. Deferring to the next tick
    // still disables well before a human could double-click.
    setTimeout(() => {
      form.querySelectorAll("button[type=submit]").forEach((btn) => {
        btn.disabled = true;
      });
    }, 0);
  });
});
