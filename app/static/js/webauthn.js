function base64urlToBuffer(base64url) {
  const padding = "=".repeat((4 - (base64url.length % 4)) % 4);
  const base64 = (base64url + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buffer = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buffer[i] = raw.charCodeAt(i);
  return buffer.buffer;
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeCreationOptions(json) {
  return {
    ...json,
    challenge: base64urlToBuffer(json.challenge),
    user: { ...json.user, id: base64urlToBuffer(json.user.id) },
    excludeCredentials: (json.excludeCredentials || []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
  };
}

function decodeRequestOptions(json) {
  return {
    ...json,
    challenge: base64urlToBuffer(json.challenge),
    allowCredentials: (json.allowCredentials || []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
  };
}

function encodeAttestationCredential(credential) {
  return JSON.stringify({
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    response: {
      attestationObject: bufferToBase64url(credential.response.attestationObject),
      clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
      transports: credential.response.getTransports ? credential.response.getTransports() : [],
    },
  });
}

function encodeAssertionCredential(credential) {
  return JSON.stringify({
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    response: {
      authenticatorData: bufferToBase64url(credential.response.authenticatorData),
      clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
      signature: bufferToBase64url(credential.response.signature),
      userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : undefined,
    },
  });
}

async function loginWithPasskey(button) {
  const flowId = button.dataset.flowId;
  const email = document.getElementById("email").value.trim();
  if (!email) {
    alert("Enter your email first, then use the passkey button.");
    return;
  }

  button.disabled = true;
  try {
    const optsResp = await fetch("/webauthn/login/options", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ flow_id: flowId, email }),
    });
    if (!optsResp.ok) {
      const err = await optsResp.json().catch(() => ({}));
      alert(err.detail || "No passkey is registered for this account.");
      return;
    }
    const options = decodeRequestOptions(await optsResp.json());
    const assertion = await navigator.credentials.get({ publicKey: options });

    const form = document.getElementById("webauthn-login-form");
    form.querySelector('input[name="credential"]').value = encodeAssertionCredential(assertion);
    form.submit();
  } catch (err) {
    alert("Passkey sign-in was cancelled or failed.");
  } finally {
    button.disabled = false;
  }
}

async function registerPasskey(button) {
  button.disabled = true;
  try {
    const optsResp = await fetch("/account/webauthn/register/options", { method: "POST" });
    if (!optsResp.ok) {
      alert("Could not start passkey registration.");
      return;
    }
    const options = decodeCreationOptions(await optsResp.json());
    const credential = await navigator.credentials.create({ publicKey: options });
    const nickname = prompt('Name this passkey (e.g. "MacBook Touch ID")', "") || "";

    const form = document.getElementById("webauthn-register-form");
    form.querySelector('input[name="credential"]').value = encodeAttestationCredential(credential);
    form.querySelector('input[name="nickname"]').value = nickname;
    form.submit();
  } catch (err) {
    alert("Passkey registration was cancelled or failed.");
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const loginBtn = event.target.closest("[data-webauthn-login]");
  if (loginBtn) {
    event.preventDefault();
    loginWithPasskey(loginBtn);
    return;
  }
  const registerBtn = event.target.closest("[data-webauthn-register]");
  if (registerBtn) {
    event.preventDefault();
    registerPasskey(registerBtn);
  }
});
