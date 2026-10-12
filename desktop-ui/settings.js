const form = document.getElementById('form');
const error = document.getElementById('error');
window.solobino.getConfig().then(config => {
  document.getElementById('backendUrl').value = config.backendUrl || '';
  document.getElementById('token').value = config.token || '';
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';
  try {
    await window.solobino.saveConfig({
      backendUrl: document.getElementById('backendUrl').value.trim(),
      token: document.getElementById('token').value,
    });
  } catch (exc) { error.textContent = exc.message; }
});
