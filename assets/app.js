const root=document.documentElement;
const btn=document.getElementById('themeToggle');
if(btn){btn.addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';localStorage.setItem('theme',root.dataset.theme);});
const saved=localStorage.getItem('theme');if(saved)root.dataset.theme=saved;}

const categoryMenus = document.querySelectorAll('.category-menu');
categoryMenus.forEach((menu) => {
  const button = menu.querySelector('.category-menu-button');
  if (!button) return;

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const isOpen = menu.classList.toggle('is-open');
    button.setAttribute('aria-expanded', String(isOpen));

    categoryMenus.forEach((otherMenu) => {
      if (otherMenu === menu) return;
      otherMenu.classList.remove('is-open');
      const otherButton = otherMenu.querySelector('.category-menu-button');
      if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
    });
  });
});

document.addEventListener('click', (event) => {
  categoryMenus.forEach((menu) => {
    if (menu.contains(event.target)) return;
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    if (button) button.setAttribute('aria-expanded', 'false');
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  categoryMenus.forEach((menu) => {
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    if (button) button.setAttribute('aria-expanded', 'false');
  });
});
