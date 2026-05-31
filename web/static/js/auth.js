// Login / register form handling.
const form = document.getElementById('auth-form');
const mode = form.dataset.mode;          // "login" | "register"
const err = document.getElementById('err');
const submit = document.getElementById('submit');

function toast(msg, kind = 'err') {
  const w = document.getElementById('toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  w.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  err.textContent = '';
  const email = form.email.value.trim();
  const password = form.password.value;
  if (!email || !password) { err.textContent = 'Please fill in both fields.'; return; }

  submit.disabled = true;
  const label = submit.textContent;
  submit.innerHTML = '<span class="spinner"></span>';
  try {
    const res = await fetch('/api/' + (mode === 'login' ? 'login' : 'register'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) { window.location.href = '/app'; return; }
    err.textContent = data.error || 'Something went wrong.';
    toast(data.error || 'Request failed.');
  } catch (_) {
    err.textContent = 'Network error. Please try again.';
    toast('Network error.');
  }
  submit.disabled = false;
  submit.textContent = label;
});
