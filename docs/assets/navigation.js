// Native buttons provide keyboard activation; the theme still owns panel state.
document.addEventListener('click', (event) => {
  const control = event.target.closest('button[data-toggle]');
  if (!control) return;
  const target = document.getElementById(control.dataset.toggle);
  if (!target) return;
  target.click();
  control.setAttribute('aria-expanded', String(target.checked));
});

document.addEventListener('change', (event) => {
  if (!['__drawer', '__search'].includes(event.target.id)) return;
  const control = document.querySelector(`button[data-toggle="${event.target.id}"]`);
  if (control) control.setAttribute('aria-expanded', String(event.target.checked));
});
