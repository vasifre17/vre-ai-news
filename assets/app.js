const root = document.documentElement;
const btn = document.getElementById('themeToggle');
if (btn) {
  btn.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', root.dataset.theme);
  });
  const saved = localStorage.getItem('theme');
  if (saved) root.dataset.theme = saved;
}

const categoryMenus = document.querySelectorAll('.category-menu');
categoryMenus.forEach((menu) => {
  const button = menu.querySelector('.category-menu-button');
  if (!button) return;

  const dropdown = menu.querySelector('.category-dropdown');
  if (dropdown) dropdown.hidden = true;

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const isOpen = !menu.classList.contains('is-open');
    menu.classList.toggle('is-open', isOpen);
    button.setAttribute('aria-expanded', String(isOpen));
    if (dropdown) dropdown.hidden = !isOpen;

    categoryMenus.forEach((otherMenu) => {
      if (otherMenu === menu) return;
      otherMenu.classList.remove('is-open');
      const otherButton = otherMenu.querySelector('.category-menu-button');
      const otherDropdown = otherMenu.querySelector('.category-dropdown');
      if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
      if (otherDropdown) otherDropdown.hidden = true;
    });
  });
});

document.addEventListener('click', (event) => {
  categoryMenus.forEach((menu) => {
    if (menu.contains(event.target)) return;
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    const dropdown = menu.querySelector('.category-dropdown');
    if (button) button.setAttribute('aria-expanded', 'false');
    if (dropdown) dropdown.hidden = true;
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  categoryMenus.forEach((menu) => {
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    const dropdown = menu.querySelector('.category-dropdown');
    if (button) button.setAttribute('aria-expanded', 'false');
    if (dropdown) dropdown.hidden = true;
  });
});

const buildVreycPlaceholder = (className = '') => {
  const placeholder = document.createElement('div');
  placeholder.className = `image-placeholder ${className}`.trim();
  placeholder.textContent = 'VREYC';
  return placeholder;
};

document.querySelectorAll('img').forEach((image) => {
  image.addEventListener('error', () => {
    if (image.dataset.placeholderApplied === '1') return;
    image.dataset.placeholderApplied = '1';
    const compact = image.closest('.related-card') ? 'related-placeholder' : (image.closest('.article-image-frame') ? 'article-image-placeholder' : 'compact');
    image.replaceWith(buildVreycPlaceholder(compact));
  });
});
