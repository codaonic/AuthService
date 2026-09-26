document.addEventListener("click", (event) => {
  const toggle = event.target.closest(".toggle-visibility");
  if (!toggle) return;

  const input = document.getElementById(toggle.dataset.target);
  if (!input) return;

  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  toggle.setAttribute("aria-pressed", String(!showing));
  toggle.setAttribute("aria-label", showing ? "Show password" : "Hide password");
  toggle.querySelector(".icon-eye").hidden = !showing;
  toggle.querySelector(".icon-eye-off").hidden = showing;
});

document.querySelectorAll("form.form").forEach((form) => {
  form.addEventListener("submit", () => {
    form.querySelectorAll("button[type=submit]").forEach((btn) => {
      btn.disabled = true;
    });
  });
});
